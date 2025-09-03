# matrix_cli/commands/mcp.py
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import sys
from dataclasses import asdict as _dc_asdict, is_dataclass as _dc_is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List, Iterable

import typer

from ..config import load_config

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
_logger = logging.getLogger("matrix_cli.mcp")
if (os.getenv("MATRIX_CLI_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on"}:
    if not _logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(
            logging.Formatter("[matrix-cli][mcp] %(levelname)s: %(message)s")
        )
        _logger.addHandler(_h)
    _logger.setLevel(logging.DEBUG)
else:
    # Avoid noisy root logger if user didn't opt into debug
    _logger.addHandler(logging.NullHandler())

# ------------------------------------------------------------------------------
# Typer app
# ------------------------------------------------------------------------------
app = typer.Typer(
    name="mcp",
    help="MCP utilities (probe or call an MCP server over SSE/WebSocket).",
    no_args_is_help=False,
    add_completion=False,
)

DEFAULT_ENDPOINT = "/messages/"
DEFAULT_HOST = "127.0.0.1"  # local runners bind here by default


# ----------------------------- small helpers ----------------------------- #
def _normalize_endpoint(ep: str | None) -> str:
    """Normalize an endpoint to '/path/' form (with a trailing slash)."""
    ep = (ep or "").strip()
    if not ep:
        return DEFAULT_ENDPOINT
    if not ep.startswith("/"):
        ep = "/" + ep
    if not ep.endswith("/"):
        ep = ep + "/"
    return ep


def _is_http_like(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _is_ws_like(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("ws://") or u.startswith("wss://")


def _jsonify_content_block(block: Any) -> Dict[str, Any]:
    """
    Best-effort normalization of MCP content blocks (TextContent, etc.) without importing classes.
    """
    # If it's already a JSON-like dict with a 'type', just sanitize minimally.
    if isinstance(block, dict) and "type" in block:
        out: Dict[str, Any] = {}
        for k, v in block.items():
            try:
                out[str(k)] = (
                    v if isinstance(v, (str, int, float, bool, type(None))) else repr(v)
                )
            except Exception:
                out[str(k)] = "<unrepr>"
        return out

    t = getattr(block, "type", None)
    if t == "text" and hasattr(block, "text"):
        try:
            return {"type": "text", "text": getattr(block, "text", "")}
        except Exception:
            return {"type": "text", "text": "<unrepr>"}
    try:
        return {"type": str(t or type(block).__name__), "repr": repr(block)}
    except Exception:
        return {"type": str(t or type(block).__name__), "repr": "<unrepr>"}


def _to_jsonable(obj: Any, _depth: int = 0) -> Any:
    """
    Convert arbitrary SDK objects (Pydantic v1/v2, dataclasses, misc containers) into
    JSON-serializable primitives. Non-serializable leaves become repr(obj).
    Depth is bounded to keep it safe and fast.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if _depth > 6:
        try:
            return repr(obj)
        except Exception:
            return "<unrepr>"

    # Bytes-like → decode best-effort
    if isinstance(obj, (bytes, bytearray, memoryview)):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return repr(obj)

    # Collections
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_to_jsonable(v, _depth + 1) for v in obj]
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            try:
                sk = str(k)
            except Exception:
                sk = "<key>"
            out[sk] = _to_jsonable(v, _depth + 1)
        return out

    # Dataclass
    try:
        if _dc_is_dataclass(obj):
            return _to_jsonable(_dc_asdict(obj), _depth + 1)
    except Exception:
        pass

    # Pydantic v2
    try:
        md = getattr(obj, "model_dump", None)
        if callable(md):
            try:
                return _to_jsonable(md(mode="json"), _depth + 1)  # v2 preferred
            except Exception:
                return _to_jsonable(md(), _depth + 1)
    except Exception:
        pass

    # Pydantic v1
    try:
        d = getattr(obj, "dict", None)
        if callable(d):
            return _to_jsonable(d(), _depth + 1)
    except Exception:
        pass

    # Pydantic v2 json
    try:
        mdj = getattr(obj, "model_dump_json", None)
        if callable(mdj):
            try:
                return _to_jsonable(json.loads(mdj()), _depth + 1)
            except Exception:
                pass
    except Exception:
        pass

    # Generic object → __dict__ if simple
    try:
        d = getattr(obj, "__dict__", None)
        if isinstance(d, dict) and d is not obj:
            return _to_jsonable(d, _depth + 1)
    except Exception:
        pass

    # Fallback: repr
    try:
        return repr(obj)
    except Exception:
        return "<unrepr>"


# ------- reuse ps logic: read endpoint from runner.json when possible ----- #
def _endpoint_from_runner_json(target_path: str | None) -> str:
    """
    Try to read an endpoint from <target>/runner.json. Check common shapes:
      - {"transport":{"type":"sse","endpoint":"/messages/"}}
      - {"sse":{"endpoint":"/messages/"}}
      - {"endpoint":"/messages/"}
      - {"env":{"ENDPOINT":"/messages/"}}
    Fallback to DEFAULT_ENDPOINT if not found.
    """
    if not target_path:
        return DEFAULT_ENDPOINT
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
    except Exception as e:
        _logger.debug("runner.json parse failed: %s", e)
    return DEFAULT_ENDPOINT


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Accommodate SDKs that return objects or dicts for runtime.status() rows."""
    if isinstance(row, dict):
        return row
    d: Dict[str, Any] = {}
    for key in ("alias", "pid", "port", "started_at", "target", "host"):
        d[key] = getattr(row, key, None)
    return d


def _runtime_rows(matrix_home: str | None) -> List[Dict[str, Any]]:
    """Fetch runtime rows as dicts. Return [] on errors."""
    try:
        if matrix_home:
            os.environ["MATRIX_HOME"] = matrix_home
        from matrix_sdk import runtime  # lazy import
    except Exception as e:
        _logger.debug("runtime import failed: %s", e)
        return []
    try:
        rows = runtime.status() or []
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        _logger.debug("runtime.status failed: %s", e)
        return []


def _load_alias_store_target(alias: str, matrix_home: str | None) -> Optional[str]:
    """
    Try to read the alias -> target mapping, first via SDK AliasStore,
    then fallback to ~/.matrix/aliases.json. Return target path or None.
    """
    # SDK store
    try:
        if matrix_home:
            os.environ["MATRIX_HOME"] = matrix_home
        from matrix_sdk.alias import AliasStore  # type: ignore

        store = AliasStore()
        ent = store.get(alias)
        if isinstance(ent, dict):
            tgt = ent.get("target") or ent.get("path")
            if tgt:
                return str(tgt)
    except Exception as e:
        _logger.debug("AliasStore lookup failed: %s", e)

    # File fallback
    try:
        home = Path(matrix_home) if matrix_home else (Path.home() / ".matrix")
        f = home / "aliases.json"
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                ent = data.get(alias)
                if isinstance(ent, dict):
                    tgt = ent.get("target") or ent.get("path")
                    if tgt:
                        return str(tgt)
    except Exception as e:
        _logger.debug("aliases.json lookup failed: %s", e)
    return None


def _discover_row_for_alias(
    alias: str, *, matrix_home: str | None
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Find a running row for an alias. Tries:
      1) exact match
      2) case-insensitive match
      3) via alias store: map alias -> target, then match any running row with same target
    Returns (row, suggestions). Suggestions are close alias matches from currently running rows.
    """
    rows = _runtime_rows(matrix_home)
    if not rows:
        return None, []

    want = alias
    want_ci = alias.casefold()

    # 1) exact
    for rd in rows:
        a = (rd.get("alias") or "").strip()
        if a == want:
            return rd, []

    # 2) case-insensitive
    for rd in rows:
        a = (rd.get("alias") or "").strip()
        if a.casefold() == want_ci:
            return rd, []

    # 3) alias store target mapping → match by running target
    tgt = _load_alias_store_target(alias, matrix_home)
    if tgt:
        tgt_resolved = str(Path(tgt).expanduser().resolve())
        for rd in rows:
            rtarget = rd.get("target")
            if rtarget:
                try:
                    if str(Path(rtarget).expanduser().resolve()) == tgt_resolved:
                        return rd, []
                except Exception:
                    pass

    # Suggestions
    running_aliases = [rd.get("alias") for rd in rows if rd.get("alias")]
    sugg = difflib.get_close_matches(want, running_aliases, n=3, cutoff=0.5)
    return None, sugg


def _final_url_from_inputs(
    *,
    url: Optional[str],
    alias: Optional[str],
    port: Optional[int],
    endpoint: str,
    matrix_home: str | None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Build the final URL from either a provided URL, or alias (+ optional/auto port).
    If alias is used and endpoint is left at default, try to auto-detect endpoint
    from runner.json. Returns (url, row_info).
    Raises ValueError if it cannot determine a URL (with helpful suggestions).
    """
    if url:
        # User gave full URL; trust it (caller may already normalize /sse or /messages)
        return url, {}

    if alias:
        row, suggestions = _discover_row_for_alias(alias, matrix_home=matrix_home)
        if row is None:
            rows = _runtime_rows(matrix_home)
            running = (
                ", ".join(
                    sorted(
                        {(r.get("alias") or "").strip() for r in rows if r.get("alias")}
                    )
                )
                or "(none)"
            )
            hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            raise ValueError(
                f"Could not auto-discover port for alias '{alias}'. Provide --port or use --url.{hint} "
                f"Running aliases: {running}"
            )

        # port: prefer explicit CLI, else runtime row
        p = port or row.get("port")
        if not p:
            raise ValueError(
                f"Alias '{alias}' is not exposing a port. Provide --port or use --url."
            )

        # endpoint: if user didn't override (left default), try runner.json
        ep = endpoint
        if endpoint == DEFAULT_ENDPOINT:
            ep = _endpoint_from_runner_json(row.get("target"))

        # host from row if present (SDKs may add it), else override env, else default
        host = row.get("host") or os.getenv("MATRIX_PS_HOST") or DEFAULT_HOST
        final = f"http://{host}:{int(p)}{_normalize_endpoint(ep)}"
        return final, row

    raise ValueError("Provide --url OR --alias (optionally with --port).")


# --------------------------- enhanced args helpers -------------------------- #
_PREFERRED_DEFAULT_INPUT_KEYS: Tuple[str, ...] = (
    "x-default-input",
    "query",
    "prompt",
    "text",
    "input",
    "message",
)


def _infer_default_input_key(schema: Dict[str, Any] | None) -> Optional[str]:
    """Infer a sensible default input key from a JSON Schema-like dict."""
    schema = schema or {}
    # explicit hint
    explicit = schema.get("x-default-input")
    if isinstance(explicit, str) and explicit:
        return explicit

    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
    req = schema.get("required") or []

    # conventional keys
    for k in _PREFERRED_DEFAULT_INPUT_KEYS[1:]:
        if k in props:
            return k

    # single required string
    if isinstance(req, (list, tuple)) and len(req) == 1:
        rk = req[0]
        t = (props.get(rk) or {}).get("type") if isinstance(props.get(rk), dict) else None
        if t in (None, "string"):
            return rk

    # single string property overall
    if isinstance(props, dict):
        string_keys = [k for k, v in props.items() if isinstance(v, dict) and v.get("type") in (None, "string")]
        if len(string_keys) == 1:
            return string_keys[0]

    return None


def _parse_kv_pairs(kv_list: Optional[List[str]]) -> Dict[str, Any]:
    """Parse --kv key=value pairs with light coercion (bool/int/float)."""
    out: Dict[str, Any] = {}
    if not kv_list:
        return out
    for pair in kv_list:
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k = k.strip()
        v = v.strip()
        # coerce bool/int/float when obvious
        vl = v.lower()
        if vl in {"true", "false"}:
            out[k] = (vl == "true")
            continue
        try:
            if "." in v:
                out[k] = float(v)
            else:
                out[k] = int(v)
            continue
        except Exception:
            pass
        out[k] = v
    return out


def _lenient_json_parse(s: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Conservative lenient JSON: try single-quote to double-quote replacement only."""
    try:
        return json.loads(s), None
    except Exception:
        pass
    # conservative: replace single quotes with double quotes if it looks like simple JSON
    if s.count("'") >= 2 and '"' not in s:
        try:
            fixed = s.replace("'", '"')
            obj = json.loads(fixed)
            if isinstance(obj, dict):
                return obj, None
        except Exception:
            return None, "Invalid JSON for --args. Try --wizard, --text or --kv."
    return None, "Invalid JSON for --args. Try --wizard, --text or --kv."


def _read_args_json(args_json: Optional[str]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Parse the --args value. Supports:
      • inline JSON
      • @path.json
      • @path.yaml | @path.yml   (if PyYAML installed)
      • @-  (stdin)
    Returns (parsed_dict, error_message_or_None).
    """
    if not args_json:
        return {}, None
    try:
        s = args_json.strip()
        if s.startswith("@"):
            path = s[1:].strip()
            if path == "-":
                content = sys.stdin.read()
                obj = json.loads(content)
            else:
                p = Path(path).expanduser()
                content = p.read_text(encoding="utf-8")
                if p.suffix.lower() in {".yaml", ".yml"}:
                    try:
                        import yaml  # type: ignore
                    except Exception:
                        return {}, (
                            "YAML not available. Install optional extra: `pip install matrix-cli[yaml]`"
                        )
                    obj = yaml.safe_load(content)  # type: ignore
                else:
                    obj = json.loads(content)
        else:
            # strict first
            try:
                obj = json.loads(s)
            except Exception:
                # lenient fallback (very conservative)
                obj, err = _lenient_json_parse(s)
                if err:
                    return {}, err
        if not isinstance(obj, dict):
            return {}, "--args must be a JSON object (e.g. '{}')"
        return obj, None
    except Exception as e:
        return {}, f"Invalid JSON for --args: {e}"


def _flatten_exception(e: BaseException, _depth: int = 0) -> str:
    """
    Make a short, human-friendly error string from ExceptionGroup / nested exceptions.
    """
    try:
        name = getattr(e, "__class__", type(e)).__name__
        msg = str(e)
        # Python 3.11 ExceptionGroup compatible flattening
        eg = getattr(e, "exceptions", None)
        if eg and isinstance(eg, (list, tuple)) and _depth < 3:
            if eg:
                return _flatten_exception(eg[0], _depth + 1)
        # Prefer the innermost cause if present
        cause = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
        if cause and _depth < 3:
            inner = _flatten_exception(cause, _depth + 1)
            return inner or (msg or name)
        return msg or name
    except Exception:
        try:
            return repr(e)
        except Exception:
            return "unhandled error"


# ----------------------------- core async work ---------------------------- #
async def _probe_async(
    url: str,
    call_tool: Optional[str],
    args_json: Optional[str],
    timeout: float,
    *,
    wizard: bool = False,
    text_arg: Optional[str] = None,
    kv_pairs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Connect, initialize, list tools, optionally call a tool, and return a structured report.
    Extended to build call arguments from --wizard / --text / --kv without extra connections.
    """
    # Import the base session first (mcp is required either way)
    try:
        from mcp import ClientSession
    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "reason": f"Missing MCP core: {e}. Try: pip install 'mcp>=1.13.1'",
        }

    # Select transport with lazy import so SSE use doesn't force 'websockets'
    if _is_http_like(url):
        try:
            from mcp.client.sse import sse_client
        except Exception as e:
            return {
                "ok": False,
                "reason": f"SSE transport unavailable: {e}. Try: pip install mcp",
            }
        transport_ctx = sse_client(url, timeout=timeout)

    elif _is_ws_like(url):
        try:
            from mcp.client.websocket import websocket_client
        except ModuleNotFoundError as e:
            missing = getattr(e, "name", "") or "websockets"
            return {
                "ok": False,
                "reason": f"Missing dependency: {missing}. Try: pip install websockets",
            }
        except Exception as e:
            return {"ok": False, "reason": f"WebSocket transport unavailable: {e}"}
        transport_ctx = websocket_client(url, timeout=timeout)

    else:
        return {"ok": False, "reason": f"Unsupported URL scheme for MCP: {url}"}

    # Parse args for an optional call (strict/lenient/file/yaml/stdin)
    call_args, err = _read_args_json(args_json)
    if err:
        return {"ok": False, "reason": err}

    # Connect and interact
    try:
        async with transport_ctx as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_result = await session.initialize()
                tools_resp = await session.list_tools()
                tools = getattr(tools_resp, "tools", [])

                report: Dict[str, Any] = {
                    "ok": True,
                    "url": url,
                    "initialized": True,
                    "init": _to_jsonable(init_result),
                    "tools": [t.name for t in tools],
                    "call": None,
                }

                if call_tool:
                    # Locate tool object (case-sensitive first, then insensitive)
                    tool_obj = None
                    for t in tools:
                        if getattr(t, "name", None) == call_tool:
                            tool_obj = t
                            break
                    if tool_obj is None:
                        for t in tools:
                            if str(getattr(t, "name", "")).strip().casefold() == call_tool.strip().casefold():
                                tool_obj = t
                                break
                    if tool_obj is None:
                        report["ok"] = False
                        report["call"] = {
                            "tool": call_tool,
                            "args": call_args,
                            "error": f"Tool '{call_tool}' not found on server.",
                        }
                        return report

                    # Build arguments if not provided
                    if not call_args and (wizard or text_arg is not None or (kv_pairs and len(kv_pairs) > 0)):
                        schema = getattr(tool_obj, "input_schema", None) or getattr(tool_obj, "inputSchema", None) or {}
                        # Start from kv pairs
                        args_from_kv = _parse_kv_pairs(kv_pairs)
                        built: Dict[str, Any] = {}

                        # Wizard prompts (top-level props only)
                        if wizard:
                            built = _prompt_from_schema(schema)

                        # Map text to default key (without overwriting explicit values)
                        if text_arg is not None:
                            dk = _infer_default_input_key(schema)
                            if dk:
                                built.setdefault(dk, text_arg)
                            else:
                                # Fallback: single property schema
                                props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
                                if len(props) == 1:
                                    only_key = next(iter(props.keys()))
                                    built.setdefault(only_key, text_arg)
                                else:
                                    return {
                                        "ok": False,
                                        "reason": "This tool requires structured input and no default text field is defined.",
                                    }

                        # Merge precedence: wizard > kv (user intent) > file/args_json (already empty here)
                        call_args = {**args_from_kv, **built}

                    try:
                        resp = await session.call_tool(name=call_tool, arguments=call_args)
                        content = getattr(resp, "content", [])
                        report["call"] = {
                            "tool": call_tool,
                            "args": call_args,
                            "content": [_jsonify_content_block(c) for c in content],
                        }
                    except Exception as e:
                        report["ok"] = False
                        report["call"] = {
                            "tool": call_tool,
                            "args": call_args,
                            "error": _flatten_exception(e),
                        }

                return report
    except BaseException as e:
        # Broader than Exception to include CancelledError, etc.
        return {"ok": False, "reason": _flatten_exception(e)}


def _run_probe_and_render(
    final_url: str,
    call: Optional[str],
    args: Optional[str],
    timeout: float,
    json_out: bool,
    *,
    wizard: bool = False,
    text_arg: Optional[str] = None,
    kv_pairs: Optional[List[str]] = None,
) -> None:
    try:
        report = asyncio.run(
            _probe_async(
                final_url,
                call,
                args,
                timeout,
                wizard=wizard,
                text_arg=text_arg,
                kv_pairs=kv_pairs,
            )
        )
    except KeyboardInterrupt:
        typer.echo("Interrupted.", err=True)
        raise typer.Exit(130)

    if json_out:
        safe = _to_jsonable(report)  # ensure robust JSON
        typer.echo(json.dumps(safe, indent=2, sort_keys=True))
        raise typer.Exit(0 if bool(safe.get("ok")) else 2)

    if not report.get("ok"):
        typer.echo(f"❌ {report.get('reason', 'probe failed')}", err=True)
        raise typer.Exit(2)

    # Human output
    typer.echo(f"✅ Connected: {report.get('url')}")
    tools = report.get("tools") or []
    typer.echo(f"Tools: {', '.join(tools) if tools else '(none)'}")

    if report.get("call"):
        call_rep = report["call"]
        if "error" in call_rep:
            typer.echo(f"Call error: {call_rep['error']}", err=True)
            raise typer.Exit(2)
        contents = call_rep.get("content") or []
        if not contents:
            typer.echo("Call returned no content.")
        else:
            typer.echo("Call result:")
            for c in contents:
                if c.get("type") == "text":
                    typer.echo(c.get("text", ""))
                else:
                    typer.echo(f"- {c.get('type')}: {c.get('repr', '')}")

    raise typer.Exit(0)


# ------------------------------ wizard prompt ------------------------------ #
def _prompt_from_schema(schema: Dict[str, Any] | None) -> Dict[str, Any]:
    """Minimal interactive prompt: string/number/integer/boolean/enum.
    Arrays/objects require pasting JSON. Depth limited to top-level properties.
    """
    out: Dict[str, Any] = {}
    schema = schema or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])

    if not isinstance(props, dict):
        return out

    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        typ = (spec.get("type") or "string").lower() if isinstance(spec.get("type"), str) else str(spec.get("type") or "string")
        enum = spec.get("enum") if isinstance(spec.get("enum"), list) else None
        default = spec.get("default") if name not in required else None
        desc = spec.get("description") or ""

        # Build help line
        hint = f"{name} ({'|'.join(typ) if isinstance(typ, list) else typ}"
        if enum:
            try:
                hint += f"; one of {', '.join(map(str, enum))}"
            except Exception:
                pass
        hint += "; required)" if name in required else "; optional)"
        if default is not None:
            try:
                hint += f" [default: {json.dumps(default)}]"
            except Exception:
                hint += " [default: <unrepr>]"
        if desc:
            hint += f"\n    {desc.strip()}"

        while True:
            try:
                raw = input(f"▸ {hint}\n  → ").strip()
            except (EOFError, KeyboardInterrupt):
                raw = ""
            if not raw:
                if name in required and default is None:
                    print("  ✖ required")
                    continue
                if default is not None:
                    out[name] = default
                break

            # enum first
            if enum:
                if raw in map(str, enum):
                    # try to coerce to enum type
                    try:
                        tgt_type = type(enum[0])
                        out[name] = tgt_type(raw)
                    except Exception:
                        out[name] = raw
                    break
                else:
                    print("  ✖ must be one of:", ", ".join(map(str, enum)))
                    continue

            # simple types
            if typ == "boolean":
                out[name] = raw.lower() in {"1", "true", "yes", "y", "on"}
                break
            if typ == "number":
                try:
                    out[name] = float(raw)
                    break
                except Exception:
                    print("  ✖ expected number")
                    continue
            if typ == "integer":
                try:
                    out[name] = int(raw)
                    break
                except Exception:
                    print("  ✖ expected integer")
                    continue
            if typ == "array" or typ == "object":
                try:
                    obj = json.loads(raw)
                    out[name] = obj
                    break
                except Exception as e:
                    print(f"  ✖ invalid JSON: {e}")
                    continue
            # default: string/any
            out[name] = raw
            break

    return out


# --------------------------------- commands -------------------------------- #
@app.command(
    "probe", help="Probe an MCP server, list tools, and optionally call one tool."
)
def probe(
    url: Optional[str] = typer.Option(
        None,
        "--url",
        help="Full SSE/WebSocket endpoint (e.g., http://127.0.0.1:52305/messages/).",
        show_default=False,
    ),
    alias: Optional[str] = typer.Option(
        None,
        "--alias",
        help="Alias shown in `matrix ps` (port auto-discovered when possible).",
        show_default=False,
    ),
    port: Optional[int] = typer.Option(
        None,
        "--port",
        help="Port the alias is listening on (from `matrix ps`).",
        show_default=False,
    ),
    endpoint: str = typer.Option(
        DEFAULT_ENDPOINT,
        "--endpoint",
        help=f"Endpoint path of the MCP SSE/WebSocket server (default: {DEFAULT_ENDPOINT}).",
        show_default=True,
    ),
    call: Optional[str] = typer.Option(
        None,
        "--call",
        help="Tool name to call after initialization (optional).",
        show_default=False,
    ),
    args: Optional[str] = typer.Option(
        None,
        "--args",
        help="JSON object with arguments for --call. Example: '{}' or '@/path/to/args.json' (also @- for stdin, and YAML if available)",
        show_default=False,
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="Connect/read timeout (seconds).", show_default=True
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit structured JSON.", show_default=False
    ),
) -> None:
    """
    Examples:

      • matrix mcp probe --alias hello-sse-server
      • matrix mcp probe --alias hello-sse-server --endpoint /messages/
      • matrix mcp probe --url http://127.0.0.1:52305/messages/
      • matrix mcp probe --url http://127.0.0.1:52305/messages/ --call hello --args '{}'
    """
    # Ensure TLS/bootstrap like the rest of the CLI
    cfg = load_config()
    matrix_home = str(cfg.home) if cfg and getattr(cfg, "home", None) else None
    if matrix_home:
        os.environ["MATRIX_HOME"] = matrix_home

    try:
        final_url, _row = _final_url_from_inputs(
            url=url,
            alias=alias,
            port=port,
            endpoint=endpoint,
            matrix_home=matrix_home,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)

    _run_probe_and_render(final_url, call, args, timeout, json_out)


@app.command(
    "call",
    help="Convenience wrapper: connect and call a tool. Accepts --url or --alias (auto-discover port).",
)
def call(
    tool: str = typer.Argument(..., help="Tool name to call."),
    url: Optional[str] = typer.Option(
        None,
        "--url",
        help="Full SSE/WebSocket endpoint (e.g., http://127.0.0.1:52305/messages/).",
        show_default=False,
    ),
    alias: Optional[str] = typer.Option(
        None,
        "--alias",
        help="Alias shown in `matrix ps` (port auto-discovered when possible).",
        show_default=False,
    ),
    port: Optional[int] = typer.Option(
        None,
        "--port",
        help="Port the alias is listening on (from `matrix ps`).",
        show_default=False,
    ),
    endpoint: str = typer.Option(
        DEFAULT_ENDPOINT,
        "--endpoint",
        help=f"Endpoint path of the MCP SSE/WebSocket server (default: {DEFAULT_ENDPOINT}).",
        show_default=True,
    ),
    args: Optional[str] = typer.Option(
        None,
        "--args",
        help="JSON object with arguments for the tool. Example: '{}' or '@/path/to/args.json' (also @- for stdin, and YAML if available)",
        show_default=False,
    ),
    # --- new additive flags ---
    wizard: bool = typer.Option(
        False,
        "--wizard",
        "-w",
        help="Prompt for inputs from the tool's schema (strings/numbers/bools/enums).",
        show_default=False,
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        help="Plain text mapped to the tool's default input field (schema-aware).",
        show_default=False,
    ),
    kv: List[str] = typer.Option(
        [],
        "--kv",
        help="Additional key=value pairs (repeatable). Coerces bool/int/float when obvious.",
        show_default=False,
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="Connect/read timeout (seconds).", show_default=True
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit structured JSON.", show_default=False
    ),
) -> None:
    """
    Examples:

      • matrix mcp call hello --alias hello-sse-server
      • matrix mcp call hello --url http://127.0.0.1:52305/messages/
      • matrix mcp call hello --alias hello-sse-server --args '{"name":"world"}'
      • matrix mcp call hello --alias hello-sse-server --wizard
      • matrix mcp call chat --alias hello-sse-server --text "Tell me about Genova"
      • matrix mcp call search --alias hello-sse-server --kv q=linux --kv top_k=5
    """
    # Ensure TLS/bootstrap like the rest of the CLI
    cfg = load_config()
    matrix_home = str(cfg.home) if cfg and getattr(cfg, "home", None) else None
    if matrix_home:
        os.environ["MATRIX_HOME"] = matrix_home

    try:
        final_url, _row = _final_url_from_inputs(
            url=url,
            alias=alias,
            port=port,
            endpoint=endpoint,
            matrix_home=matrix_home,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)

    # Single connect path with extended arg building in-proc
    _run_probe_and_render(
        final_url,
        tool,
        args,
        timeout,
        json_out,
        wizard=wizard,
        text_arg=text,
        kv_pairs=kv,
    )
