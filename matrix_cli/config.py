from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Python 3.11+ has tomllib in stdlib; fall back to tomli if needed.
try:
    import tomllib as _toml  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    import tomli as _toml  # type: ignore


DEFAULT_CONFIG_PATH = Path(os.path.expanduser("~/.matrix/config.toml"))
DEFAULT_REGISTRY_URL = "http://localhost:7300"
DEFAULT_GATEWAY_URL = "http://localhost:7200"
DEFAULT_CACHE_DIR = Path(os.path.expanduser("~/.cache/matrix"))
DEFAULT_CACHE_TTL = 4 * 60 * 60  # 4 hours


@dataclass
class MatrixCLIConfig:
    # Registry (Matrix Hub)
    registry_url: str = DEFAULT_REGISTRY_URL
    registry_token: Optional[str] = None
    extra_catalogs: List[str] = field(default_factory=list)

    # MCP-Gateway
    gateway_url: str = DEFAULT_GATEWAY_URL
    gateway_token: Optional[str] = None

    # Local cache
    cache_dir: Path = DEFAULT_CACHE_DIR
    cache_ttl: int = DEFAULT_CACHE_TTL

    # Raw path used (for debugging/diagnostics)
    config_path: Path = DEFAULT_CONFIG_PATH


def _read_toml(cfg_path: Path) -> dict:
    if not cfg_path.exists():
        return {}
    try:
        return _toml.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        # Corrupt or unreadable file — ignore but keep going with env/defaults
        return {}


def _from_env() -> dict:
    """
    Collect environment overrides into the same shape as our TOML.
    """
    env = {}

    # Registry
    reg_url = os.getenv("MATRIX_BASE_URL")
    reg_tok = os.getenv("MATRIX_TOKEN")
    extra = os.getenv("MATRIX_EXTRA_CATALOGS")  # CSV of URLs
    if any([reg_url, reg_tok, extra]):
        env["registry"] = {}
        if reg_url:
            env["registry"]["base_url"] = reg_url
        if reg_tok:
            env["registry"]["token"] = reg_tok
        if extra:
            env["registry"]["extra_catalogs"] = [x.strip() for x in extra.split(",") if x.strip()]

    # Gateway
    gw_url = os.getenv("MCP_GATEWAY_URL")
    gw_tok = os.getenv("MCP_GATEWAY_TOKEN")
    if any([gw_url, gw_tok]):
        env["gateway"] = {}
        if gw_url:
            env["gateway"]["base_url"] = gw_url
        if gw_tok:
            env["gateway"]["token"] = gw_tok

    # Cache
    cache_dir = os.getenv("MATRIX_CACHE_DIR")
    cache_ttl = os.getenv("MATRIX_CACHE_TTL")
    if any([cache_dir, cache_ttl]):
        env["cache"] = {}
        if cache_dir:
            env["cache"]["dir"] = cache_dir
        if cache_ttl:
            try:
                env["cache"]["ttl_seconds"] = int(cache_ttl)
            except ValueError:
                # ignore invalid env, keep defaults
                pass

    return env


def _merge(base: dict, override: dict) -> dict:
    """
    Shallow merge for simple nested dicts (registry/gateway/cache).
    """
    out = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            nv = dict(out[k])
            nv.update(v)
            out[k] = nv
        else:
            out[k] = v
    return out


def load_config() -> MatrixCLIConfig:
    """
    Load configuration from TOML + env with well-defined precedence and defaults.
    """
    # Allow overriding the config path
    cfg_path = Path(os.getenv("MATRIX_CONFIG", str(DEFAULT_CONFIG_PATH))).expanduser()

    toml_obj = _read_toml(cfg_path)
    env_obj = _from_env()
    merged = _merge(toml_obj, env_obj)

    # Registry
    reg = merged.get("registry", {}) or {}
    registry_url = str(reg.get("base_url") or DEFAULT_REGISTRY_URL)
    registry_token = reg.get("token") or None
    extra_catalogs = list(reg.get("extra_catalogs") or [])

    # Gateway
    gw = merged.get("gateway", {}) or {}
    gateway_url = str(gw.get("base_url") or DEFAULT_GATEWAY_URL)
    gateway_token = gw.get("token") or None

    # Cache
    cache = merged.get("cache", {}) or {}
    cache_dir_raw = cache.get("dir") or str(DEFAULT_CACHE_DIR)
    cache_dir = Path(str(cache_dir_raw)).expanduser()
    cache_ttl = int(cache.get("ttl_seconds") or DEFAULT_CACHE_TTL)

    # XDG override for cache directory if MATRIX_CACHE_DIR not set and config missing
    if "MATRIX_CACHE_DIR" not in os.environ and "dir" not in cache:
        xdg_cache_home = os.getenv("XDG_CACHE_HOME")
        if xdg_cache_home:
            cache_dir = Path(xdg_cache_home).expanduser() / "matrix"

    return MatrixCLIConfig(
        registry_url=registry_url,
        registry_token=registry_token,
        extra_catalogs=extra_catalogs,
        gateway_url=gateway_url,
        gateway_token=gateway_token,
        cache_dir=cache_dir,
        cache_ttl=cache_ttl,
        config_path=cfg_path,
    )
