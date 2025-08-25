from __future__ import annotations

import json
from pathlib import Path
import typer

from ..util.console import success, error, info

app = typer.Typer(
    help="Run a server from an alias", add_completion=False, no_args_is_help=False
)


# ---- tiny local helpers (no deps, fast) ------------------------------------ #
def _normalize_endpoint(ep: str | None) -> str:
    """Return a clean endpoint path (default '/messages/')."""
    ep = (ep or "").strip()
    if not ep:
        return "/messages/"
    if not ep.startswith("/"):
        ep = "/" + ep
    if not ep.endswith("/"):
        ep = ep + "/"
    return ep


def _endpoint_from_runner_json(target_path: str | None) -> str:
    """
    Try to read an endpoint from <target>/runner.json. We check common shapes:
      - {"transport":{"endpoint":"/messages/"}}
      - {"sse":{"endpoint":"/messages/"}}
      - {"endpoint":"/messages/"}
      - {"env":{"ENDPOINT":"/messages/"}}
    Fallback: '/messages/'.
    """
    if not target_path:
        return "/messages/"
    try:
        p = Path(target_path).expanduser() / "runner.json"
        if not p.is_file():
            return "/messages/"
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return "/messages/"

        # transport.endpoint / transport.path
        tr = data.get("transport")
        if isinstance(tr, dict):
            ep = tr.get("endpoint") or tr.get("path")
            if ep:
                return _normalize_endpoint(str(ep))

        # sse.endpoint / sse.path
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
    return "/messages/"


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
      ✓ (new) suggests MCP probe/call commands using alias or URL
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

    # Clickable links
    info(f"Open in browser: {base_url}")
    info(f"Health:          {health_url}")

    # Existing UX hint
    info(f"View logs with:  matrix logs {alias} -f")

    # ---- NEW: actionable MCP suggestions (no behavior change) -------------- #
    # We infer the endpoint from runner.json or default to /messages/
    endpoint = _endpoint_from_runner_json(target)
    probe_url = f"{base_url.rstrip('/')}{endpoint}"

    # Show quick next steps in both alias and URL forms
    info("—")
    info("Next steps (MCP):")
    info(f"• Probe via alias: matrix mcp probe --alias {alias}")
    info(f"• Or via URL:      matrix mcp probe --url {probe_url}")
    info(f"• Call a tool:     matrix mcp call <tool> --alias {alias} --args '{{}}'")
