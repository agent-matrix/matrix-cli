from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
from typing import Optional

try:
    import tomllib as _toml  # py>=3.11
except ImportError:  # pragma: no cover
    import tomli as _toml  # type: ignore

DEFAULT_HUB = "https://api.matrixhub.io"

@dataclass(frozen=True)
class Config:
    hub_base: str = DEFAULT_HUB
    token: Optional[str] = None
    home: Path = Path(os.getenv("MATRIX_HOME") or (Path.home() / ".matrix")).expanduser()

def _load_toml() -> dict:
    cfg = {}
    path = Path.home() / ".config" / "matrix" / "cli.toml"
    if path.is_file():
        try:
            cfg = _toml.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return cfg

def load_config() -> Config:
    cfg = _load_toml()
    hub = os.getenv("MATRIX_HUB_BASE") or cfg.get("hub_base") or DEFAULT_HUB
    tok = os.getenv("MATRIX_HUB_TOKEN") or cfg.get("token") or None
    home = Path(os.getenv("MATRIX_HOME") or cfg.get("home") or (Path.home() / ".matrix")).expanduser()
    return Config(hub_base=str(hub), token=tok, home=home)

def client_from_config(cfg: Config):
    # Lazy import to keep CLI startup minimal
    from matrix_sdk.client import MatrixClient
    return MatrixClient(base_url=cfg.hub_base, token=cfg.token)

def target_for(id_str: str, alias: str | None, cfg: Config) -> str:
    # Use SDK policy; base path defaults to ~/.matrix/runners (SDK handles that)
    os.environ["MATRIX_HOME"] = str(cfg.home)  # ensure SDK sees the intended home
    from matrix_sdk.policy import default_install_target
    return default_install_target(id_str, alias=alias)