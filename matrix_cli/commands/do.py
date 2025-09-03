# matrix_cli/commands/do.py
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional, Tuple

import typer

from ..util.console import error, info, success

app = typer.Typer(
    help="One-shot, zero-JSON call against a running MCP server (alias or URL).",
    add_completion=False,
    no_args_is_help=False,
)

# -------------------------- tiny local primitives -------------------------- #

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
    # Ensure correct shapes
    if not isinstance(props, dict):
        props = {}
    if not isinstance(required, (list, tuple)):
        required = []
    return props, required


def _select_default_tool(tools: Iterable[Any]) -> Optional[Any]:
    """
    Pick a default tool with minimal work:
      1) prefer name in {default, main, run, chat}
      2) else the first tool
    """
    # Snapshot as list (tools is tiny, a few entries)
    tools_list = list(tools or [])
    if not tools_list:
        return None

    name_to_tool = {}
    for t in tools_list:
        nm = (_safe_get(t, "name", default="") or "").strip()
        if nm:
            name_to_tool[nm.casefold()] = t

    for pref in _PREFERRED_DEFAULT_TOOL_NAMES:
        if pref in name_to_tool:
            return name_to_tool[pref]

    return tools_list[0]


def _infer_default_input_key(schema: Dict[str, Any] | None) -> Optional[str]:
    """
    Priority:
      1) schema['x-default-input']
      2) first of query|prompt|text|input|message among properties
      3) if exactly one required string → that key
      4) if exactly one string property overall → that key
    """
    schema = schema or {}
    # 1) explicit
    explicit = _safe_get(schema, "x-default-input")
    if isinstance(explicit, str) and explicit:
        return explicit

    props, required = _schema_props_required(schema)

    # 2) convention
    for k in _PREFERRED_DEFAULT_INPUT_KEYS[1:]:
        if k in props:
            return k

    # 3) single required string
    if isinstance(required, (list, tuple)) and len(required) == 1:
        rk = required[0]
        p = props.get(rk) if isinstance(props, dict) else None
        t = (p or {}).get("type") if isinstance(p, dict) else None
        if t in (None, "string"):
            return rk

    # 4) single string property overall
    if isinstance(props, dict):
        string_keys = [k for k, v in props.items() if isinstance(v, dict) and v.get("type") in (None, "string")]
        if len(string_keys) == 1:
            return string_keys[0]

    return None


