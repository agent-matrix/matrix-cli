# matrix_cli/health.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

import httpx

"""
Connection health utilities for Matrix CLI (production-safe).

- Non-throwing API: network errors become a falsey status you can render.
- Works with both legacy MatrixCLIConfig (registry_url) and newer Config (hub_base).
- Prefers the hardened httpx client from matrix_cli.config (build_httpx_client_forced),
  which reuses your global TLS policy (truststore/certifi/env CA) and avoids CERTIFICATE_VERIFY_FAILED.
- Also sets trust_env=True so REQUESTS_CA_BUNDLE / SSL_CERT_FILE are honored.
"""

# Try to import the modern TLS-aware helpers; fall back gracefully.
try:
    from .config import load_config, build_httpx_client_forced  # type: ignore
except Exception:  # pragma: no cover
    load_config = None  # type: ignore[assignment]
    build_httpx_client_forced = None  # type: ignore[assignment]

DEFAULT_TIMEOUT: float = 5.0
DEFAULT_BASE_URL: str = "https://api.matrixhub.io"


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    code: int
    reason: str
    url: str
    latency_ms: int
    details: Optional[Dict[str, Any]] = None


def _base_url_from_config(cfg: Any) -> str:
    for attr in ("hub_base", "registry_url", "base_url"):
        v = getattr(cfg, attr, None)
        if v:
            return str(v).rstrip("/")
    return DEFAULT_BASE_URL


def _verify_kwarg_from_config(cfg: Any) -> Dict[str, Any]:
    ca = getattr(cfg, "ca_bundle", None)
    if ca:
        try:
            return {"verify": str(ca)}
        except Exception:
            return {}
    return {}


def check_connection(
    cfg: Optional[Any] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> ConnectionStatus:
    """
    GET <base>/health and return a structured status. Never raises.
    """
    if cfg is None:
        try:
            if load_config is not None:
                cfg = load_config()
            else:
                cfg = object()
        except Exception:
            cfg = object()

    base = _base_url_from_config(cfg)
    url = f"{base}/health"

    t0 = time.perf_counter()
    try:
        # Prefer the hardened client wired to your TLS policy (truststore/certifi/env CA).
        if build_httpx_client_forced is not None:
            client = build_httpx_client_forced(timeout=timeout)  # type: ignore[misc]
        else:
            verify_kw = _verify_kwarg_from_config(cfg)
            client = httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                trust_env=True,
                **verify_kw,
            )

        with client:
            resp = client.get(url)

        latency = int((time.perf_counter() - t0) * 1000)

        ok = resp.status_code == 200
        reason = resp.reason_phrase or ""

        details: Optional[Dict[str, Any]] = None
        try:
            js = resp.json()
            if isinstance(js, dict):
                details = js
                status_field = js.get("status") or js.get("state") or ""
                if isinstance(status_field, str):
                    ok = ok and (status_field.lower() in {"ok", "healthy", "alive"})
        except Exception:
            pass

        return ConnectionStatus(
            ok=ok,
            code=resp.status_code,
            reason=reason,
            url=url,
            latency_ms=latency,
            details=details,
        )
    except httpx.HTTPError as e:
        latency = int((time.perf_counter() - t0) * 1000)
        return ConnectionStatus(
            ok=False,
            code=0,
            reason=str(e),
            url=url,
            latency_ms=latency,
            details=None,
        )
