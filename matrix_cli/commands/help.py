# matrix_cli/commands/help.py
from __future__ import annotations

import json
import difflib
from typing import Any, Dict, Iterable, Optional, Tuple

import typer

from ..util.console import error

app = typer.Typer(
    help="Human-friendly usage for MCP servers (schema-aware, one screen).",
    add_completion=False,
    no_args_is_help=False,
)

# ------------------------------- tiny helpers ------------------------------- #

_PREFERRED_DEFAULT_TOOL_NAMES = ("default", "main", "run", "chat")
_PREFERRED_DEFAULT_INPUT_KEYS = ("x-default-input", "query", "prompt", "text", "input", "message")


def _safe_get(obj: Any, *names: str, default: Any = None) -> Any:
    """Safely get first present attribute or key from an SDK object or dict."""
    for n in names:
        try:
            if isinstance(obj, dict) and n in obj:
                return obj[n]
            v = getattr(obj, n, default)
            if v is not default:
                return v
        except Exception:
            pass
    return default


def _schema_props_required(schema: Dict[str, Any] | None) -> Tuple[Dict[str, Any], Iterable[str]]:
    """Return (properties, required) from a JSON schema-like dict."""
    schema = schema or {}
    props = _safe_get(schema, "properties", default={}) or {}
    required = _safe_get(schema, "required", default=[]) or []
    if not isinstance(props, dict):
        props = {}
    if not isinstance(required, (list, tuple)):
        required = []
    return props, required


def _infer_default_input_key(schema: Dict[str, Any] | None) -> Optional[str]:
    """
    Priority:
      1) schema['x-default-input']
      2) first of query|prompt|text|input|message among properties
      3) if exactly one required string → that key
      4) if exactly one string property overall → that key
    """
    schema = schema or {}
    explicit = _safe_get(schema, "x-default-input")
    if isinstance(explicit, str) and explicit:
        return explicit

    props, required = _schema_props_required(schema)

    for k in _PREFERRED_DEFAULT_INPUT_KEYS[1:]:
        if k in props:
            return k

    if isinstance(required, (list, tuple)) and len(required) == 1:
        rk = required[0]
        p = props.get(rk) if isinstance(props, dict) else None
        t = (p or {}).get("type") if isinstance(p, dict) else None
        if t in (None, "string"):
            return rk

    if isinstance(props, dict):
        string_keys = [k for k, v in props.items() if isinstance(v, dict) and v.get("type") in (None, "string")]
        if len(string_keys) == 1:
            return string_keys[0]

    return None


def _select_default_tool(tools: Iterable[Any]) -> Optional[Any]:
    """Prefer default|main|run|chat (ci); else first."""
    tools_list = list(tools or [])
    if not tools_list:
        return None
    name_map = {}
    for t in tools_list:
        nm = (_safe_get(t, "name", default="") or "").strip()
        if nm:
            name_map[nm.casefold()] = t
    for pref in _PREFERRED_DEFAULT_TOOL_NAMES:
        if pref in name_map:
            return name_map[pref]
    return tools_list[0]


def _one_line(s: str | None, max_len: int = 96) -> str:
    """First line trimmed; hard cap length."""
    if not s:
        return ""
    s = s.strip().splitlines()[0]
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _fmt_type(prop: Dict[str, Any] | None) -> str:
    t = (prop or {}).get("type")
    if isinstance(t, list):
        try:
            return "|".join(map(str, t))
        except Exception:
            return "any"
    return str(t) if t else "any"


def _fmt_default(prop: Dict[str, Any] | None) -> str:
    if not isinstance(prop, dict):
        return ""
    if "default" in prop:
        try:
            return f" [default: {json.dumps(prop['default'])}]"
        except Exception:
            return " [default: <unrepr>]"
    return ""


# --------------------------------- command --------------------------------- #

