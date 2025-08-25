# matrix_cli/commands/doctor.py
from __future__ import annotations

import time
import typing as _t
import urllib.error
import urllib.request

import typer

from ..config import load_config
from ..util.console import error, success, warn

app = typer.Typer(
    help="Health check (GET /health) with smart retries and hub preflight"
)


def _get_attr_or_key(obj: _t.Any, name: str, default: _t.Any = None) -> _t.Any:
    """Support both dicts and simple objects (dataclasses)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _http_get(url: str, *, timeout: float = 1.0) -> tuple[int, str]:
    """GET url, return (status_code, response_text). Raise URLError/HTTPError on failure."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - local/known URLs
        code = resp.getcode() or 0
        body = resp.read().decode("utf-8", errors="replace")
        return code, body


def _probe_health(base_url: str, *, tries: int, wait: float) -> tuple[bool, str]:
    """
    Probe /health then / with a small retry budget.
    Returns (ok, used_url_or_reason).
    """
    # Try /health first, then / (some servers don't expose /health)
    paths = ("/health", "/")
    last_err = ""
    # small initial settle to reduce flakiness immediately after start
    time.sleep(0.15)

    for attempt in range(max(1, tries)):
        for p in paths:
            url = base_url.rstrip("/") + p
            try:
                code, _ = _http_get(url, timeout=max(0.2, wait))
                if 200 <= code < 300:
                    return True, url
                last_err = f"HTTP {code} from {url}"
            except urllib.error.HTTPError as he:
                last_err = f"HTTP {he.code} from {url}"
            except urllib.error.URLError as ue:
                reason = getattr(ue, "reason", None)
                last_err = (
                    f"{reason} hitting {url}" if reason else f"URLError hitting {url}"
                )
            except Exception as e:  # pragma: no cover - defensive
                last_err = f"{type(e).__name__}: {e} hitting {url}"
        # linear backoff; keep snappy
        time.sleep(min(1.0, (attempt + 1) * wait))
    return False, last_err or "no response"


def _hub_preflight(*, hub_base: str, timeout: float = 0.6) -> str | None:
    """
    Very fast hub preflight to improve diagnostics.
    Returns a hint string if we used localhost fallback, otherwise None.
    Never fails the command.
    """
    hub = hub_base.rstrip("/")
    try:
        code, _ = _http_get(f"{hub}/health", timeout=timeout)
        if 200 <= code < 300:
            return None  # public hub is reachable
    except Exception:
        pass

    # Try local dev hub quickly
    try:
        code, _ = _http_get("http://localhost:443/health", timeout=0.4)
        if 200 <= code < 300:
            return (
                "(offline?) couldn't reach public hub; "
                "used local dev hub at http://localhost:443"
            )
    except Exception:
        pass

    # silent if both are down; doctor result should focus on the alias server
    return None


@app.command()
def main(
    alias: str = typer.Argument(..., help="Alias of the running server to check"),
    tries: int = typer.Option(8, "--tries", help="Max attempts to probe the server"),
    wait: float = typer.Option(0.25, "--wait", help="Delay (s) between attempts"),
    no_hub_check: bool = typer.Option(
        False,
        "--no-hub-check",
        help="Skip small hub preflight (saves ~0.5s on bad networks).",
    ),
) -> None:
    """
    Check health of a locally running server by alias with minimal, robust retries.
    Success → exit 0, prints `OK - Responded 200 from <url>`.
    Failure → exit 1, prints `FAIL - Status: fail, Reason: <details>`.
    """
    # Optional: quick hub preflight for friendlier diagnostics
    if not no_hub_check:
        cfg = load_config()
        hint = _hub_preflight(hub_base=cfg.hub_base)
        if hint:
            warn(hint)

    # Resolve alias → port (via runtime.status), then probe /health
    try:
        from matrix_sdk import runtime
    except Exception as e:  # pragma: no cover - unexpected environment
        error(f"cannot import runtime module: {e}")
        raise typer.Exit(1)

    try:
        # First, try SDK's own doctor (fast-path). If it returns ok, use it.
        res = runtime.doctor(alias, timeout=max(1, int(wait * 4)))
        if isinstance(res, dict) and str(res.get("status", "")).lower() == "ok":
            # If SDK includes url info, prefer it.
            msg = res.get("reason") or "OK"
            success(f"OK - {msg}")
            return
    except Exception:
        # Ignore, we’ll do our own probing next
        pass

    # Find the running process info to build the URL ourselves
    locks = []
    try:
        locks = runtime.status() or []
    except Exception:
        # If status fails, still let SDK doctor result above be authoritative
        pass

    lock = None
    for item in locks:
        if _get_attr_or_key(item, "alias") == alias:
            lock = item
            break

    if lock is None:
        # Could still be starting up; try again after a very short wait once.
        time.sleep(0.2)
        try:
            locks = runtime.status() or []
            for item in locks:
                if _get_attr_or_key(item, "alias") == alias:
                    lock = item
                    break
        except Exception:
            pass

    if lock is None:
        error(
            f"FAIL - Status: fail, Reason: no running process found for alias '{alias}'"
        )
        raise typer.Exit(1)

    port = _get_attr_or_key(lock, "port")
    if not port:
        error(
            "FAIL - Status: fail, Reason: missing port information "
            "for the running process"
        )
        raise typer.Exit(1)

    base = f"http://127.0.0.1:{int(port)}"
    ok, used = _probe_health(base, tries=max(1, tries), wait=max(0.1, float(wait)))

    if ok:
        success(f"OK - Responded 200 from {used}")
        return

    error(f"FAIL - Status: fail, Reason: {used}")
    raise typer.Exit(1)
