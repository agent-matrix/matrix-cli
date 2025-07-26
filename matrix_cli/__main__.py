from __future__ import annotations

import importlib
import sys
from importlib import metadata
from typing import Optional

import typer

from .config import MatrixCLIConfig, load_config

# Create the top-level Typer app
app = typer.Typer(
    name="matrix",
    help="Matrix Hub CLI — search, show, install agents/tools, and manage remotes.",
    add_completion=True,
    no_args_is_help=True,
)


def _register_subapp(module_name: str, name: str) -> None:
    """
    Dynamically import a commands module that is expected to expose `app: Typer`,
    then attach it as a subcommand group under `name`.
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - defensive
        # Fail soft if a commands module is missing; the rest of the CLI still works.
        typer.echo(f"[warn] Unable to load commands from {module_name}: {exc}", err=True)
        return

    sub = getattr(mod, "app", None)
    if sub is None:  # pragma: no cover
        typer.echo(f"[warn] Module {module_name} does not export `app`", err=True)
        return

    app.add_typer(sub, name=name)


# Register command groups
_register_subapp("matrix_cli.commands.search", "search")
_register_subapp("matrix_cli.commands.show", "show")
_register_subapp("matrix_cli.commands.install", "install")
_register_subapp("matrix_cli.commands.list", "list")
_register_subapp("matrix_cli.commands.remotes", "remotes")


def _version_string() -> str:
    try:
        return metadata.version("matrix-cli")
    except metadata.PackageNotFoundError:  # pragma: no cover
        return "0.0.0"


@app.callback()
def _global_options(
    ctx: typer.Context,
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Override registry base URL for this command (e.g., http://localhost:7300).",
        show_default=False,
    ),
    token: Optional[str] = typer.Option(
        None,
        "--token",
        help="Override registry bearer token for this command.",
        show_default=False,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Verbose output.",
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        help="Show matrix-cli version and exit.",
        callback=None,
        is_eager=True,
    ),
) -> None:
    """
    Loads configuration once per process and exposes it to subcommands via ctx.obj.
    Allows per-invocation overrides for base URL and token.
    """
    if version:
        typer.echo(f"matrix-cli { _version_string() }")
        raise typer.Exit(code=0)

    cfg: MatrixCLIConfig = load_config()

    # One-off overrides
    if base_url:
        cfg.registry_url = base_url
    if token:
        cfg.registry_token = token

    # Expose config to subcommands
    ctx.obj = cfg

    # Optional verbose output
    if verbose:
        typer.echo(
            f"[matrix-cli] registry={cfg.registry_url} gateway={cfg.gateway_url} cache_dir={cfg.cache_dir}"
        )


def main() -> None:
    app()


if __name__ == "__main__":
    # When run as a module: python -m matrix_cli
    sys.exit(main())