@app.command()
def main(
    target: Optional[str] = typer.Argument(
        None,
        help="Alias or catalog name previously installed (if omitted, use --alias or --url).",
    ),
    tool: Optional[str] = typer.Option(
        None, "--tool", "-t", help="Show detailed usage for a specific tool."
    ),
    alias: Optional[str] = typer.Option(
        None,
        "--alias",
        help="Alias shown by `matrix ps` (port auto-discovered when possible).",
        show_default=False,
    ),
    url: Optional[str] = typer.Option(
        None,
        "--url",
        help="Full SSE/WebSocket endpoint (e.g., http://127.0.0.1:52305/messages/).",
        show_default=False,
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        help="Connect/read timeout (seconds).",
        show_default=True,
    ),
) -> None:
    """
    One-screen usage:

      • Without --tool: list available tools (name + one-line description).
      • With --tool: show arguments (required/optional, types, defaults) and a single 'Try:' line.

    Performance: one connect, one list_tools(), done.
    """
    # Lazy imports for fast startup
    try:
        from ..config import load_config
    except Exception:
        load_config = None  # type: ignore[assignment]

    try:
        from .mcp import (  # type: ignore
            _final_url_from_inputs,
            DEFAULT_ENDPOINT,
        )
        from .mcp import _is_http_like, _is_ws_like  # type: ignore
    except Exception as e:  # pragma: no cover
        error(f"Internal import error: {e}")
        raise typer.Exit(2)

    effective_alias = alias or target

    # Honor MATRIX_HOME like other commands
    matrix_home = None
    if load_config:
        try:
            cfg = load_config()
            matrix_home = str(cfg.home) if cfg and getattr(cfg, "home", None) else None
        except Exception:
            matrix_home = None

    # Compose final URL (no network yet)
    try:
        final_url, _row = _final_url_from_inputs(
            url=url,
            alias=effective_alias,
            port=None,
            endpoint=DEFAULT_ENDPOINT,
            matrix_home=matrix_home,
        )
    except ValueError as e:
        error(str(e))
        raise typer.Exit(2)

    # Choose transport lazily
    try:
        from mcp import ClientSession
        if _is_http_like(final_url):
            from mcp.client.sse import sse_client as _transport_ctx  # type: ignore
        elif _is_ws_like(final_url):
            from mcp.client.websocket import websocket_client as _transport_ctx  # type: ignore
        else:
            error(f"Unsupported URL scheme for MCP: {final_url}")
            raise typer.Exit(2)
    except Exception as e:
        error(f"MCP dependencies missing or unavailable: {e}")
        raise typer.Exit(2)

    import asyncio

    async def _list(url_: str) -> Tuple[bool, str, Dict[str, Any], Iterable[Any]]:
        """Return (ok, message, server_meta, tools_list). One connect, one list."""
        try:
            async with _transport_ctx(url_, timeout=timeout) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    init_result = await session.initialize()
                    tools_resp = await session.list_tools()
                    tools = _safe_get(tools_resp, "tools", default=[]) or []
                    return True, "ok", {"url": url_, "init": init_result}, tools
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            msg = str(e) or e.__class__.__name__
            return False, msg, {"url": url_}, []

    try:
        ok, msg, meta, tools = asyncio.run(_list(final_url))
    except KeyboardInterrupt:
        typer.echo("Interrupted.", err=True)
        raise typer.Exit(130)

    if not ok:
        error(msg)
        raise typer.Exit(2)

    # No --tool ⇒ list tools + hint
    if not tool:
        title = effective_alias or final_url
        typer.echo(f"Available Tools for '{title}':")
        if not tools:
            typer.echo("  (none)")
            raise typer.Exit(0)

        # list name + one-liner description
        names: list[str] = []
        for t in tools:
            name = (_safe_get(t, "name", default="") or "").strip()
            desc = _one_line(_safe_get(t, "description", default="") or "")
            names.append(name)
            if desc:
                typer.echo(f"• {name}: {desc}")
            else:
                typer.echo(f"• {name}")

        # Suggest a concrete follow-up
        hint_name = _safe_get(_select_default_tool(tools) or {}, "name", default=None) or (names[0] if names else "<tool>")
        alias_hint = effective_alias or "<alias>"
        typer.echo("\nTry:")
        typer.echo(f"matrix help {alias_hint} --tool {hint_name}")
        raise typer.Exit(0)

    # With --tool ⇒ detailed usage
    # Locate the tool (case-insensitive)
    lookup = {(_safe_get(t, "name", default="") or "").strip().casefold(): t for t in tools}
    t_obj = lookup.get(tool.strip().casefold()) if tool else None
    if not t_obj:
        # suggestions
        choices = sorted([(_safe_get(t, "name", default="") or "").strip() for t in tools if _safe_get(t, "name", default="")])
        sug = difflib.get_close_matches(tool or "", choices, n=3, cutoff=0.5)
        error(f"Tool '{tool}' not found.")
        if choices:
            typer.echo("Available:", err=True)
            for c in choices:
                typer.echo(f"  - {c}", err=True)
        if sug:
            typer.echo("Did you mean:", err=True)
            for s in sug:
                typer.echo(f"  - {s}", err=True)
        raise typer.Exit(2)

    name = (_safe_get(t_obj, "name", default="") or "").strip()
    desc = _safe_get(t_obj, "description", default="") or ""
    schema = _safe_get(t_obj, "input_schema", "inputSchema", "schema", default={}) or {}

    typer.echo(f"Tool: {name}")
    if desc:
        typer.echo(f"Description: {_one_line(desc, 160)}\n")

    props, required = _schema_props_required(schema)
    if not props and not required:
        typer.echo("Arguments: none (this tool takes no input)")
        # Try line (no-input): simplest path
        alias_hint = effective_alias or "<alias>"
        typer.echo("\nTry:")
        typer.echo(f"matrix do {alias_hint}")
        raise typer.Exit(0)

    typer.echo("Arguments:")
    # stable ordering: required first (in schema order), then optionals (alpha)
    req_list = [k for k in required if k in props]
    opt_list = sorted([k for k in props.keys() if k not in required])

    def _line_for(k: str) -> str:
        pr = props.get(k) or {}
        rq = "required" if k in required else "optional"
        return f"• {k} ({_fmt_type(pr)}, {rq}){_fmt_default(pr)}"

    for k in req_list:
        typer.echo(_line_for(k))
    for k in opt_list:
        typer.echo(_line_for(k))

    # Try line (single-string → do; otherwise wizard)
    alias_hint = effective_alias or "<alias>"
    default_key = _infer_default_input_key(schema)

    typer.echo("\nTry:")
    if default_key:
        # single-string input path
        typer.echo(f'matrix do {alias_hint} "Example input"')
    else:
        typer.echo(f"matrix mcp call {name} --alias {alias_hint} --wizard")

    raise typer.Exit(0)
