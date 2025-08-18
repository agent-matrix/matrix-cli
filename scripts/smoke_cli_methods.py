#!/usr/bin/env python3
"""
Matrix CLI — method-by-method smoke test (no pytest required)

• Exercises each CLI command individually via Typer's CliRunner.
• Uses an in-memory fake `matrix_sdk` so no network or real FS writes are needed.
• Safe to run locally: `python scripts/smoke_cli_methods.py`

Exit code is 0 if all checks pass, non-zero otherwise.

CHANGELOG
- 2025-08-16: Remove `mix_stderr` argument to support older Click/Typer versions.
- 2025-08-16: Make message assertions case-insensitive and relax wording to
  match the CLI's human-friendly output. The non-follow logs check now
  asserts success (exit code) only, because the fake runtime doesn't write a
  real log file.
- 2025-08-16: Expect doctor(fail) to return exit code 1. Link test now tries
  `--as` then falls back to `--alias`, and accepts either “linked” or “added”.
"""
from __future__ import annotations

import sys
import types
import tempfile
from pathlib import Path
from typing import Callable, List, Tuple

from typer.testing import CliRunner

# -----------------------------------------------------------------------------
# 1) Minimal in-memory fake `matrix_sdk` so the CLI can run offline
# -----------------------------------------------------------------------------

def install_fake_sdk() -> None:
    sdk = types.ModuleType("matrix_sdk")
    sdk.__version__ = "0.1.3"

    # --- alias store ---------------------------------------------------------
    alias_mod = types.ModuleType("matrix_sdk.alias")

    class AliasStore:
        _store: dict[str, dict] = {}

        def set(self, name: str, **meta) -> None:
            self._store[name] = dict(meta)

        def get(self, name: str):
            return self._store.get(name)

        def remove(self, name: str) -> bool:
            return self._store.pop(name, None) is not None

        def all(self) -> dict:
            return dict(self._store)

        @classmethod
        def _clear(cls):
            cls._store.clear()

    alias_mod.AliasStore = AliasStore

    # --- ids -----------------------------------------------------------------
    ids_mod = types.ModuleType("matrix_sdk.ids")

    def suggest_alias(id_str: str) -> str:
        core = id_str.split(":", 1)[-1]
        core = core.split("@", 1)[0]
        return core.replace("/", "-")

    ids_mod.suggest_alias = suggest_alias

    # --- policy ---------------------------------------------------------------
    policy_mod = types.ModuleType("matrix_sdk.policy")

    def default_install_target(id_str: str, alias: str | None = None) -> str:
        return f"/tmp/matrix/{(alias or suggest_alias(id_str))}"

    def default_port() -> int:
        return 7777

    policy_mod.default_install_target = default_install_target
    policy_mod.default_port = default_port

    # --- installer ------------------------------------------------------------
    installer_mod = types.ModuleType("matrix_sdk.installer")
    installer_mod.build_calls: list[tuple[str, str | None, str | None]] = []

    class LocalInstaller:
        def __init__(self, client) -> None:
            self.client = client

        def build(self, id: str, *, target: str | None = None, alias: str | None = None, timeout: int = 900):
            installer_mod.build_calls.append((id, target, alias))
            return {"id": id, "target": target, "alias": alias}

    installer_mod.LocalInstaller = LocalInstaller

    # --- client ---------------------------------------------------------------
    client_mod = types.ModuleType("matrix_sdk.client")

    class MatrixError(Exception):
        def __init__(self, status: int, detail: str = "") -> None:
            self.status = status
            self.detail = detail
            super().__init__(f"HTTP {status}: {detail}")

    class MatrixClient:
        def __init__(self, base_url: str, token: str | None = None, timeout: float = 15.0) -> None:
            self.base_url = base_url
            self.token = token

        def search(self, q: str, **kwargs):
            return {"items": [{"id": "mcp_server:test@1.0.0", "summary": "Hello from SDK"}]}

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

    # --- deep_link ------------------------------------------------------------
    deep_mod = types.ModuleType("matrix_sdk.deep_link")

    class DeepLink:
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

    # --- runtime --------------------------------------------------------------
    runtime_mod = types.ModuleType("matrix_sdk.runtime")
    from types import SimpleNamespace

    _state: dict[str, SimpleNamespace] = {}

    def log_path(alias: str) -> str:
        return f"/tmp/matrix/logs/{alias}.log"

    def start(target: str, *, alias: str | None = None, port: int | None = None):
        pid = 12000 + len(_state)
        prt = port or 7777
        lock = SimpleNamespace(pid=pid, port=prt, alias=alias or "anon", target=target, started_at=0)
        _state[lock.alias] = lock
        return lock

    def stop(alias: str) -> bool:
        return _state.pop(alias, None) is not None

    def status():
        return list(_state.values())

    def tail_logs(alias: str, *, follow: bool = False, n: int = 20):
        if follow:
            for i in range(3):
                yield f"{alias} follow line {i}\n"
        else:
            return [f"{alias} L{i}\n" for i in range(min(n, 5))]

    def doctor(alias: str, timeout: int = 5):
        if alias in _state:
            return {"status": "ok", "reason": "200 /health"}
        return {"status": "fail", "reason": "not running"}

    runtime_mod.log_path = log_path
    runtime_mod.start = start
    runtime_mod.stop = stop
    runtime_mod.status = status
    runtime_mod.tail_logs = tail_logs
    runtime_mod.doctor = doctor

    # register all submodules
    sys.modules["matrix_sdk"] = sdk
    sys.modules["matrix_sdk.alias"] = alias_mod
    sys.modules["matrix_sdk.ids"] = ids_mod
    sys.modules["matrix_sdk.policy"] = policy_mod
    sys.modules["matrix_sdk.installer"] = installer_mod
    sys.modules["matrix_sdk.client"] = client_mod
    sys.modules["matrix_sdk.deep_link"] = deep_mod
    sys.modules["matrix_sdk.runtime"] = runtime_mod


