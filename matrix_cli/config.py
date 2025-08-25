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


def _inject_os_trust_if_possible() -> None:
    """
    Respect env CA first; else try OS trust (truststore); else fall back to certifi.

    This keeps HTTPS verification robust in diverse environments (local, CI, corporate).
    """
    if os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE"):
        return
    try:
        import truststore  # type: ignore

        truststore.inject_into_ssl()
        os.environ.setdefault("PYTHONHTTPSVERIFY", "1")
        return
    except Exception:
        pass
    try:
        import certifi  # type: ignore

        ca = certifi.where()
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
        os.environ.setdefault("SSL_CERT_FILE", ca)
    except Exception:
        pass


def _build_verify() -> VerifyType:
    """
    Produce a 'verify' object suitable for both httpx and requests:
      - If SSL_CERT_FILE/REQUESTS_CA_BUNDLE set: use them.
      - Else try OS trust via stdlib.
      - Else fall back to certifi.
      - Else True (default verification).
    """
    env_ca = os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE")
    if env_ca:
        return env_ca
    try:
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.load_default_certs()
        return ctx
    except Exception:
        pass
    try:
        import certifi  # type: ignore

        return certifi.where()
    except Exception:
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
        return _orig_client_init(self, *args, **kwargs)

    httpx.Client.__init__ = _patched_client_init  # type: ignore[assignment]
    httpx.Client.__matrix_tls_patched__ = True  # type: ignore[attr-defined]

    if hasattr(httpx, "AsyncClient"):
        _orig_async_init = httpx.AsyncClient.__init__  # type: ignore[attr-defined]

        def _patched_async_init(self, *args, **kwargs):  # type: ignore[no-redef]
            if "verify" not in kwargs:
                kwargs["verify"] = verify
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
      - If SSL_CERT_FILE/REQUESTS_CA_BUNDLE set: use them.
      - Else try OS trust via truststore for stdlib/requests.
      - Else fall back to certifi.
    """
    import requests  # type: ignore

    # Ensure our trust bootstrap ran (sets env / truststore if possible)
    _inject_os_trust_if_possible()

    sess = requests.Session()
    env_ca = os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE")
    if env_ca:
        sess.verify = env_ca
        return sess

    try:
        import certifi  # type: ignore

        sess.verify = certifi.where()
    except Exception:
        sess.verify = True  # default behavior

    return sess


def build_httpx_client_forced(timeout: float = 5.0):
    """
    Build an httpx.Client that uses the SAME verify policy as our requests session.
    Useful for utilities like health checks so they share the exact TLS behavior.
    """
    import httpx  # type: ignore

    sess = build_requests_session()
    verify = getattr(sess, "verify", True)
    return httpx.Client(timeout=timeout, verify=verify, trust_env=True)


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
