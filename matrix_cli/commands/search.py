# matrix_cli/commands/search.py
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import typer

from ..config import load_config, client_from_config
from ..util.console import info, warn, error

app = typer.Typer(
    help="Search the Hub catalog (includes pending by default; use --certified for certified-only).",
    add_completion=False,
    no_args_is_help=False,
)


# --------------------------------------------------------------------------------------
# Lightweight helpers (no external deps beyond stdlib)
# --------------------------------------------------------------------------------------
def _to_dict(obj: Any) -> Dict[str, Any]:
    """
    Convert Pydantic v2/v1 models or dicts into plain dicts — without importing pydantic.
    """
    if isinstance(obj, dict):
        return obj

    # pydantic v2
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")  # type: ignore[call-arg]
        except Exception:
            try:
                return dump()  # type: ignore[misc]
            except Exception:
                pass

    # pydantic v1
    as_dict = getattr(obj, "dict", None)
    if callable(as_dict):
        try:
            return as_dict()
        except Exception:
            pass

    # last resort: model_dump_json()
    dump_json = getattr(obj, "model_dump_json", None)
    if callable(dump_json):
        try:
            return json.loads(dump_json())  # type: ignore[misc]
        except Exception:
            pass

    return {}


def _to_items(payload: Any) -> List[Dict[str, Any]]:
    """
    Normalize SDK response to a list of dict items:
      - dict → items|results
      - pydantic → dict first, then items|results
      - list → list of dicts
    """
    body = _to_dict(payload)
    if isinstance(body, dict):
        items = body.get("items", body.get("results", []))
        if isinstance(items, list):
            return [it if isinstance(it, dict) else _to_dict(it) for it in items]
        return []
    if isinstance(payload, list):
        return [it if isinstance(it, dict) else _to_dict(it) for it in payload]
    return []


def _looks_like_id(s: str) -> bool:
    """
    Heuristic for fully-qualified entity ids: type:name@version
    """
    return (":" in s) and ("@" in s) and (1 <= len(s) <= 256)


def _is_pending_item(item: Dict[str, Any]) -> bool:
    """
    Best-effort per-item pending detection:
      1) status in {'pending','unverified','draft'}
      2) pending == True
      3) certified == False
    If none of these are present, we treat status as unknown (not marked pending).
    """
    status = str(item.get("status") or "").lower()
    if status in {"pending", "unverified", "draft"}:
        return True
    if "pending" in item:
        try:
            return bool(item["pending"])
        except Exception:
            pass
    if "certified" in item:
        try:
            return not bool(item["certified"])
        except Exception:
            pass
    return False  # unknown → don't mark as pending


def _row_text(
    item: Dict[str, Any],
    *,
    show_status: bool,
) -> str:
    """
    Build the display row. By default, status is NOT shown.
    When show_status=True, append '  (pending)' or '  (certified)'.
    """
    iid = item.get("id") or "?"
    summary = item.get("summary") or ""
    snippet = item.get("snippet") or ""
    suffix = ""
    if show_status:
        suffix = "  (pending)" if _is_pending_item(item) else "  (certified)"
    main = f"{iid:40s}  {summary[:80]}{suffix}"
    if snippet and snippet != summary:
        return f"{main}\n    ↳ {snippet[:120]}"
    return main


def _print_items(
    items: List[Dict[str, Any]],
    *,
    show_status: bool,
) -> int:
    """
    Print rows; return the count tagged as pending (for optional summary).
    """
    if not items:
        print("    (no results)")
        return 0

    pend = 0
    for it in items:
        if _is_pending_item(it):
            pend += 1
        print(_row_text(it, show_status=show_status))
    return pend


