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
def main() -> None:
    from matrix_sdk import runtime

    rows = runtime.status()
    table = ps_table()
    now = time.time()

    for r in sorted(rows, key=lambda x: x.alias):
        up = int(now - float(r.started_at))
        h, rem = divmod(up, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h:02d}:{m:02d}:{s:02d}"

        port = getattr(r, "port", None)
        target = getattr(r, "target", "")
        host = _host_for_row(r)

        if port:
            endpoint = _endpoint_from_runner_json(target)
            url = f"http://{host}:{int(port)}{endpoint}"
        else:
            url = "—"

        table.add_row(
            r.alias,
            str(r.pid),
            str(port or "-"),
            uptime_str,
            url,  # <-- NEW: URL column content
            target,
        )

    Console().print(table)
    info(f"{len(rows)} running process(es).")
