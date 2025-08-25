from __future__ import annotations

import re
from pathlib import Path
import typer

from ..util.console import success, error

app = typer.Typer(help="Link a local folder that contains a runner.json")

_ALIAS_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _slugify_dir_name(name: str) -> str:
    """
    Best-effort alias suggestion from a directory name:
    - lowercase
    - spaces -> '-'
    - keep only [a-z0-9._-]
    - trim to 64, ensure starts with [a-z0-9]
    """
    s = name.strip().lower().replace(" ", "-")
    s = "".join(ch for ch in s if ch.isalnum() or ch in "._-")
    if not s or not s[0].isalnum():
        s = f"x-{s}" if s else "x"
    return s[:64]


@app.command()
def main(
    path: str = typer.Argument(..., help="Path to the local project folder"),
    as_alias: str | None = typer.Option(
        None, "--as", help="Alias to assign to this path"
    ),
    alias: str | None = typer.Option(
        None, "--alias", help="Alias to assign to this path"
    ),
):
    """
    Link a local folder (that already contains a runner.json) to an alias.

    Examples:
      matrix link ./my-server --as my-svc
      matrix link ./my-server --alias my-svc
      matrix link ./my-server              # falls back to folder name (slugified)
    """
    from matrix_sdk.alias import AliasStore

    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        error(f"Path not found or not a directory: '{p}'")
        raise typer.Exit(1)

    rj = p / "runner.json"
    if not rj.is_file():
        error(f"A 'runner.json' file was not found in '{p}'.")
        raise typer.Exit(1)

    # Prefer --as, then --alias, then slugified folder name
    chosen = as_alias or alias or _slugify_dir_name(p.name)

    # Validate alias format (same policy as deep-link UI)
    if not _ALIAS_RX.match(chosen):
        raise typer.BadParameter(
            f"Alias must match [a-z0-9][a-z0-9._-]{{0,63}} (got: {chosen!r}). "
            "Tip: use lowercase, digits, '.', '_' or '-'."
        )

    # Persist alias mapping (id is a local pseudo-id)
    AliasStore().set(chosen, id=f"local/{p.name}@dev", target=str(p))

    # Keep wording predictable so smoke/pytest can match 'linked'
    success(f"linked {p} as {chosen}")