def _retry_call(fn, *, retries: int, wait: float):
    """
    Call fn() with minimal retry logic.
    Exactly one operation per search (no extra/fallback calls), unless the caller
    decides to try a local fallback on DNS/connection failure.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception:
            attempt += 1
            if attempt > max(0, retries):
                raise
            time.sleep(max(0.05, float(wait)))


def _is_default_public_hub(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host == "api.matrixhub.io"
    except Exception:
        return False


def _is_dns_or_conn_failure(err: Exception) -> bool:
    """
    Heuristic: detect common DNS/connection failures from requests/urllib3/socket.
    We avoid importing requests; we just scan the exception chain text.
    """
    needles = (
        "temporary failure in name resolution",
        "name or service not known",
        "nodename nor servname provided",
        "failed to establish a new connection",
        "connection refused",
        "connection timed out",
        "max retries exceeded with url",
    )
    seen = set()
    cur: Exception | None = err
    for _ in range(6):
        if cur is None or cur in seen:
            break
        seen.add(cur)
        s = (str(cur) or "").lower()
        if any(n in s for n in needles):
            return True
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return False


def _stable_prioritize(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Presentational re-ordering only (no extra network requests):
    1) mcp_server results first
    2) Then others
    3) Within each group, if score_final is present, sort descending; otherwise keep input order
    """

    def _key(it: Dict[str, Any]) -> Tuple[int, float]:
        tid = str(it.get("id", ""))
        typ = str(it.get("type", "")).lower()
        is_server = (typ == "mcp_server") or tid.startswith("mcp_server:")
        score = float(it.get("score_final") or 0.0)
        return (0 if is_server else 1, -score)

    try:
        # stable sort: Python's sort is stable; sorting once with the combined key keeps original order for ties
        return sorted(items, key=_key)
    except Exception:
        return items  # if anything odd happens, just return as-is


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
@app.command()
def main(
    query: str = typer.Argument(..., help="Search query (or an exact id with --exact)"),
    type: str | None = typer.Option(  # noqa: A002
        "any", "--type", help="Filter by entity type (agent|tool|mcp_server|any)"
    ),
    limit: int = typer.Option(5, "--limit", "-l", help="Max number of results"),
    retries: int = typer.Option(2, "--retries", help="Retry on temporary errors"),
    wait: float = typer.Option(0.5, "--wait", help="Seconds to wait between retries"),
    capabilities: str | None = typer.Option(
        None, "--capabilities", "-c", help="CSV list, e.g. 'rag,sql'"
    ),
    frameworks: str | None = typer.Option(None, "--frameworks", "-f", help="CSV list"),
    providers: str | None = typer.Option(None, "--providers", "-p", help="CSV list"),
    with_snippets: bool = typer.Option(
        False, "--with-snippets", help="Server may return short snippets"
    ),
    mode: str | None = typer.Option(
        None, "--mode", "-m", help="keyword|semantic|hybrid (server default if omitted)"
    ),
    exact: bool = typer.Option(
        False,
        "--exact",
        "-x",
        help="Treat QUERY as an exact id and fetch via entity lookup.",
    ),
    certified: bool = typer.Option(
        False,
        "--certified",
        help="Show certified/registered entities only (exclude pending). "
        "By default, pending are included.",
    ),
    show_status: bool = typer.Option(
        False,
        "--show-status",
        help="Show status (pending/certified) per row and in the summary.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON payload."),
) -> None:
    """
    Ultra-efficient search (one call only):

      • Default: include pending (single request with include_pending=True).
      • --certified: certified-only (exclude pending).
      • --exact (or id-looking query): /entity/{id} lookup (single call).
      • JSON mode is deterministic and strict: prints raw JSON or exits 1 on error.

    Resilient UX, minimal traffic:
      • If the public hub cannot be resolved/reached (e.g., offline dev box),
        we try ONCE against http://localhost:443 with include_pending=True (human mode only).
      • Output presentation prioritizes mcp_server results (no extra queries).
      • If results exist, show a one-line install hint for the top mcp_server item.
    """
    cfg = load_config()
    client = client_from_config(cfg)
    hub_is_public = _is_default_public_hub(cfg.hub_base)

    # Normalize type
    typ = (type or "").strip().lower()
    typ = None if typ in ("", "any") else typ

    # Fast path: treat input as exact id
    if exact or _looks_like_id(query):

        def _entity_call(c):
            return c.entity(query)

        try:
            payload = _retry_call(
                lambda: _entity_call(client), retries=retries, wait=wait
            )
            if json_out:
                typer.echo(json.dumps(_to_dict(payload), indent=2))
                return

            ed = _to_dict(payload)
            print(_row_text(ed, show_status=show_status))
            if show_status:
                pend = 1 if _is_pending_item(ed) else 0
                info(f"1 result ({pend} pending).")
            else:
                info("1 result.")
            return

        except Exception as e:
            # Human mode: if we failed because public hub isn't reachable, try localhost once
            if (not json_out) and hub_is_public and _is_dns_or_conn_failure(e):
                try:
                    from matrix_sdk.client import MatrixClient as _MC

                    local_client = _MC(base_url="http://localhost:443", token=cfg.token)
                    payload = _entity_call(local_client)
                    ed = _to_dict(payload)
                    print(_row_text(ed, show_status=show_status))
                    if show_status:
                        pend = 1 if _is_pending_item(ed) else 0
                        info(f"1 result ({pend} pending).")
                    else:
                        info("1 result.")
                    warn(
                        "(offline?) couldn't reach public hub; used local dev hub at http://localhost:443"
                    )
                    return
                except Exception:
                    pass  # fall through to graceful message

            if json_out:
                error(f"entity lookup failed: {e}")
                raise typer.Exit(1)
            warn(f"entity lookup failed: {e}")
            info("0 results.")
            warn("Tip: try a broader query or check your id format.")
            return

    # Build base search params (single-call branch decisions below)
    params: Dict[str, Any] = {"q": query, "limit": int(limit)}
    if typ is not None:
        params["type"] = typ
    if capabilities:
        params["capabilities"] = capabilities
    if frameworks:
        params["frameworks"] = frameworks
    if providers:
        params["providers"] = providers
    if with_snippets:
        params["with_snippets"] = True
    if mode:
        params["mode"] = mode

    # Default includes pending; --certified excludes it.
    if not certified:
        params["include_pending"] = True

    def _search_call(c):
        return c.search(**params)

    try:
        payload = _retry_call(lambda: _search_call(client), retries=retries, wait=wait)
        if json_out:
            typer.echo(json.dumps(_to_dict(payload), indent=2))
            return

        items = _stable_prioritize(_to_items(payload))
        pending_count = _print_items(items, show_status=show_status)
        if show_status:
            info(f"{len(items)} results ({pending_count} pending).")
        else:
            info(f"{len(items)} results.")

        # UX: if there's a top mcp_server result, show a one-line install hint
        if items:
            top = items[0]
            tid = str(top.get("id") or "")
            typ0 = str(top.get("type") or "").lower()
            if tid.startswith("mcp_server:") or typ0 == "mcp_server":
                # conservative hint (no alias guesses here)
                warn(f"Tip: install with: matrix install {tid}")
        return

    except Exception as e:
        # Human mode fallback (ONE extra call) when public hub is unreachable: try local dev hub
        if (not json_out) and hub_is_public and _is_dns_or_conn_failure(e):
            try:
                from matrix_sdk.client import MatrixClient as _MC

                local_client = _MC(base_url="http://localhost:443", token=cfg.token)
                local_params = dict(params)
                local_params["include_pending"] = (
                    True  # ensure users see something locally
                )
                payload = local_client.search(**local_params)
                items = _stable_prioritize(_to_items(payload))
                pending_count = _print_items(items, show_status=show_status)
                if show_status:
                    info(f"{len(items)} results ({pending_count} pending).")
                else:
                    info(f"{len(items)} results.")
                warn(
                    "(offline?) couldn't reach public hub; used local dev hub at http://localhost:443"
                )

                # UX install hint for local fallback as well
                if items:
                    top = items[0]
                    tid = str(top.get("id") or "")
                    typ0 = str(top.get("type") or "").lower()
                    if tid.startswith("mcp_server:") or typ0 == "mcp_server":
                        warn(f"Tip: install with: matrix install {tid}")
                return
            except Exception:
                # ignore and fall through to graceful message
                pass

        if json_out:
            error(f"search failed: {e}")
            raise typer.Exit(1)
        warn(f"search failed: {e}")
        info("0 results.")
        warn(
            "Tip: try a broader query or run: matrix remotes ingest <remote-name> if your catalog is empty."
        )
        return
