from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from matrix_cli.__main__ import app


# --- New: ensure the fake installer exposes the APIs the CLI now uses -----
def _ensure_fake_installer_apis(fake_sdk):
    """
    Make the fake SDK's LocalInstaller quack like the real one:
    - materialize(outcome, target) -> BuildReport(runner_path=...)
    - prepare_env(target_path, runner, timeout)
    - _load_runner_from_report(report, target_path) -> dict
    """
    InstallerMod = fake_sdk.get("installer")
    assert InstallerMod is not None, "fake_sdk['installer'] module missing"
    LocalInstaller = InstallerMod.LocalInstaller

    # Define a tiny BuildReport the CLI expects (runner_path is used)
    @dataclass(frozen=True)
    class _BuildReport:
        files_written: int = 0
        artifacts_fetched: int = 0
        runner_path: str | None = None

    # Inject BuildReport into the fake installer module (optional, but handy)
    setattr(InstallerMod, "BuildReport", _BuildReport)

    # materialize: create target dir, write a minimal runner.json (and server.py, optional)
    def _fake_materialize(self, outcome, target):
        t = Path(target).expanduser().resolve()
        t.mkdir(parents=True, exist_ok=True)

        # Write a simple runner.json that the rest of the toolchain can read
        runner_json = {
            "type": "python",
            "entry": "server.py",
            "python": {"venv": ".venv"},
        }
        (t / "runner.json").write_text(
            json.dumps(runner_json, indent=2), encoding="utf-8"
        )

        # Optional: a tiny server file so later steps don't choke if they look for it
        (t / "server.py").write_text("print('hello: started')\n", encoding="utf-8")

        return _BuildReport(
            files_written=2, artifacts_fetched=0, runner_path=str(t / "runner.json")
        )

    # prepare_env: no-op for tests
    def _fake_prepare_env(self, target_path, runner, *, timeout=900):
        return True

    # loader: mirror the SDK helper so the CLI can load the runner data
    def _fake_load_runner_from_report(self, report, target_path):
        rp = (
            Path(report.runner_path)
            if getattr(report, "runner_path", None)
            else Path(target_path) / "runner.json"
        )
        return json.loads(rp.read_text(encoding="utf-8")) if rp.is_file() else {}

    # Patch only if missing (keep existing behaviors if present)
    if not hasattr(LocalInstaller, "materialize"):
        LocalInstaller.materialize = _fake_materialize  # type: ignore[attr-defined]
    if not hasattr(LocalInstaller, "prepare_env"):
        LocalInstaller.prepare_env = _fake_prepare_env  # type: ignore[attr-defined]
    if not hasattr(LocalInstaller, "_load_runner_from_report"):
        LocalInstaller._load_runner_from_report = _fake_load_runner_from_report  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------


def test_install_and_run(runner, fake_sdk):
    # Ensure the fake SDK's MatrixClient has an `install` method (the plan call)
    MatrixClient = fake_sdk["client"].MatrixClient
    if not hasattr(MatrixClient, "install"):

        def _fake_install(self, fqid: str, target: str):
            # Return a plan-like dict; CLI converts to dict and passes to materialize()
            return {
                "id": fqid,
                "target": target,  # <alias>/<version> label
                "items": [],
                "plan": {"label": target},  # minimal shape
            }

        setattr(MatrixClient, "install", _fake_install)

    # NEW: make the fake installer quack like the real one
    _ensure_fake_installer_apis(fake_sdk)

    # install
    result = runner.invoke(
        app, ["install", "mcp_server:hello@1.0.0", "--alias", "hello", "--force"]
    )
    assert result.exit_code == 0, result.stdout

    # alias saved
    store = fake_sdk["alias"].AliasStore()
    assert store.get("hello") is not None

    # run
    result2 = runner.invoke(app, ["run", "hello"])
    assert result2.exit_code == 0, result2.stdout
    out_lower = result2.stdout.lower()
    assert "started" in out_lower
    assert "hello" in out_lower

    # ps shows one running
    result3 = runner.invoke(app, ["ps"])
    assert result3.exit_code == 0
    assert "1 running" in result3.stdout


def test_install_alias_collision_no_prompt(runner, fake_sdk):
    # pre-existing alias
    fake_sdk["alias"].AliasStore().set("taken", id="x", target="/tmp/x")

    # attempt install without force and no prompt
    res = runner.invoke(
        app,
        [
            "install",
            "mcp_server:something@1.2.3",
            "--alias",
            "taken",
            "--no-prompt",
        ],
    )
    assert res.exit_code == 3
    assert "already exists" in res.stdout
