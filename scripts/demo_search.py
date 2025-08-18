#!/usr/bin/env python3
"""
demo_search.py — Matrix Hub search cookbook (efficient + friendly)

Runs a curated sequence of search examples (simple → advanced) against a Matrix Hub.

Key behavior
- Defaults to include pending results everywhere to maximize matches.
- --certified shows only registered/certified results (filters out pending).
- Optional --show-status adds a tiny " (pending)" / " (certified)" suffix and summary counts.
- JSON mode is deterministic: exactly one call per case, no fallback.
- De-duplicates identical parameter sets across cases (no useless re-queries).
- Tiny retry budget per call to smooth out transient hiccups.

Usage:
  python scripts/demo_search.py
  python scripts/demo_search.py --hub http://localhost:7300
  python scripts/demo_search.py --query "hello" --limit 5 --json
  python scripts/demo_search.py --only "snippets"   # run only cases whose titles match

Environment:
  MATRIX_HUB_BASE   Hub base URL (default: https://api.matrixhub.io)
  MATRIX_HUB_TOKEN  Bearer token (if required by your Hub)

Requires:
  matrix-python-sdk >= 0.1.2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Tuple

# SDK (v0.1.2+)
try:
    from matrix_sdk.client import MatrixClient
except Exception:
    print("This script requires matrix-python-sdk >= 0.1.2", file=sys.stderr)
    raise

# ---------------------------- Helpers: formatting & normalization ---------------------------- #

def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert Pydantic v2/v1 models or dicts into plain dicts (no hard dependency on pydantic)."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")  # pydantic v2 preferred
        except Exception:
            try:
                return dump()
            except Exception:
                pass
    as_dict = getattr(obj, "dict", None)
    if callable(as_dict):
        try:
            return as_dict()          # pydantic v1
        except Exception:
            pass
    dump_json = getattr(obj, "model_dump_json", None)
    if callable(dump_json):
        try:
            return json.loads(dump_json())
        except Exception:
            pass
    return {}


def _items_from(payload: Any) -> List[Dict[str, Any]]:
    """Extract list of items from various payload shapes."""
    body = _to_dict(payload)
    if isinstance(body, dict):
        items = body.get("items", body.get("results", []))
        if isinstance(items, list):
            return [i if isinstance(i, dict) else _to_dict(i) for i in items]
        return []
    if isinstance(payload, list):
        return [i if isinstance(i, dict) else _to_dict(i) for i in payload]
    return []


def _is_pending_item(item: Dict[str, Any], default_pending_ctx: bool = False) -> bool:
    """
    Best-effort pending detection:
      1) status in {'pending','unverified','draft'}
      2) pending == True
      3) certified == False
      4) fallback to context flag (used when we know the search included pending)
    """
    status = str(item.get("status") or "").lower()
    if status in {"pending", "unverified", "draft"}:
        return True
    if "pending" in item:
        try:
            if bool(item["pending"]):
                return True
        except Exception:
            pass
    if "certified" in item:
        try:
            return not bool(item["certified"])
        except Exception:
            pass
    return bool(default_pending_ctx)


def _row_text(
    item: Dict[str, Any],
    *,
    show_status: bool,
    pending_ctx: bool,
) -> str:
    """
    Build a single-line row string. By default, no status labels are shown.
    If show_status=True, append a tiny suffix: '  (pending)' or '  (certified)'.
    """
    iid = item.get("id") or "?"
    summary = item.get("summary") or ""
    snippet = item.get("snippet") or ""
    status_suffix = ""
    if show_status:
        is_pend = _is_pending_item(item, default_pending_ctx=pending_ctx)
        status_suffix = "  (pending)" if is_pend else "  (certified)"
    main = f"{iid:40s}  {summary[:80]}{status_suffix}"
    if snippet and snippet != summary:
        return f"{main}\n    ↳ {snippet[:120]}"
    return main


def _print_case_header(n: int, title: str, params: Dict[str, Any]) -> None:
    pretty = ", ".join(f"{k}={v!r}" for k, v in params.items() if v not in (None, "", False))
    print(f"\n=== {n:02d}) {title}")
    if pretty:
        print(f"    Params: {pretty}")


def _print_results(
    items: List[Dict[str, Any]],
    *,
    pending_ctx: bool = False,
    show_status: bool = False,
) -> int:
    """Print items and return count tagged as pending."""
    if not items:
        print("    (no results)")
        print("→ 0 results.")
        return 0

    pending_count = 0
    for it in items:
        if _is_pending_item(it, default_pending_ctx=pending_ctx):
            pending_count += 1
        print("  - " + _row_text(it, show_status=show_status, pending_ctx=pending_ctx))

    if show_status:
        print(f"→ {len(items)} results ({pending_count} pending).")
    else:
        print(f"→ {len(items)} results.")
    return pending_count


def _search_once(client: MatrixClient, params: Dict[str, Any], *, retries: int, wait: float):
    """One search call with a tiny retry budget to keep network traffic low."""
    attempt = 0
    while True:
        try:
            return client.search(**params)
        except Exception as e:
            attempt += 1
            if attempt > max(0, retries):
                raise
            time.sleep(max(0.05, wait))


def _norm_params(params: Dict[str, Any]) -> str:
    """Canonical hashable string for caching/deduping identical requests."""
    return json.dumps(params, sort_keys=True, separators=(",", ":"))

# ---------------------------- Demo cases ---------------------------- #

def build_cases(query: str, limit: int, *, certified_only: bool) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Curated set of searches from simple to advanced.

    Default behavior: include_pending=True everywhere to maximize useful results.
    If --certified, we omit include_pending so users see only certified/registered results.
    """
    def P(**kw) -> Dict[str, Any]:
        if not certified_only and "include_pending" not in kw:
            kw["include_pending"] = True
        return kw

    cases: List[Tuple[str, Dict[str, Any]]] = [
        ("Simple search", P(q=query, limit=limit)),
        ("Filter by type=mcp_server", P(q=query, type="mcp_server", limit=limit)),
        ("Filter by type=tool", P(q=query, type="tool", limit=limit)),
        ("Mode=keyword", P(q=query, mode="keyword", limit=limit)),
        ("Mode=semantic", P(q=query, mode="semantic", limit=limit)),
        ("Mode=hybrid (server default)", P(q=query, mode="hybrid", limit=limit)),
        ("With snippets", P(q=query, with_snippets=True, limit=limit)),
        ("Capabilities filter", P(q=query, capabilities="rag,sql", limit=limit)),
        ("Frameworks filter", P(q=query, frameworks="langchain,autogen", limit=limit)),
        ("Providers filter", P(q=query, providers="openai,anthropic", limit=limit)),
        ("Combo: type + snippets + hybrid + longer limit",
         P(q=query, type="mcp_server", with_snippets=True, mode="hybrid", limit=max(limit, 10))),
        ("Different query term",
         P(q="vector database", type="tool", capabilities="embedding", limit=limit)),
    ]

    # Keep one explicit pending case in the list only if --certified is set (for comparison)
    if certified_only:
        cases.insert(
            1,
            ("(Compare) Include pending entities", dict(q=query, include_pending=True, limit=limit)),
        )

    return cases

