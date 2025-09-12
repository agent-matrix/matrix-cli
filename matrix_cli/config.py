# matrix_cli/config.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import ssl
from typing import Optional, Union

try:
    import tomllib as _toml  # py>=3.11
except ImportError:  # pragma: no cover
    import tomli as _toml  # type: ignore

DEFAULT_HUB = "https://api.matrixhub.io"

# httpx/requests 'verify' accepts: bool | str (CA bundle path) | ssl.SSLContext
VerifyType = Union[bool, str, ssl.SSLContext]


@dataclass(frozen=True)
class Config:
    hub_base: str = DEFAULT_HUB
    token: Optional[str] = None
    home: Path = Path(
        os.getenv("MATRIX_HOME") or (Path.home() / ".matrix")
    ).expanduser()


def _load_toml() -> dict:
    """
    Load optional CLI config from XDG-style path: ~/.config/matrix/cli.toml
    """
    cfg = {}
    path = Path.home() / ".config" / "matrix" / "cli.toml"
    if path.is_file():
        try:
            cfg = _toml.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # Ignore malformed config; fall back to env/defaults
            pass
    return cfg


# --- TLS bootstrap + httpx hardening (idempotent) ----------------------------
_TLS_BOOTSTRAPPED = False


def _truthy(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _clear_env_ca_if_unwanted() -> None:
    """
    Unless MATRIX_RESPECT_ENV_CA=1, scrub SSL_CERT_FILE / REQUESTS_CA_BUNDLE
    so stale paths from other venvs can't break TLS.
    """
    if _truthy("MATRIX_RESPECT_ENV_CA", False):
        return
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        if key in os.environ:
            os.environ.pop(key, None)


def _valid_env_ca_path() -> Optional[str]:
    """
    Return a usable CA bundle path from SSL_CERT_FILE/REQUESTS_CA_BUNDLE
    only if the feature is enabled and the file exists.
    """
    if not _truthy("MATRIX_RESPECT_ENV_CA", False):
        return None
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        p = os.getenv(key)
        if not p:
            continue
        if os.path.isfile(p):
            return p
        # Stale or invalid path -> clean it up so downstream code can recover
        os.environ.pop(key, None)
    return None


def _inject_os_trust_if_possible() -> None:
    """
    Prefer OS trust on macOS/Windows via truststore; avoid mutating env CA vars.
    """
    _clear_env_ca_if_unwanted()

    # If env CA is explicitly respected and valid, leave it alone.
    if _valid_env_ca_path():
        return

    # Try to make stdlib/requests use OS store on macOS/Windows
    try:
        import truststore  # type: ignore

        truststore.inject_into_ssl()
        os.environ.setdefault("PYTHONHTTPSVERIFY", "1")
        return
    except Exception:
        # No truststore available — benign
        pass


def _build_verify() -> VerifyType:
    """
    Produce a 'verify' object suitable for httpx and SDKs:
      - If MATRIX_RESPECT_ENV_CA=1 and env path valid: wrap in SSLContext.
      - Else try OS trust via truststore.SSLContext or stdlib (with injected trust).
      - Else fall back to certifi (wrapped into SSLContext).
      - Else return True (default verification).
    """
    # 1) Respect an explicit, valid env CA (opt-in)
    env_ca = _valid_env_ca_path()
    if env_ca:
        try:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx.load_verify_locations(cafile=env_ca)
            return ctx
        except Exception:
            pass  # fall through

    # 2) Prefer an explicit truststore SSLContext (Apple Keychain/Windows Store)
    try:
        import truststore  # type: ignore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass

    # 3) Use stdlib defaults (truststore.inject_into_ssl may have patched these)
    try:
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.load_default_certs()
        return ctx
    except Exception:
        pass

    # 4) Fall back to certifi (wrap in SSLContext to avoid httpx deprecation warnings)
    try:
        import certifi  # type: ignore

        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.load_verify_locations(cafile=certifi.where())
        return ctx
    except Exception:
        # 5) Last resort
        return True


def _force_httpx_verify(verify: VerifyType) -> None:
    """
    Ensure all httpx Clients (incl. those created inside the SDK) use our verify by default.
    Safe to call multiple times (patch is idempotent).
    """
    try:
        import httpx  # type: ignore
    except Exception:
        return

    if getattr(httpx.Client, "__matrix_tls_patched__", False):  # type: ignore[attr-defined]
        return

    _orig_client_init = httpx.Client.__init__

    def _patched_client_init(self, *args, **kwargs):  # type: ignore[no-redef]
        if "verify" not in kwargs:
            kwargs["verify"] = verify
        # Avoid env proxies/CA surprises unless explicitly requested by the caller
        kwargs.setdefault("trust_env", False)
        return _orig_client_init(self, *args, **kwargs)

    httpx.Client.__init__ = _patched_client_init  # type: ignore[assignment]
    httpx.Client.__matrix_tls_patched__ = True  # type: ignore[attr-defined]

    if hasattr(httpx, "AsyncClient"):
        _orig_async_init = httpx.AsyncClient.__init__  # type: ignore[attr-defined]

        def _patched_async_init(self, *args, **kwargs):  # type: ignore[no-redef]
            if "verify" not in kwargs:
                kwargs["verify"] = verify
            kwargs.setdefault("trust_env", False)
            return _orig_async_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = _patched_async_init  # type: ignore[assignment, attr-defined]


def _bootstrap_tls_once() -> None:
    """
    Run TLS bootstrapping exactly once per process before any HTTP requests.
    """
    global _TLS_BOOTSTRAPPED
    if _TLS_BOOTSTRAPPED:
        return
    _inject_os_trust_if_possible()
    _force_httpx_verify(_build_verify())
    _TLS_BOOTSTRAPPED = True


# -----------------------------------------------------------------------------


# -------- Generic helpers used by HTTP clients (requests/httpx) --------------
def build_requests_session():
    """
    Build a `requests.Session` with best-possible trust:
      - Let truststore-injected stdlib use OS trust when available.
      - Otherwise fall back to certifi path.
      - Ignore shell env CA by default (unless MATRIX_RESPECT_ENV_CA=1).
    """
    import requests  # type: ignore

    # Ensure our trust bootstrap ran (patches stdlib ssl if truststore is present)
    _inject_os_trust_if_possible()

    sess = requests.Session()

    # If respecting env CA and it is valid, requests happily accepts the path
    env_ca = _valid_env_ca_path()
    if env_ca:
        sess.verify = env_ca
        return sess

    # Otherwise, prefer default verification (truststore-injected) or certifi
    try:
        import certifi  # type: ignore

        # Only force certifi when not on mac/win or when explicitly requested
        if not _truthy("MATRIX_PREFER_SYSTEM_TRUST", True):
            sess.verify = certifi.where()
            return sess
    except Exception:
        # Leave default verification
        pass

    # Default: let requests use stdlib SSL (truststore may have injected OS trust)
    # requests' default is verify=True; keep it.
    return sess


def build_httpx_client_forced(timeout: float = 5.0):
    """
    Build an httpx.Client with our hardened verify policy.
    - Pass an SSLContext directly (prevents stale path issues).
    - Disable trust_env to avoid proxies/CA overrides from the shell environment.
    """
    import httpx  # type: ignore

    return httpx.Client(
        timeout=timeout,
        verify=_build_verify(),  # SSLContext | True
        trust_env=False,  # avoid env surprises
        follow_redirects=True,
    )


# -----------------------------------------------------------------------------


def load_config() -> Config:
    """
    Load configuration from env and XDG TOML, then bootstrap TLS defaults
    before returning a Config object used by the CLI/SDK.
    """
    # Initialize TLS/httpx behavior before any HTTP is made (incl. inside SDK).
    _bootstrap_tls_once()

    cfg = _load_toml()
    hub = os.getenv("MATRIX_HUB_BASE") or cfg.get("hub_base") or DEFAULT_HUB
    tok = os.getenv("MATRIX_HUB_TOKEN") or cfg.get("token") or None
    home = Path(
        os.getenv("MATRIX_HOME") or cfg.get("home") or (Path.home() / ".matrix")
    ).expanduser()
    return Config(hub_base=str(hub), token=tok, home=home)


def client_from_config(cfg: Config):
    """
    Create the SDK client. Prefer a requests backend/session if the SDK allows it;
    otherwise fall back — httpx is already patched to use our verify by default.
    """
    from matrix_sdk.client import MatrixClient  # lazy import

    # Preferred: requests backend with our configured session
    try:
        sess = build_requests_session()
        return MatrixClient(
            base_url=cfg.hub_base,
            token=cfg.token,
            transport="requests",  # if supported by the SDK
            session=sess,
        )
    except TypeError:
        # Older/newer SDKs may not accept transport/session. Try passing verify directly:
        try:
            return MatrixClient(
                base_url=cfg.hub_base, token=cfg.token, verify=_build_verify()
            )
        except TypeError:
            # Last resort: default ctor; our httpx patch enforces verify anyway.
            return MatrixClient(base_url=cfg.hub_base, token=cfg.token)


def target_for(id_str: str, alias: str | None, cfg: Config) -> str:
    """
    Compute install target path using SDK policy.
    Ensures MATRIX_HOME is set so the SDK sees the intended home.
    """
    os.environ["MATRIX_HOME"] = str(cfg.home)  # ensure SDK sees the intended home
    from matrix_sdk.policy import default_install_target

    return default_install_target(id_str, alias=alias)
