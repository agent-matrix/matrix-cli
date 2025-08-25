# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import sys
import types
import pytest
from typer.testing import CliRunner


# -----------------------------------------------------------------------------
# Compatibility shim for Click 7 vs 8+
# Ensures Result.stdout exists even on Click 7 where only .output is present.
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _click_stdout_shim(monkeypatch):
    try:
        from click.testing import Result  # type: ignore

        # If Click < 8, Result may not expose `.stdout`.
        if not hasattr(Result, "stdout"):

            def _get_stdout(self):  # noqa: ANN001
                return self.output

            try:
                # Add a read-only property alias
                Result.stdout = property(_get_stdout)  # type: ignore[attr-defined]
            except Exception:
                # Best-effort only; tests will still fall back to .output
                pass
    except Exception:
        # If Click isn't importable here, just continue
        pass
    yield


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    """
    Create an in-memory fake `matrix_sdk` package so the CLI can run without
    network or filesystem side effects.
    """
    sdk = types.ModuleType("matrix_sdk")
    sdk.__version__ = "0.1.3"

    # ---------------- alias store ---------------- #
    alias_mod = types.ModuleType("matrix_sdk.alias")

    class AliasStore:
        _store: dict[str, dict] = {}

        def __init__(self) -> None:
            pass

        def set(self, name: str, **meta) -> None:
            self._store[name] = dict(meta)

        def get(self, name: str):
            return self._store.get(name)

        def remove(self, name: str) -> bool:
            return self._store.pop(name, None) is not None

        def all(self) -> dict:
            return dict(self._store)

        @classmethod
        def _clear(cls):  # test helper
            cls._store.clear()

    alias_mod.AliasStore = AliasStore

    # ---------------- ids helpers ---------------- #
    ids_mod = types.ModuleType("matrix_sdk.ids")

    def suggest_alias(id_str: str) -> str:
        # example: "mcp_server:hello-sse@1.0.0" -> "hello-sse"
        core = id_str.split(":", 1)[-1]
        core = core.split("@", 1)[0]
        return core.replace("/", "-")

    ids_mod.suggest_alias = suggest_alias

    # ---------------- policy helpers ------------- #
    policy_mod = types.ModuleType("matrix_sdk.policy")

    def default_install_target(id_str: str, alias: str | None = None) -> str:
        return f"/tmp/matrix/{(alias or suggest_alias(id_str))}"

    def default_port() -> int:
        return 7777

    policy_mod.default_install_target = default_install_target
    policy_mod.default_port = default_port

    # ---------------- installer ------------------ #
    installer_mod = types.ModuleType("matrix_sdk.installer")
    installer_mod.build_calls: list[tuple[str, str | None, str | None]] = []

    class LocalInstaller:
        def __init__(self, client) -> None:
            self.client = client

        def build(
            self,
            id: str,
            *,
            target: str | None = None,
            alias: str | None = None,
            timeout: int = 900,
        ):
            installer_mod.build_calls.append((id, target, alias))
            return {"id": id, "target": target, "alias": alias}

        # Optional extra methods to satisfy CLI's call patterns if expanded
        def plan(self, id: str, target: str):
            return {"plan": {"id": id, "target": target}}

    installer_mod.LocalInstaller = LocalInstaller

    # ---------------- client --------------------- #
    client_mod = types.ModuleType("matrix_sdk.client")

    class MatrixError(Exception):
        def __init__(self, status: int, detail: str = "") -> None:
            self.status = status
            self.detail = detail
            super().__init__(f"HTTP {status}: {detail}")

    class MatrixClient:
        def __init__(
            self, base_url: str, token: str | None = None, timeout: float = 15.0
        ) -> None:
            self.base_url = base_url
            self.token = token

        # Search returns one dummy item for simplicity
        def search(self, q: str, **kwargs):
            return {
                "items": [{"id": "mcp_server:test@1.0.0", "summary": "Hello from SDK"}]
            }

        def entity(self, id: str):
            return {"id": id, "name": "demo"}

        def list_remotes(self):
            return ["default"]

        def add_remote(self, url: str, name: str | None = None):
            return {"added": {"url": url, "name": name}}

        def delete_remote(self, name: str):
            return {"deleted": name}

        def trigger_ingest(self, name: str):
            return {"ingest": name}

    client_mod.MatrixClient = MatrixClient
    client_mod.MatrixError = MatrixError

    # ---------------- deep_link ------------------ #
    deep_mod = types.ModuleType("matrix_sdk.deep_link")

    class DeepLink:  # minimal shape for tests
        def __init__(self, id: str, alias: str | None = None) -> None:
            self.id = id
            self.alias = alias

    def parse(url: str) -> DeepLink:
        from urllib.parse import urlsplit, parse_qs, unquote

        u = urlsplit(url)
        qs = parse_qs(u.query)
        raw_id = (qs.get("id") or [None])[0]
        raw_alias = (qs.get("alias") or [None])[0]
        mid = unquote(raw_id) if raw_id else None
        alias = unquote(raw_alias) if raw_alias else None
        if not mid:
            raise ValueError("id required")
        return DeepLink(mid, alias)

    deep_mod.parse = parse
    deep_mod.DeepLink = DeepLink

    # ---------------- runtime -------------------- #
    runtime_mod = types.ModuleType("matrix_sdk.runtime")

    from types import SimpleNamespace

    _state: dict[str, SimpleNamespace] = {}

    def log_path(alias: str) -> str:
        return f"/tmp/matrix/logs/{alias}.log"

    def start(target: str, *, alias: str | None = None, port: int | None = None):
        pid = 12000 + len(_state)
        prt = port or 7777
        lock = SimpleNamespace(
            pid=pid, port=prt, alias=alias or "anon", target=target, started_at=0
        )
        _state[lock.alias] = lock
        return lock

    def stop(alias: str) -> bool:
        return _state.pop(alias, None) is not None

    def status():
        return list(_state.values())

    def tail_logs(alias: str, *, follow: bool = False, n: int = 20):
        if follow:
            # bounded generator for tests
            for i in range(3):
                yield f"{alias} follow line {i}\n"
        else:
            return [f"{alias} L{i}\n" for i in range(min(n, 5))]

    def doctor(alias: str, timeout: int = 5):
        if alias in _state:
            return {"status": "ok", "reason": "200 /health"}
        return {"status": "fail", "reason": "not running"}

    def _reset_runtime():  # test helper
        _state.clear()

    runtime_mod.log_path = log_path
    runtime_mod.start = start
    runtime_mod.stop = stop
    runtime_mod.status = status
    runtime_mod.tail_logs = tail_logs
    runtime_mod.doctor = doctor
    runtime_mod._reset_runtime = _reset_runtime

    # register all submodules into sys.modules
    sys.modules["matrix_sdk"] = sdk
    sys.modules["matrix_sdk.alias"] = alias_mod
    sys.modules["matrix_sdk.ids"] = ids_mod
    sys.modules["matrix_sdk.policy"] = policy_mod
    sys.modules["matrix_sdk.installer"] = installer_mod
    sys.modules["matrix_sdk.client"] = client_mod
    sys.modules["matrix_sdk.deep_link"] = deep_mod
    sys.modules["matrix_sdk.runtime"] = runtime_mod

    try:
        yield {
            "sdk": sdk,
            "alias": alias_mod,
            "ids": ids_mod,
            "policy": policy_mod,
            "installer": installer_mod,
            "client": client_mod,
            "deep_link": deep_mod,
            "runtime": runtime_mod,
        }
    finally:
        # reset shared in-memory state between tests
        AliasStore._clear()
        runtime_mod._reset_runtime()
        installer_mod.build_calls.clear()


@pytest.fixture()
def runner() -> CliRunner:
    # Avoid mix_stderr for Click < 8 compatibility
    return CliRunner()