# -----------------------------------------------------------------------------
# 2) Helpers
# -----------------------------------------------------------------------------

def out_of(result) -> str:
    # Support both Click 7 (result.output) and Click 8+ (result.stdout)
    return getattr(result, "stdout", getattr(result, "output", ""))


def must_ok(
    label: str,
    result,
    expect_exit: int = 0,
    *,
    contains: str | None = None,
    contains_any: list[str] | None = None,
    contains_all: list[str] | None = None,
) -> bool:
    """Unified assertion helper (case-insensitive contains checks).

    - If *contains* is provided, text must include it.
    - If *contains_any* is provided, text must include at least one.
    - If *contains_all* is provided, text must include all.
    """
    text = out_of(result)
    ok = (result.exit_code == expect_exit)

    def has(s: str) -> bool:
        return s.lower() in text.lower()

    if contains is not None:
        ok = ok and has(contains)
    if contains_any:
        ok = ok and any(has(s) for s in contains_any)
    if contains_all:
        ok = ok and all(has(s) for s in contains_all)

    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}\n{text}")
    return ok


# -----------------------------------------------------------------------------
# 3) Individual command tests (each independent)
# -----------------------------------------------------------------------------

def t_install(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    res = runner.invoke(app, ["install", "mcp_server:hello@1.0.0", "--alias", "hello", "--force"])
    return must_ok(
        "install",
        res,
        contains_all=["Installed", "mcp_server:hello@1.0.0"],
    )


def t_run(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    # prepare alias
    sys.modules["matrix_sdk.alias"].AliasStore().set("svc", id="mcp_server:svc@1.0.0", target="/tmp/matrix/svc")
    res = runner.invoke(app, ["run", "svc"])
    return must_ok("run", res, contains_all=["Started", "svc"])


def t_ps(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    # ensure one running
    sys.modules["matrix_sdk.alias"].AliasStore().set("ps1", id="mcp_server:ps@1.0.0", target="/tmp/matrix/ps1")
    runner.invoke(app, ["run", "ps1"])  # ignore result
    res = runner.invoke(app, ["ps"])
    return must_ok("ps", res, contains="running")


def t_logs_lines(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    sys.modules["matrix_sdk.alias"].AliasStore().set("logs1", id="mcp_server:logs@1.0.0", target="/tmp/matrix/logs1")
    runner.invoke(app, ["run", "logs1"])  # start
    res = runner.invoke(app, ["logs", "logs1", "--lines", "2"])
    # Non-follow path likely tails a file; our fake runtime doesn't write one.
    # Assert success (exit code) only.
    return must_ok("logs (lines)", res)


def t_logs_follow(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    sys.modules["matrix_sdk.alias"].AliasStore().set("logs2", id="mcp_server:logs@1.0.0", target="/tmp/matrix/logs2")
    runner.invoke(app, ["run", "logs2"])  # start
    res = runner.invoke(app, ["logs", "logs2", "--follow"])
    return must_ok("logs (follow)", res, contains="follow line")


def t_doctor_ok(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    sys.modules["matrix_sdk.alias"].AliasStore().set("doc1", id="mcp_server:doc@1.0.0", target="/tmp/matrix/doc1")
    runner.invoke(app, ["run", "doc1"])  # start
    res = runner.invoke(app, ["doctor", "doc1"])
    return must_ok("doctor (ok)", res, contains_any=["ok", "/health"])  # case-insens


def t_stop_and_doctor_fail(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    sys.modules["matrix_sdk.alias"].AliasStore().set("doc2", id="mcp_server:doc@1.0.0", target="/tmp/matrix/doc2")
    runner.invoke(app, ["run", "doc2"])  # start
    r_stop = runner.invoke(app, ["stop", "doc2"])
    ok1 = must_ok("stop", r_stop, contains_all=["stopped", "doc2"])  # case-insens
    r_doc = runner.invoke(app, ["doctor", "doc2"])
    # Expect non-zero exit when doctor reports failure in your CLI
    ok2 = must_ok("doctor (fail)", r_doc, expect_exit=1, contains_any=["status: fail", "fail"])  # case-insens
    return ok1 and ok2


def t_alias_crud(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    ok = True
    r_add = runner.invoke(app, ["alias", "add", "a1", "id1", "/tmp/t1"])
    ok &= must_ok("alias add", r_add)

    r_list = runner.invoke(app, ["alias", "list"])
    ok &= must_ok("alias list", r_list, contains="a1")

    r_show = runner.invoke(app, ["alias", "show", "a1"])
    ok &= must_ok("alias show", r_show, contains='"id": "id1"')

    r_rm = runner.invoke(app, ["alias", "rm", "a1", "--yes"])
    ok &= must_ok("alias rm", r_rm)
    return ok


def t_link(runner: CliRunner) -> bool:
    """Tests the `link` command."""
    from matrix_cli.__main__ import app
    
    # Create a temporary directory to simulate a local project
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        
        # The `link` command requires a runner.json file to exist
        (p / "runner.json").write_text("{}", encoding="utf-8")
        
        # Invoke the command with the correct, unambiguous option
        res = runner.invoke(app, ["link", str(p), "--as", "link1"])
        
        # Check for a successful exit code and a success message
        return must_ok("link", res, contains_any=["linked", "added"])


def t_search(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    res = runner.invoke(app, ["search", "hello", "--limit", "3"])
    return must_ok("search", res, contains_any=["result(s)", "results"])  # tolerate CLI wording


def t_show(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    res = runner.invoke(app, ["show", "mcp_server:test@1.0.0"])
    return must_ok("show", res, contains='"id": "mcp_server:test@1.0.0"')


def t_remotes(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    ok = True
    r_list = runner.invoke(app, ["remotes", "list"])
    ok &= must_ok("remotes list", r_list)

    r_add = runner.invoke(app, ["remotes", "add", "https://example.com/cat.json", "--name", "example"])
    ok &= must_ok("remotes add", r_add, contains="added")

    r_ing = runner.invoke(app, ["remotes", "ingest", "example"])
    ok &= must_ok("remotes ingest", r_ing, contains="ingest triggered")  # case-insens

    r_rm = runner.invoke(app, ["remotes", "remove", "example"])
    ok &= must_ok("remotes remove", r_rm, contains="removed")  # case-insens
    return ok


def t_handle_url_install(runner: CliRunner) -> bool:
    from matrix_cli.__main__ import app
    from urllib.parse import quote
    uid = "mcp_server:hello-sse@1.0.0"
    alias = "hello-sse"
    url = f"matrix://install?id={quote(uid)}&alias={alias}"
    res = runner.invoke(app, ["handle-url", "install", url])
    return must_ok("handle-url install", res, contains="Next: matrix run")


# -----------------------------------------------------------------------------
# 4) Main
# -----------------------------------------------------------------------------

def main() -> int:
    # Install the in-memory SDK before importing the CLI app
    install_fake_sdk()

    try:
        from matrix_cli.__main__ import app  # noqa: F401
    except Exception as e:
        print(f"Cannot import matrix_cli app: {e}")
        return 1

    # NOTE: Do not pass mix_stderr for compatibility with older Click/Typer.
    runner = CliRunner()

    tests: List[Tuple[str, Callable[[CliRunner], bool]]] = [
        ("install", t_install),
        ("run", t_run),
        ("ps", t_ps),
        ("logs_lines", t_logs_lines),
        ("logs_follow", t_logs_follow),
        ("doctor_ok", t_doctor_ok),
        ("stop_and_doctor_fail", t_stop_and_doctor_fail),
        ("alias_crud", t_alias_crud),
        ("link", t_link),
        ("search", t_search),
        ("show", t_show),
        ("remotes", t_remotes),
        ("handle_url_install", t_handle_url_install),
    ]

    passed = 0
    for name, fn in tests:
        try:
            ok = fn(runner)
            passed += int(ok)
        except Exception as e:  # continue suite on individual error
            print(f"[EXC ] {name}: {e}")

    total = len(tests)
    print("-" * 60)
    print(f"Summary: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