# ---------------------------- Runner ---------------------------- #

def run_cases(
    client: MatrixClient,
    cases: Iterable[Tuple[str, Dict[str, Any]]],
    *,
    json_mode: bool = False,
    retries: int = 1,
    wait: float = 0.4,
    show_status: bool = False,
) -> None:
    """
    Execution policy (per case):
      • Single primary call with small retry budget.
      • JSON mode: deterministic; no fallback.
      • Human mode: no fallback; we print helpful hints instead.
      • Caching: identical parameter sets across cases are resolved once and reused across the run.
    """
    cache: Dict[str, Any] = {}
    n = 0
    for title, params in cases:
        n += 1
        _print_case_header(n, title, params)

        key = _norm_params(params)
        payload = cache.get(key)

        if payload is None:
            try:
                payload = _search_once(client, params, retries=retries, wait=wait)
                cache[key] = payload
            except Exception as e:
                if json_mode:
                    print(json.dumps({"error": f"search failed: {e}"}, indent=2))
                    continue
                print(f"  ! search failed after retries: {e}")
                _print_results([], show_status=show_status)
                print("  tip: if your catalog isn't ingested yet, try: matrix remotes ingest <remote-name>")
                continue
        else:
            if not json_mode:
                print("    (cached)")

        if json_mode:
            print(json.dumps(_to_dict(payload), indent=2))
            continue

        items = _items_from(payload)
        if items:
            _print_results(
                items,
                pending_ctx=bool(params.get("include_pending")),
                show_status=show_status,
            )
        else:
            _print_results([], show_status=show_status)
            if not params.get("include_pending"):
                print("  tip: no certified matches; re-run without --certified to include pending results.")
            else:
                print("  tip: try a broader query or increase --limit.")

# ---------------------------- Main ---------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description="Matrix Hub search cookbook (efficient + friendly)")
    ap.add_argument(
        "--hub",
        default=os.getenv("MATRIX_HUB_BASE", "https://api.matrixhub.io"),
        help="Matrix Hub base URL (default env MATRIX_HUB_BASE or https://api.matrixhub.io)",
    )
    ap.add_argument(
        "--token",
        default=os.getenv("MATRIX_HUB_TOKEN"),
        help="Bearer token (if required by the Hub)",
    )
    ap.add_argument("--query", default="hello", help="Base search query to demonstrate")
    ap.add_argument("--limit", type=int, default=5, help="Default limit for examples")
    ap.add_argument("--json", action="store_true", help="Print raw JSON payloads for each example (no fallback)")
    ap.add_argument(
        "--show-status",
        action="store_true",
        help="Show per-row status '(pending)' / '(certified)' and summary counts",
    )
    ap.add_argument(
        "--certified",
        action="store_true",
        help="Show only certified/registered results (filters out pending).",
    )
    ap.add_argument("--only", default=None, help="Run only cases whose title contains this substring (case-insensitive)")
    ap.add_argument("--retries", type=int, default=1, help="Retries per example on transient errors")
    ap.add_argument("--wait", type=float, default=0.4, help="Sleep between retries (seconds)")
    args = ap.parse_args()

    # Never print the token
    print("Matrix Hub search demo")
    print(f"Hub: {args.hub}")
    print(f"Token: {'<set>' if args.token else '<none>'}")
    print(f"Base query: {args.query!r}, limit={args.limit}")
    if args.certified:
        print("(filter) showing only certified/registered results; pending are excluded.")
    else:
        print("(default) pending results are included; use --certified to filter to registered only.")
    if args.show_status and not args.json:
        print("(status) rows will include a small ' (pending)' / ' (certified)' suffix; summary shows pending counts.")

    client = MatrixClient(base_url=args.hub, token=args.token)

    cases = build_cases(args.query, args.limit, certified_only=args.certified)
    if args.only:
        needle = args.only.lower()
        cases = [(t, p) for (t, p) in cases if needle in t.lower()]

    if not cases:
        print("No cases matched --only filter.")
        return 0

    run_cases(
        client,
        cases,
        json_mode=args.json,
        retries=args.retries,
        wait=args.wait,
        show_status=args.show_status,
    )
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
