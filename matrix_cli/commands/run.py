from __future__ import annotations

import typer

from ..util.console import success, error, info

app = typer.Typer(help="Run a server from an alias", add_completion=False, no_args_is_help=False)


@app.command()
def main(
    alias: str,
    port: int | None = typer.Option(None, "--port", "-p", help="Port to run on"),
) -> None:
    """
    Start a component previously installed under an alias.

    On success:
      ✓ prints PID and port
      ✓ prints a click-friendly URL and health endpoint
      ✓ reminds how to tail logs
    """
    from matrix_sdk.alias import AliasStore
    from matrix_sdk import runtime

    info(f"Resolving alias '{alias}'...")
    rec = AliasStore().get(alias)
    if not rec:
        error(f"Alias '{alias}' not found.")
        raise typer.Exit(1)

    target = rec.get("target")
    if not target:
        error("Alias record is corrupt and missing a target path.")
        raise typer.Exit(1)

    try:
        lock = runtime.start(target, alias=alias, port=port)
    except Exception as e:
        error(f"Start failed: {e}")
        raise typer.Exit(1)

    # Prefer a loopback address for clickability even if the process binds to 0.0.0.0 / ::
    host = getattr(lock, "host", None) or "127.0.0.1"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"

    # If the runtime exposes a full URL, use it; otherwise build one.
    base_url = getattr(lock, "url", None) or f"http://{host}:{lock.port}"
    health_url = f"{base_url}/health"

    success(f"Started '{alias}' (PID: {lock.pid}, Port: {lock.port})")

    # New: print a clickable link users can try immediately.
    # Keeping this before the logs hint as requested.
    info(f"Open in browser: {base_url}")
    info(f"Health:          {health_url}")

    # Existing UX hint preserved
    info(f"View logs with: matrix logs {alias} -f")
