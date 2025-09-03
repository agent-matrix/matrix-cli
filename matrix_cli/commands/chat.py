# matrix_cli/commands/chat.py
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional, Tuple

import typer

from ..util.console import error, info, success

app = typer.Typer(
    help="(beta) Interactive chat-like REPL over a single MCP session. Zero JSON required.",
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
    schema = schema or {}
    props = _safe_get(schema, "properties", default={}) or {}
    required = _safe_get(schema, "required", default=[]) or []
    if not isinstance(props, dict):
        props = {}
    if not isinstance(required, (list, tuple)):
        required = []
    return props, required


def _select_default_tool(tools: Iterable[Any]) -> Optional[Any]:
    """Prefer default|main|run|chat; else first."""
    tools_list = list(tools or [])
    if not tools_list:
        return None
    name_map = {}
    for t in tools_list:
        nm = (_safe_get(t, "name", default="") or "").strip()
        if nm:
            name_map[nm.casefold()] = t
    for pref in _PREFERRED_DEFAULT_TOOL_NAMES:
        t = name_map.get(pref)
        if t:
            return t
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


def _kv_merge(dst: Dict[str, Any], kv: Dict[str, str]) -> Dict[str, Any]:
    """Merge key=value pairs with light coercion (bool/int/float)."""
    for k, v in kv.items():
        vl = v.strip().lower()
        if vl in {"true", "false"}:
            dst[k] = (vl == "true")
            continue
        try:
            if "." in vl:
                f = float(vl)
                dst[k] = f
            else:
                i = int(vl)
                dst[k] = i
            continue
        except Exception:
            dst[k] = v
    return dst


def _print_blocks(blocks: Iterable[Dict[str, Any]]) -> None:
    """Pretty-print MCP content blocks with text-first bias."""
    printed = False
    for c in blocks or []:
        t = c.get("type")
        if t == "text":
            typer.echo(c.get("text", ""))
            printed = True
        else:
            typ = c.get("type", "content")
            rep = c.get("repr") or c.get("text") or c.get("value")
            typer.echo(f"- {typ}: {rep}")
            printed = True
    if not printed:
        typer.echo("(no content)")


# --------------------------- future AI compatibility ------------------------ #
# NOTE: This is a minimal placeholder that will be moved to ai.py later.
class AIRouter:
    """
    Future-ready AI router (Ollama, OpenAI/ChatGPT, watsonx.ai, Gemini).
    Current version is a stub to preserve zero-dependency footprint and speed.
    """

    __slots__ = ("backend", "model", "system")

    def __init__(self, backend: str = "none", model: str = "", system: str = "") -> None:
        self.backend = backend  # e.g., "ollama", "openai", "watsonx", "gemini"
        self.model = model
        self.system = system

    def set_backend(self, backend: str, model: str | None = None) -> None:
        self.backend = backend
        if model:
            self.model = model

    def set_system(self, system: str) -> None:
        self.system = system

    def generate(self, prompt: str, history: list[dict[str, str]] | None = None) -> str:
        # Intentionally no network calls. Pure stub for now.
        return (
            "[ai:disabled] No AI backend configured in this beta build. "
            "Future backends: ollama | openai | watsonx | gemini."
        )


# --------------------------------- command --------------------------------- #

@app.command()
def main(
    target: Optional[str] = typer.Argument(
        None,
        help="Alias or catalog name previously installed (if omitted, use --alias or --url).",
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
        30.0,
        "--timeout",
        help="Connect/read timeout (seconds).",
        show_default=True,
    ),
) -> None:
    """
    (beta) Interactive loop that keeps a single MCP session open.

    • Picks a default tool (default|main|run|chat, else first).
    • Maps plain text lines to the tool's primary string input (schema-aware).
    • Slash commands:
/quit             exit
/help             show commands
/tool <name>      switch current tool
/kv k=v ...       set persistent key=value args (bool/int/float coercion)
/clear            clear persistent key=value args
/json {...}       send a raw JSON object (no schema help)
/retry            re-send the last payload
/ai backend[:model]  (future) set AI backend; no network calls today
/system TEXT      (future) set AI system prompt (stored only)

    Performance: one connect; no background threads; minimal allocations.
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
            _jsonify_content_block,
            _to_jsonable,
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

    # ----------------------------- async core ----------------------------- #
    async def _open_session(url_: str) -> Tuple[ClientSession, Any, Any, Any]:
        """Open transport + session; return (session, read_stream, write_stream, tools)."""
        async_ctx = _transport_ctx(url_, timeout=timeout)
        read_stream = write_stream = session = None  # assigned below
        # Use nested context managers manually to allow returning the objects
        acm = async_ctx.__aenter__()
        read_stream, write_stream = await acm  # type: ignore
        session_cm = ClientSession(read_stream, write_stream).__aenter__()
        session = await session_cm  # type: ignore

        init_result = await session.initialize()
        tools_resp = await session.list_tools()
        tools = _safe_get(tools_resp, "tools", default=[]) or []

        # Store the two context managers to close later
        session.__dict__["__aclose_cm"] = (session_cm, async_ctx)  # type: ignore[attr-defined]

        info(f"Connected: {url_}")
        if tools:
            tool_names = ", ".join((_safe_get(t, "name", default="") or "") for t in tools if _safe_get(t, "name", default=""))
            info(f"Tools: {tool_names}")
        return session, read_stream, write_stream, tools

    async def _close_session(session: ClientSession) -> None:
        """Close session and transport cleanly."""
        try:
            cm, transport_cm = session.__dict__.get("__aclose_cm", (None, None))  # type: ignore[attr-defined]
            if cm:
                await cm.__aexit__(None, None, None)  # session
            if transport_cm:
                await transport_cm.__aexit__(None, None, None)  # transport
        except Exception:
            pass

    async def _call(session: ClientSession, tool_name: str, payload: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """Call and normalize response."""
        try:
            resp = await session.call_tool(name=tool_name, arguments=payload)
            content = _safe_get(resp, "content", default=[]) or []
            blocks = []
            for c in content:
                try:
                    blk = _jsonify_content_block(c)
                except Exception:
                    blk = {"type": getattr(c, "type", "content"), "repr": repr(c)}
                blocks.append(blk)
            return True, "ok", {"tool": tool_name, "args": payload, "content": blocks}
        except BaseException as e:
            msg = str(e) or e.__class__.__name__
            return False, msg, {"tool": tool_name, "args": payload, "reason": msg}

    # ----------------------------- REPL state ----------------------------- #
    ai = AIRouter()  # future-ready stub
    kv_args: Dict[str, Any] = {}
    last_payload: Dict[str, Any] | None = None
    current_tool_name: str | None = None
    current_tool_schema: Dict[str, Any] | None = None

    # ------------------------------- session ------------------------------ #
    try:
        session, _rs, _ws, tools = asyncio.run(_open_session(final_url))
    except KeyboardInterrupt:
        typer.echo("Interrupted.", err=True)
        raise typer.Exit(130)
    except BaseException as e:
        error(str(e))
        raise typer.Exit(2)

    # Pick default tool
    tool_obj = _select_default_tool(tools)
    if not tool_obj:
        error("No tools exposed by the server.")
        asyncio.run(_close_session(session))
        raise typer.Exit(2)

    current_tool_name = (_safe_get(tool_obj, "name", default="") or "").strip()
    current_tool_schema = _safe_get(tool_obj, "input_schema", "inputSchema", "schema", default={}) or {}
    default_key = _infer_default_input_key(current_tool_schema)

    typer.echo(f"💬 chatting with {effective_alias or final_url} — tool: {current_tool_name}")
    typer.echo("Type /help for commands. Press Ctrl+C or /quit to exit.")

    # ------------------------------- REPL loop ---------------------------- #
    exit_code = 0
    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                typer.echo("")  # newline
                break

            if not line:
                continue

            if line.startswith("/"):
                # -------- slash commands (local, zero network) -------- #
                parts = line.split()
                cmd = parts[0].lower()

                if cmd in {"/quit", "/exit"}:
                    break

                if cmd == "/help":
                    typer.echo(
                        "Commands:\n"
                        "/quit                  exit\n"
                        "/tool <name>           switch current tool\n"
                        "/kv k=v [k=v...]       set persistent key=value args (coerces bool/int/float)\n"
                        "/clear                 clear persistent key=value args\n"
                        "/json {..}             send raw JSON payload (no schema help)\n"
                        "/retry                 re-send the last payload\n"
                        "/ai backend[:model]    (future) set AI backend; no network calls today\n"
                        "/system TEXT           (future) set AI system prompt"
                    )
                    continue

                if cmd == "/tool":
                    if len(parts) < 2:
                        typer.echo("Usage: /tool <name>")
                        continue
                    want = parts[1].strip().casefold()
                    lookup = {(_safe_get(t, "name", default="") or "").strip().casefold(): t for t in tools}
                    sel = lookup.get(want)
                    if not sel:
                        # list available
                        names = [(_safe_get(t, "name", default="") or "").strip() for t in tools if _safe_get(t, "name", default="")]
                        typer.echo("Available tools:")
                        for n in names:
                            typer.echo(f"  - {n}")
                        continue
                    current_tool_name = (_safe_get(sel, "name", default="") or "").strip()
                    current_tool_schema = _safe_get(sel, "input_schema", "inputSchema", "schema", default={}) or {}
                    default_key = _infer_default_input_key(current_tool_schema)
                    kv_args.clear()
                    typer.echo(f"✓ tool set: {current_tool_name}")
                    continue

                if cmd == "/kv":
                    if len(parts) < 2:
                        typer.echo("Usage: /kv key=value [key=value...]")
                        continue
                    pairs = {}
                    for p in parts[1:]:
                        if "=" not in p:
                            continue
                        k, v = p.split("=", 1)
                        pairs[k.strip()] = v.strip()
                    _kv_merge(kv_args, pairs)
                    typer.echo(f"✓ kv: {json.dumps(kv_args, ensure_ascii=False)}")
                    continue

                if cmd == "/clear":
                    kv_args.clear()
                    typer.echo("✓ kv cleared")
                    continue

                if cmd == "/json":
                    raw = line[len("/json") :].strip()
                    if not raw:
                        typer.echo("Usage: /json { ... }")
                        continue
                    try:
                        payload = json.loads(raw)
                        if not isinstance(payload, dict):
                            typer.echo("Payload must be a JSON object.")
                            continue
                    except Exception as e:
                        typer.echo(f"Invalid JSON: {e}")
                        continue
                    ok, msg, rep = asyncio.run(_call(session, current_tool_name, payload))  # type: ignore[arg-type]
                    if not ok:
                        error(msg)
                        continue
                    last_payload = payload
                    _print_blocks(rep.get("content") or [])
                    continue

                if cmd == "/retry":
                    if not last_payload:
                        typer.echo("Nothing to retry yet.")
                        continue
                    ok, msg, rep = asyncio.run(_call(session, current_tool_name, last_payload))  # type: ignore[arg-type]
                    if not ok:
                        error(msg)
                        continue
                    _print_blocks(rep.get("content") or [])
                    continue

                if cmd == "/ai":
                    # future: ai router; keep local state only
                    if len(parts) < 2:
                        typer.echo(f"ai backend: {ai.backend} model: {ai.model or '(default)'}")
                    else:
                        seg = parts[1].strip()
                        if ":" in seg:
                            be, mo = seg.split(":", 1)
                            ai.set_backend(be, mo)
                        else:
                            ai.set_backend(seg)
                        typer.echo(f"✓ ai backend set: {ai.backend} model: {ai.model or '(default)'}")
                    continue

                if cmd == "/system":
                    sysmsg = line[len("/system") :].strip()
                    ai.set_system(sysmsg)
                    typer.echo("✓ system prompt set (local only)")
                    continue

                typer.echo("Unknown command. Type /help for commands.")
                continue

            # -------- normal user input (map to schema) -------- #
            if not current_tool_name:
                error("No tool selected.")
                exit_code = 2
                break

            payload: Dict[str, Any] = {}

            # Allow raw JSON lines for power users
            if (line.startswith("{") and line.endswith("}")) or (line.startswith("[") and line.endswith("]")):
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        typer.echo("JSON payload must be an object; arrays are not supported here.")
                        continue
                except Exception as e:
                    typer.echo(f"Invalid JSON: {e}")
                    continue
            else:
                # Single-string mapping with optional persistent kv
                dk = default_key
                if dk:
                    payload[dk] = line
                else:
                    typer.echo(
                        "This tool requires structured input. Try sending /json { ... } "
                        "or switch tool with /tool <name>."
                    )
                    continue

                if kv_args:
                    payload.update(kv_args)

            ok, msg, rep = asyncio.run(_call(session, current_tool_name, payload))  # type: ignore[arg-type]
            if not ok:
                error(msg)
                continue

            last_payload = payload
            _print_blocks(rep.get("content") or [])

    except KeyboardInterrupt:
        typer.echo("")  # newline
    finally:
        try:
            asyncio.run(_close_session(session))
        except Exception:
            pass

    if exit_code:
        raise typer.Exit(exit_code)
    success("Goodbye.")
