#!/usr/bin/env python3
# examples/search_via_cli.py

import os
import json
import shutil
import subprocess
from typing import Any, Dict, List, Tuple


def _matrix_cmd() -> List[str]:
    """
    Prefer the 'matrix' CLI if available; otherwise fall back to 'python -m matrix_cli'.
    """
    exe = shutil.which("matrix")
    if exe:
        return [exe]
    # Fallback: run the package as a module
    return [os.environ.get("PYTHON", "python"), "-m", "matrix_cli"]


def _to_mapping(obj: Any) -> Dict[str, Any]:
    """Best-effort normalize an item into a plain dict."""
    if isinstance(obj, dict):
        return obj
    # Try pydantic-like objects, just in case payload passes them through
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            pass
    d = getattr(obj, "dict", None)
    if callable(d):
        try:
            return d()
        except Exception:
            pass
    return {}


def _items_and_total(payload: Any) -> Tuple[List[Dict[str, Any]], Any]:
    """Return (items, total) from a typical search payload."""
    if isinstance(payload, dict):
        return list(payload.get("items", [])), payload.get("total")
    seq = getattr(payload, "items", []) or []
    items = [_to_mapping(it) for it in seq]
    total = getattr(payload, "total", None)
    return items, total


def pretty_print(query: str, res: Any) -> None:
    items, total = _items_and_total(res)
    print(f"\n=== Query: {query!r}  (total={total}) ===")
    if not items:
        print("(no items)")
        return

    for it in items:
        score = it.get("score_final")
        try:
            score_str = f"{float(score):.3f}" if score is not None else "n/a"
        except Exception:
            score_str = str(score)

        print(
            f"- {it.get('id')}  "
            f"[{it.get('type')}]  "
            f"{it.get('name')} v{it.get('version')}  "
            f"score={score_str}"
        )
        if it.get("manifest_url"):
            print(f"  manifest: {it.get('manifest_url')}")
        if it.get("install_url"):
            print(f"  install : {it.get('install_url')}")
        if it.get("snippet"):
            print(f"  snippet : {it.get('snippet')}")


def run_cli_search(query: str) -> Dict[str, Any]:
    """
    Invoke `matrix search` with JSON output and return the parsed payload.
    Mirrors the original SDK call:
      - type=any
      - mode=hybrid
      - limit=5
      - with_snippets=True
      - include_pending=True (default behavior of the CLI unless --certified)
    """
    cmd = (
        _matrix_cmd()
        + [
            "search",
            query,
            "--type",
            "any",
            "--mode",
            "hybrid",
            "--limit",
            "5",
            "--with-snippets",
            "--json",
        ]
    )

    # Inherit environment so MATRIX_HUB_BASE / MATRIX_HUB_TOKEN still work.
    env = os.environ.copy()

    try:
        p = subprocess.run(
            cmd,
            env=env,
            check=False,              # we'll handle non-zero ourselves
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise SystemExit(
            "ERROR: Could not find the 'matrix' CLI. Install it (pip install matrix-cli) "
            "or ensure it's on your PATH."
        )

    if p.returncode != 0:
        # JSON mode prints errors to stderr and exits 1.
        err = (p.stderr or "").strip()
        if not err:
            err = "unknown error"
        raise SystemExit(f"Search failed for {query!r}: {err}")

    try:
        payload = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON from matrix CLI for {query!r}: {e}")

    return payload


def do_search(query: str) -> None:
    payload = run_cli_search(query)
    pretty_print(query, payload)


def main():
    # Same three example queries as the original script
    for q in ("hello", "hello-sse-server", "mcp_server:hello-sse-server@0.1.0"):
        try:
            do_search(q)
        except SystemExit as e:
            # Keep going across queries, mirroring the original "log & continue" UX
            print(str(e))


if __name__ == "__main__":
    main()
