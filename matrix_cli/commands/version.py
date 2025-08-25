from __future__ import annotations

import json
import sys
import typer

__all__ = ["app"]

app = typer.Typer(
    help="Show CLI and SDK versions",
    add_completion=False,
    no_args_is_help=False,
)

CLI_DIST = "matrix-cli"
SDK_DIST = "matrix-python-sdk"


def _dist_version(dist_name: str) -> str:
    """
    Return the installed distribution version for `dist_name`, or a readable
    placeholder if not installed/unknown.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover
        # Defensive fallback for Python < 3.8, though project requires >3.11
        return "unknown"

    try:
        return version(dist_name)
    except PackageNotFoundError:
        return "not installed"
    except Exception:
        # Catch any other metadata-related errors
        return "unknown"


@app.command(
    name="main", help="Show CLI and SDK versions"
)  # Use explicit name to avoid conflicts
def main(
    json_: bool = typer.Option(
        False, "--json", "-j", help="Output machine-readable JSON."
    ),
    short: bool = typer.Option(
        False,
        "--short",
        "-s",
        help="Print only the CLI version.",
    ),
) -> None:
    """
    Print versions using distribution metadata first to avoid costly imports.
    """
    # Get CLI version: Prefer metadata, fall back to lazy __version__ if needed.
    cli_ver = _dist_version(CLI_DIST)
    if cli_ver in ("unknown", "not installed"):
        # Check if the package is already in memory to avoid import cost
        if pkg := sys.modules.get("matrix_cli"):
            cli_ver = getattr(pkg, "__version__", cli_ver)

    if short:
        print(cli_ver)
        return

    # Get SDK version: Prefer metadata to avoid importing the full SDK.
    sdk_ver = _dist_version(SDK_DIST)
    if sdk_ver in ("unknown", "not installed"):
        if mod := sys.modules.get("matrix_sdk"):
            sdk_ver = getattr(mod, "__version__", sdk_ver)

    if json_:
        output = {"matrix-cli": cli_ver, "matrix-python-sdk": sdk_ver}
        print(json.dumps(output, separators=(",", ":")))
        return

    # Default human-readable output
    print(f"matrix-cli: {cli_ver}")
    print(f"matrix-python-sdk: {sdk_ver}")
