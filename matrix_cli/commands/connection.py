# matrix_cli/commands/connection.py
from __future__ import annotations

import json
import typer

from ..config import load_config
from ..health import check_connection

"""
Production-ready `matrix connection` command group.

- `matrix connection` → defaults to `status`
- `matrix connection status --json` → machine-readable
- Exit codes: 0 when healthy, 2 when not
"""

app = typer.Typer(
    name="connection",
    help="Check connectivity and health of the Matrix Hub.",
    no_args_is_help=False,
    add_completion=False,
)


@app.command(
    "status",
    help="Show connection status (HTTP code, latency, and any /health JSON payload).",
)
def status(
    timeout: float = typer.Option(
        5.0, "--timeout", show_default=True, help="HTTP timeout in seconds."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit structured JSON (good for scripts/CI)."
    ),
) -> None:
    cfg = load_config()
    st = check_connection(cfg, timeout=timeout)

    if json_out:
        payload = {
            "ok": st.ok,
            "code": st.code,
            "reason": st.reason,
            "url": st.url,
            "latency_ms": st.latency_ms,
            "details": st.details,
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        raise typer.Exit(code=0 if st.ok else 2)

    icon = "✅" if st.ok else "❌"
    typer.echo(f"{icon} {st.url} — {st.code} {st.reason} ({st.latency_ms} ms)")
    if st.details:
        try:
            typer.echo(json.dumps(st.details, indent=2, sort_keys=True))
        except Exception:
            pass

    raise typer.Exit(code=0 if st.ok else 2)


@app.callback(invoke_without_command=True)
def _default_entry(
    ctx: typer.Context,
    timeout: float = typer.Option(
        5.0, "--timeout", show_default=True, help="HTTP timeout in seconds."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit structured JSON (good for scripts/CI)."
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        status(timeout=timeout, json_out=json_out)
