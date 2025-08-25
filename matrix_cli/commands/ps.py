# matrix_cli/commands/ps.py
from __future__ import annotations
import json
import os
import time
from pathlib import Path

import typer
from rich.console import Console

from ..util.console import info
from ..util.tables import ps_table

app = typer.Typer(help="List running servers")

DEFAULT_ENDPOINT = "/messages/"  # sensible default for SSE servers
DEFAULT_HOST = "127.0.0.1"  # what `matrix run` binds to for local probing


def _normalize_endpoint(ep: str | None) -> str:
    if not ep:
        return DEFAULT_ENDPOINT
    ep = ep.strip()
    if not ep.startswith("/"):
        ep = "/" + ep
    if not ep.endswith("/"):
        ep = ep + "/"
    return ep


def _endpoint_from_runner_json(target_path: str) -> str:
    """
    Try to read an endpoint from <target>/runner.json. We check common shapes:
      - {"transport":{"type":"sse","endpoint":"/messages/"}}
      - {"sse":{"endpoint":"/messages/"}}
      - {"endpoint":"/messages/"}
      - {"env":{"ENDPOINT":"/messages/"}}
    Fallback to DEFAULT_ENDPOINT if not found.
    """
    try:
        p = Path(target_path).expanduser() / "runner.json"
        if not p.is_file():
            return DEFAULT_ENDPOINT
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return DEFAULT_ENDPOINT

        # transport.endpoint
        tr = data.get("transport")
        if isinstance(tr, dict):
            ep = tr.get("endpoint") or tr.get("path")
            if ep:
                return _normalize_endpoint(str(ep))

        # sse.endpoint
        sse = data.get("sse")
        if isinstance(sse, dict):
            ep = sse.get("endpoint") or sse.get("path")
            if ep:
                return _normalize_endpoint(str(ep))

        # flat endpoint
        ep = data.get("endpoint")
        if ep:
            return _normalize_endpoint(str(ep))

        # env-derived endpoint
        env = data.get("env")
        if isinstance(env, dict):
            ep = env.get("ENDPOINT") or env.get("MCP_SSE_ENDPOINT")
            if ep:
                return _normalize_endpoint(str(ep))
    except Exception:
        pass
    return DEFAULT_ENDPOINT


def _host_for_row(row) -> str:
    """
    Prefer row.host if the runtime exposes it; otherwise use MATRIX_PS_HOST env
    or default to 127.0.0.1 for local probing.
    """
    return getattr(row, "host", None) or os.getenv("MATRIX_PS_HOST") or DEFAULT_HOST


@app.command()
def main(
    plain: bool = typer.Option(
        False,
        "--plain",
        help="Print a script-friendly table: <alias> <pid> <port> <uptime> <url> <target>.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit structured JSON (array of rows).",
    ),
) -> None:
    """
    Default: pretty Rich table.
    --plain: whitespace-delimited rows for shell scripts.
    --json: machine-readable array of objects.

    Columns for --plain:
      <alias> <pid> <port> <uptime> <url> <target>
    """
    if plain and json_out:
        # Be explicit rather than guessing; keep behavior predictable for scripts
        typer.echo("Error: use either --plain or --json (not both).", err=True)
        raise typer.Exit(2)

    from matrix_sdk import runtime

    rows = runtime.status()
    now = time.time()

    # Build normalized row dicts once
    norm_rows = []
    for r in sorted(rows, key=lambda x: x.alias):
        uptime_seconds = max(0, int(now - float(getattr(r, "started_at", 0) or 0)))
        h, rem = divmod(uptime_seconds, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h:02d}:{m:02d}:{s:02d}"

        port = getattr(r, "port", None)
        target = getattr(r, "target", "") or ""
        host = _host_for_row(r)

        if port:
            endpoint = _endpoint_from_runner_json(target)
            url = f"http://{host}:{int(port)}{endpoint}"
        else:
            url = "—"

        norm_rows.append(
            {
                "alias": getattr(r, "alias", ""),
                "pid": int(getattr(r, "pid", 0) or 0),
                "port": int(port) if port else None,
                "uptime": uptime_str,
                "uptime_seconds": uptime_seconds,
                "url": url,
                "target": target,
                "host": host,
            }
        )

    # JSON mode (no extra noise)
    if json_out:
        typer.echo(json.dumps(norm_rows, indent=2, sort_keys=False))
        raise typer.Exit(0)

    # Plain mode (stable column order for scripts)
    if plain:
        for rd in norm_rows:
            # Keep port as '-' when missing to preserve column positions
            port_str = "-" if rd["port"] is None else str(rd["port"])
            # alias pid port uptime url target
            typer.echo(
                f"{rd['alias']} {rd['pid']} {port_str} {rd['uptime']} {rd['url']} {rd['target']}"
            )
        raise typer.Exit(0)

    # Default: pretty table + count line
    table = ps_table()
    for rd in norm_rows:
        table.add_row(
            rd["alias"],
            str(rd["pid"]),
            str(rd["port"] if rd["port"] is not None else "-"),
            rd["uptime"],
            rd["url"],
            rd["target"],
        )

    Console().print(table)
    info(f"{len(norm_rows)} running process(es).")
