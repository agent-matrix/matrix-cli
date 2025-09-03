# matrix_cli/commands/run.py
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import typer

from ..util.console import error, info, success

app = typer.Typer(
    help="Run a server from an alias", add_completion=False, no_args_is_help=False
)


# ---- tiny local helpers (no deps, fast) ------------------------------------ #
def _normalize_endpoint(ep: str | None) -> str:
    """Return a clean endpoint path.

    Default selection now prefers '/sse/' for MCP/SSE runners and '/messages/' for
    legacy/unknown. This function only normalizes a *given* endpoint; selection of
    the default happens in `_endpoint_from_runner_json`.
    """
    ep = (ep or "").strip()
    if not ep:
        return "/messages/"
    if not ep.startswith("/"):
        ep = "/" + ep
    if not ep.endswith("/"):
        ep = ep + "/"
    return ep


def _is_mcp_sse_runner(data: dict) -> bool:
    """Heuristically detect an MCP/SSE runner from runner.json content.

    Signals:
      - integration_type == 'MCP' (case-insensitive)
      - request_type == 'SSE' (case-insensitive)
      - presence of an 'sse' block
      - url path ending with '/sse' or '/sse/'
    """
    try:
        it = str(data.get("integration_type", "")).strip().lower()
        rt = str(data.get("request_type", "")).strip().lower()
        if it == "mcp" or rt == "sse":
            return True
        if isinstance(data.get("sse"), dict):
            return True
        url = str(data.get("url", "")).strip()
        if url:
            path = urlparse(url).path.rstrip("/")
            if path.endswith("/sse"):
                return True
    except Exception:
        pass
    return False


def _endpoint_from_runner_json(target_path: str | None) -> str:
    """
    Try to read an endpoint from <target>/runner.json. We check common shapes:
      - {"transport":{"endpoint":"/messages/"}}
      - {"sse":{"endpoint":"/messages/"}}
      - {"endpoint":"/messages/"}
      - {"env":{"ENDPOINT":"/messages/"}}
      - {"url":"http://.../sse"} → prefer '/sse/'

    Fallback:
      - '/sse/' for MCP/SSE runners
      - '/messages/' for others
    """
    default_non_mcp = "/messages/"
    default_mcp = "/sse/"

    if not target_path:
        return default_non_mcp

    try:
        p = Path(target_path).expanduser() / "runner.json"
        if not p.is_file():
            return default_non_mcp
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_non_mcp

        # Explicit transport endpoint
        tr = data.get("transport")
        if isinstance(tr, dict):
            ep = tr.get("endpoint") or tr.get("path")
            if ep:
                return _normalize_endpoint(str(ep))

        # Explicit SSE endpoint
        sse = data.get("sse")
        if isinstance(sse, dict):
            ep = sse.get("endpoint") or sse.get("path")
            if ep:
                return _normalize_endpoint(str(ep))

        # Flat endpoint
        ep = data.get("endpoint")
        if ep:
            return _normalize_endpoint(str(ep))

        # env-derived endpoint
        env = data.get("env")
        if isinstance(env, dict):
            ep = env.get("ENDPOINT") or env.get("MCP_SSE_ENDPOINT")
            if ep:
                return _normalize_endpoint(str(ep))

        # URL-derived preference (when a full URL is present in runner)
        url = data.get("url")
        if isinstance(url, str) and url.strip():
            path = urlparse(url).path.rstrip("/")
            if path.endswith("/sse"):
                return default_mcp

        # Heuristic default based on runner characteristics
        return default_mcp if _is_mcp_sse_runner(data) else default_non_mcp

    except Exception:
        # On any parse failure, lean to legacy default to preserve behavior
        return default_non_mcp


def _compose_probe_url(base_url: str, endpoint: str) -> str:
    """Join base_url and endpoint safely, avoiding '/sse/sse/'.

    If base_url already ends with '/sse' (or '/sse/'), we don't append another
    '/sse/'. In that case we simply return base_url (normalized with trailing '/').
    """
    try:
        b = (base_url or "").strip()
        if not b:
            return endpoint
        if b.rstrip("/").endswith("/sse") and endpoint.rstrip("/").endswith("/sse"):
            return b.rstrip("/") + "/"  # ensure single trailing slash for readability
        return f"{b.rstrip('/')}{endpoint}"
    except Exception:
        return f"{base_url.rstrip('/')}{endpoint}"


# ---- additive: zero-latency quickstart banner helpers ---------------------- #
_PREFERRED_DEFAULT_INPUT_KEYS = ("x-default-input", "query", "prompt", "text", "input", "message")


def _load_runner_json(target_path: str | None) -> dict:
    if not target_path:
        return {}
    try:
        p = Path(target_path).expanduser() / "runner.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _infer_default_input_key_from_schema(schema: dict | None) -> str | None:
    schema = schema or {}
    # 1) explicit
    x = schema.get("x-default-input")
    if isinstance(x, str) and x:
        return x
    props = schema.get("properties") or {}
    req = schema.get("required") or []
    # 2) common keys
    for k in _PREFERRED_DEFAULT_INPUT_KEYS[1:]:
        if k in props:
            return k
    # 3) one required string
    if isinstance(req, list) and len(req) == 1:
        rk = req[0]
        t = (props.get(rk) or {}).get("type") if isinstance(props.get(rk), dict) else None
        if t in (None, "string"):
            return rk
    # 4) one string prop overall
    if isinstance(props, dict):
        sk = [k for k, v in props.items() if isinstance(v, dict) and v.get("type") in (None, "string")]
        if len(sk) == 1:
            return sk[0]
    return None


