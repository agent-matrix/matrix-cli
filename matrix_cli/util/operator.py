from __future__ import annotations

import typer

from ..config import Config
from .console import error


def require_operator_token(cfg: Config) -> None:
    """
    Non-destructive local guard.
    Matrix-Hub now protects admin/mutation endpoints (remotes/ingest/install).
    This helper keeps CLI UX clean and prevents accidental destructive calls
    by tokenless users.
    """
    if cfg.token:
        return

    msg = (
        "This action requires an operator token.\n\n"
        "Set it like:\n"
        "  export MATRIX_HUB_TOKEN='...'\n\n"
        "Or put it in:\n"
        "  ~/.config/matrix/cli.toml  (token = '...')"
    )
    error(msg)
    raise typer.Exit(code=2)