def _build_payload_for_text(
    *,
    text_arg: Optional[str],
    schema: Dict[str, Any] | None,
    file_in: Optional[str],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Construct payload for a single-shot call from an optional text string and/or --in path.
    Returns (payload_dict, guidance_error_or_None). If guidance_error is not None, caller
    should print it and exit 2.
    """
    schema = schema or {}
    props, required = _schema_props_required(schema)

    # No inputs expected → empty payload ok.
    if not props and not required:
        return {}, None

    # Discover best key for text input
    default_key = _infer_default_input_key(schema)

    # If --in PATH was provided, prefer common path-ish keys; else map to default key.
    if file_in:
        for pathish in ("path", "file", "filepath", "filename", "input_path"):
            if pathish in props:
                return {pathish: file_in}, None
        # fallback to default input if exists
        if default_key:
            return {default_key: file_in}, None
        # could be multi-input; suggest wizard
        return {}, "Multiple inputs or no clear default input detected. Try:\n  matrix mcp call <tool> --alias <alias> --wizard"

    # Single-string input with provided text
    if text_arg is not None and default_key:
        return {default_key: text_arg}, None

    # If exactly one required key and it's not string → we cannot auto-construct safely
    if isinstance(required, (list, tuple)) and len(required) == 1 and required[0] not in (default_key or ()):
        return {}, "This tool requires structured input. Try:\n  matrix mcp call <tool> --alias <alias> --wizard"

    # If we have a default key but no text, ask once via prompt (no TTY → fail fast)
    if default_key and text_arg is None:
        try:
            entered = input("> ").strip()
            if not entered:
                return {}, "No input provided."
            return {default_key: entered}, None
        except (EOFError, KeyboardInterrupt):
            return {}, "No input provided."

    # Multiple inputs or ambiguous schema → suggest wizard
    return {}, "Multiple inputs or no clear default input detected. Try:\n  matrix mcp call <tool> --alias <alias> --wizard"


def _print_content_blocks(blocks: Iterable[Dict[str, Any]]) -> None:
    """Pretty-print MCP content blocks, text-first."""
    printed = False
    for c in blocks or []:
        t = c.get("type")
        if t == "text":
            typer.echo(c.get("text", ""))
            printed = True
        else:
            # compact line for non-text types
            typ = c.get("type", "content")
            rep = c.get("repr") or c.get("text") or c.get("value")
            typer.echo(f"- {typ}: {rep}")
            printed = True
    if not printed:
        typer.echo("(no content)")


# --------------------------------- command --------------------------------- #

@app.command()
def main(
    target: Optional[str] = typer.Argument(
        None,
        help="Alias or catalog name previously installed (if omitted, use --alias or --url).",
    ),
    text: Optional[str] = typer.Argument(
        None,
        help='Plain text input for single-string tools (e.g., "Tell me about Genova").',
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
    file_in: Optional[str] = typer.Option(
        None,
        "--in",
        help="Path-like input. If the schema has path/file fields, maps there; otherwise uses the default input key.",
        show_default=False,
    ),
    timeout: float = typer.Option(
        10.0,
        "--timeout",
        help="Connect/read timeout (seconds).",
        show_default=True,
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit structured JSON instead of pretty text.",
        show_default=False,
    ),
) -> None:
    """
    One-shot call flow:

      • Resolves URL from --url or --alias (and your running runtime).
      • Lists tools once → picks a sensible default tool.
      • Builds a payload from plain text or --in PATH (no JSON required).
      • Calls the tool and prints the result, then exits.

    Exit codes:
      0 = success
      2 = user error / guidance
      130 = interrupted
    """
    # Lazy imports to keep CLI startup fast
    try:
        from ..config import load_config
    except Exception:
        load_config = None  # type: ignore[assignment]

    try:
        # Reuse existing discovery + URL shaping helpers
        from .mcp import (  # type: ignore
            _final_url_from_inputs,
            DEFAULT_ENDPOINT,
            _to_jsonable,
            _jsonify_content_block,
        )
        from .mcp import _is_http_like, _is_ws_like  # type: ignore
    except Exception as e:  # pragma: no cover
        error(f"Internal import error: {e}")
        raise typer.Exit(2)

    # Resolve alias if user passed a positional 'target'
    effective_alias = alias or target

    # Honor MATRIX_HOME like other commands
    matrix_home = None
    if load_config:
        try:
            cfg = load_config()
            matrix_home = str(cfg.home) if cfg and getattr(cfg, "home", None) else None
        except Exception:
            matrix_home = None

    # Compose final URL
    try:
        final_url, _row = _final_url_from_inputs(
            url=url,
            alias=effective_alias,
            port=None,  # keep minimal; users shouldn't need this in happy path
            endpoint=DEFAULT_ENDPOINT,
            matrix_home=matrix_home,
        )
    except ValueError as e:
        error(str(e))
        raise typer.Exit(2)

    # Lazy import MCP transport only now
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

    # Async interaction kept inline for minimal overhead
    import asyncio

    async def _oneshot(url_: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Returns (ok, message, result_json_like).
        result_json_like includes: url, tool, args, content[] or reason on error.
        """
        try:
            async with _transport_ctx(url_, timeout=timeout) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    init_result = await session.initialize()
                    tools_resp = await session.list_tools()
                    tools = _safe_get(tools_resp, "tools", default=[]) or []
                    if not tools:
                        return False, "No tools exposed by the server.", {"url": url_}

                    tool_obj = _select_default_tool(tools)
                    if not tool_obj:
                        return False, "Could not select a default tool.", {"url": url_}

                    tool_name = _safe_get(tool_obj, "name", default=None)
                    if not tool_name:
                        return False, "Tool has no name.", {"url": url_}

                    schema = _safe_get(tool_obj, "input_schema", "inputSchema", "schema", default={}) or {}
                    payload, guidance = _build_payload_for_text(
                        text_arg=text, schema=schema, file_in=file_in
                    )
                    if guidance:
                        return False, guidance, {"url": url_, "tool": tool_name}

                    # Call once
                    resp = await session.call_tool(name=str(tool_name), arguments=payload)
                    content = _safe_get(resp, "content", default=[]) or []

                    # Normalize content blocks to JSON-safe form
                    blocks = []
                    for c in content:
                        try:
                            # Reuse existing normalization to keep consistent output
                            blk = _jsonify_content_block(c)
                        except Exception:
                            # Last-resort shape
                            blk = {"type": getattr(c, "type", "content"), "repr": repr(c)}
                        blocks.append(blk)

                    result = {
                        "ok": True,
                        "url": url_,
                        "tool": tool_name,
                        "args": payload,
                        "content": blocks,
                        "init": _to_jsonable(init_result),
                    }
                    return True, "ok", result
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # include CancelledError, transport failures
            # The fix is on this line:
            return False, "An error occurred", {"url": url_, "reason": "An error occurred"}

    try:
        ok, msg, result = asyncio.run(_oneshot(final_url))
    except KeyboardInterrupt:
        typer.echo("Interrupted.", err=True)
        raise typer.Exit(130)

    if json_out:
        typer.echo(json.dumps(result, indent=2, sort_keys=True, default=str))
        raise typer.Exit(0 if ok else 2)

    if not ok:
        error(msg)
        # Offer a single next step if it looks like schema complexity
        if "wizard" in (msg.lower() if isinstance(msg, str) else ""):
            info("Hint: use the guided mode:")
            # If we know a tool name, tell them; otherwise generic
            tool_hint = result.get("tool") or "<tool>"
            alias_hint = effective_alias or (target or "<alias>")
            info(f"matrix mcp call {tool_hint} --alias {alias_hint} --wizard")
        raise typer.Exit(2)

    success("✅ Done.")
    blocks = result.get("content") or []
    _print_content_blocks(blocks)
    raise typer.Exit(0)
