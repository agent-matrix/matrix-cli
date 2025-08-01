from __future__ import annotations

import importlib
import sys
from importlib import metadata
from typing import Optional

import typer

from .config import MatrixCLIConfig, load_config

# Try to import the REPL exit exception so we can exit cleanly
try:  # pragma: no cover - optional dependency handling
    from click_repl.exceptions import ExitReplException  # type: ignore
except Exception:  # pragma: no cover
    ExitReplException = None  # type: ignore

# Create the top-level Typer app
app = typer.Typer(
    name="matrix",
    help="Matrix Hub CLI — search, show, install agents/tools, and manage remotes.",
    add_completion=True,
    no_args_is_help=False,  # allow zero-arg invocation
)


def _register_subapp(module_name: str, name: str) -> None:
    """
    Dynamically import a commands module that is expected to expose `app: Typer`,
    then attach it as a subcommand group under `name`.
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - defensive
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


@app.callback(invoke_without_command=True)
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
        is_eager=True,
    ),
) -> None:
    """
    Loads configuration once per process and exposes it to subcommands via ctx.obj.
    Allows per-invocation overrides for base URL and token.
    If no subcommand is given, hand off to the interactive Matrix Shell UI.
    """
    if version:
        typer.echo(f"matrix-cli {_version_string()}")
        raise typer.Exit(code=0)

    # Load and override config
    cfg: MatrixCLIConfig = load_config()
    if base_url:
        cfg.registry_url = base_url
    if token:
        cfg.registry_token = token

    ctx.obj = cfg

    if verbose:
        typer.echo(
            f"[matrix-cli] registry={cfg.registry_url} "
            f"gateway={cfg.gateway_url} cache_dir={cfg.cache_dir}"
        )

    # If no Typer subcommand was given, invoke the Click-based UI.
    if ctx.invoked_subcommand is None:
        from matrix_cli.ui.cli import main as ui_main

        # Forward any leftover CLI args (e.g., "exit") to the Click UI.
        ui_args = list(ctx.args or [])
        try:
            ui_main(standalone_mode=False, args=ui_args)
        except SystemExit:
            # Normal Click termination
            raise
        except Exception as exc:
            # If the UI raised click-repl's ExitReplException, exit cleanly
            if ExitReplException and isinstance(exc, ExitReplException):
                raise SystemExit(0)
            # Otherwise, re-raise the original error
            raise


def main() -> None:
    app()


if __name__ == "__main__":
    # When run as a module: python -m matrix_cli
    sys.exit(main())