def _extract_candidate_schemas(data: dict) -> list[dict]:
    """Best-effort: pluck any embedded schema-like dicts from runner.json.
    Keeps this tiny and fast; no recursion beyond a couple obvious spots.
    """
    out: list[dict] = []
    if not isinstance(data, dict):
        return out

    # Direct fields
    for k in ("input_schema", "schema"):
        v = data.get(k)
        if isinstance(v, dict):
            out.append(v)

    # transport/sse blocks
    for sec in ("transport", "sse"):
        v = data.get(sec)
        if isinstance(v, dict):
            for k in ("input_schema", "schema"):
                sv = v.get(k)
                if isinstance(sv, dict):
                    out.append(sv)

    # tools list (if present)
    tools = data.get("tools")
    if isinstance(tools, list):
        for t in tools[:6]:  # cap small for speed
            if isinstance(t, dict):
                for k in ("input_schema", "schema"):
                    sv = t.get(k)
                    if isinstance(sv, dict):
                        out.append(sv)

    return out


def _infer_quickstart_lines(alias: str, target_path: str | None, endpoint: str) -> list[str]:
    data = _load_runner_json(target_path)
    is_mcp = _is_mcp_sse_runner(data) or endpoint.rstrip("/").endswith("/sse")
    if not is_mcp:
        return []  # non-MCP: don't add extra banner

    # Try find any schema hints
    schemas = _extract_candidate_schemas(data)

    # No-input: if any schema has no props/required
    for sch in schemas:
        props = sch.get("properties") or {}
        req = sch.get("required") or []
        if not props and not req:
            return [
                "Next steps:",
                f"• Run it now:      matrix do {alias}",
                f"• See details:     matrix help {alias}",
            ]

    # Single-string: if any schema yields a default input key
    for sch in schemas:
        dk = _infer_default_input_key_from_schema(sch)
        if dk:
            return [
                "Next steps:",
                f"• One-shot:        matrix do {alias} \"Example input\"",
                f"• See arguments:   matrix help {alias}",
            ]

    # Fallback general guidance (complex / multi-tool / no clear schema)
    return [
        "Next steps:",
        f"• See arguments:   matrix help {alias}",
        f"• Guided call:     matrix mcp call <tool> --alias {alias} --wizard",
    ]


@app.command()
def main(
    alias: str,
    port: int | None = typer.Option(None, "--port", "-p", help="Port to run on"),
) -> None:
    """
    Start a component previously installed under an alias.

    On success:
      ✓ prints PID and port (or connector URL)
      ✓ prints a click-friendly URL and health endpoint
      ✓ reminds how to tail logs
      ✓ suggests MCP probe/call commands using alias or URL
    """
    from matrix_sdk import runtime
    from matrix_sdk.alias import AliasStore

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

    # Connector mode: runtime may expose a full URL (e.g., remote SSE)
    connector_url: str | None = getattr(lock, "url", None) or None

    # Build base_url
    if connector_url:
        base_url = connector_url.rstrip("/")
    else:
        if getattr(lock, "port", None) is not None:
            base_url = f"http://{host}:{lock.port}"
        else:
            # Extremely rare, but avoids 'http://127.0.0.1:None'
            base_url = f"http://{host}"

    # Health URL (best-effort)
    health_url = (
        base_url
        if connector_url and base_url.rstrip("/").endswith("/sse")
        else f"{base_url}/health"
    )

    # Success banner (handle missing port for connector)
    port_repr = getattr(lock, "port", None)
    port_str = str(port_repr) if port_repr is not None else "-"
    success(f"Started '{alias}' (PID: {lock.pid}, Port: {port_str})")

    # Clickable links
    info(f"Open in browser: {base_url}")
    info(f"Health:           {health_url}")

    # Existing UX hint
    info(f"View logs with:   matrix logs {alias} -f")

    # ---- Actionable MCP suggestions --------------------------------------- #
    # Prefer /sse for MCP runners. If base_url already endswith /sse, avoid duplicating.
    endpoint = _endpoint_from_runner_json(target)

    # If we're in connector mode and the base_url already carries /sse, don't append
    if connector_url and base_url.rstrip("/").endswith("/sse"):
        probe_url = base_url  # already pointing at SSE
    else:
        # For MCP/SSE, prefer '/sse/' over '/messages/'
        if endpoint == "/messages/":
            # Re-check whether base_url or runner implies MCP/SSE and upgrade endpoint
            try:
                p = Path(target).expanduser() / "runner.json"
                if p.is_file():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if _is_mcp_sse_runner(data):
                        endpoint = "/sse/"
            except Exception:
                pass
        probe_url = _compose_probe_url(base_url, endpoint)

    # Show quick next steps in both alias and URL forms (keep as-is)
    info("—")
    info("Next steps (MCP):")
    info(f"• Probe via alias: matrix mcp probe --alias {alias}")
    info(f"• Or via URL:      matrix mcp probe --url {probe_url}")
    info(f"• Call a tool:     matrix mcp call <tool> --alias {alias} --args '{{}}'")

    # ---- Additive: zero-latency smart quickstart banner ------------------- #
    try:
        lines = _infer_quickstart_lines(alias, target, endpoint)
        if lines:
            info("")
            for ln in lines:
                info(ln)
    except Exception:
        # Never fail the run output on banner heuristics
        pass
