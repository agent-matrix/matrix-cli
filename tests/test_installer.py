# matrix_cli/tests/test_installer.py
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Import the CLI app
from matrix_cli.commands.install import app as install_app

# We'll patch these modules/symbols inside matrix_cli.commands.install
import matrix_cli.commands.install as cli_mod


class _DummyCfg:
    def __init__(self, hub_base: str, token: str, home: str):
        self.hub_base = hub_base
        self.token = token
        self.home = home


class _DummyClient:
    """Minimal client for cli flow: only install() is used directly."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.token = token

    def install(self, fqid: str, *, target: str):
        # Return a minimal plan; we *don't* include runner_url here so
        # the CLI must honor --runner-url flag and write runner.json.
        return {"plan": {"files": [], "artifacts": []}}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Block any accidental real network usage by raising if urlopen is called without our test override."""

    def _fail(*args, **kwargs):
        raise RuntimeError("Unexpected network call in test")

    monkeypatch.setattr("urllib.request.urlopen", _fail, raising=True)


def _patch_common_cli_bits(tmp_path, monkeypatch):
    """Shared patches for CLI: config, client, target_for, resolver, AliasStore, and LocalInstaller light stubs."""
    # load_config → return dummy config using tmp_path as HOME root
    monkeypatch.setattr(
        cli_mod, "load_config", lambda: _DummyCfg("http://hub", "tok", str(tmp_path))
    )

    # client_from_config → return our dummy client
    monkeypatch.setattr(
        cli_mod, "client_from_config", lambda cfg: _DummyClient(cfg.hub_base, cfg.token)
    )

    # target_for → deterministically use tmp_path/inst/<alias>/<ver>
    def _target_for(_fqid, *, alias, cfg):
        return str(tmp_path / "inst" / alias / "0.1.0")

    monkeypatch.setattr(cli_mod, "target_for", _target_for)

    # resolve_fqid → return object with fqid, note=None
    class _Resolved:
        def __init__(self, fqid, note=None):
            self.fqid, self.note = fqid, note

    monkeypatch.setattr(
        cli_mod,
        "resolve_fqid",
        lambda *a, **k: _Resolved("mcp_server:watsonx-agent@0.1.0"),
    )

    # AliasStore → in-memory stub to avoid touching user files
    alias_mod = types.SimpleNamespace()

    class _AliasStore:
        _db = {}

        def get(self, alias):
            return self._db.get(alias)

        def set(self, alias, *, id, target):
            self._db[alias] = {"id": id, "target": target}

    alias_mod.AliasStore = _AliasStore
    monkeypatch.setitem(sys.modules, "matrix_sdk.alias", alias_mod)

    # LocalInstaller → patch heavy bits on the real (or faked-by-conftest) class
    import matrix_sdk.installer as sdk_inst

    # 1) prevent venv/pip work — avoid referring to EnvReport (may not exist in fake)
    monkeypatch.setattr(
        sdk_inst.LocalInstaller, "prepare_env", lambda *a, **k: None, raising=False
    )

    # 2) make materialize a no-op that still ensures target exists; return a benign object
    def _fake_materialize(self, outcome, target):
        Path(target).mkdir(parents=True, exist_ok=True)
        return {}  # CLI doesn't depend on its structure in our test

    monkeypatch.setattr(
        sdk_inst.LocalInstaller, "materialize", _fake_materialize, raising=False
    )

    # 3) loader: read runner.json if present, else empty dict
    def _fake_load(self, report, target_path: Path):
        p = Path(target_path) / "runner.json"
        return json.loads(p.read_text()) if p.exists() else {}

    monkeypatch.setattr(
        sdk_inst.LocalInstaller, "_load_runner_from_report", _fake_load, raising=False
    )


def test_cli_install_writes_runner_json_from_flag(tmp_path, monkeypatch):
    """
    Given: user passes --runner-url
    Expect: CLI writes runner.json in target and completes without touching real env/git.
    """
    _patch_common_cli_bits(tmp_path, monkeypatch)

    # --- Provide a controlled urlopen for --runner-url ---
    runner_obj = {"type": "python", "entry": "bin/run.py"}

    def _ok_urlopen(url, timeout=10):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(runner_obj).encode("utf-8")

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _ok_urlopen, raising=True)

    # --- Act: run CLI ---
    runner = CliRunner()
    target_dir = Path(tmp_path) / "inst" / "watsonx-chat" / "0.1.0"
    args = [
        "mcp_server:watsonx-agent@0.1.0",
        "--alias",
        "watsonx-chat",
        "--target",
        str(target_dir),
        "--runner-url",
        "https://example.test/runner.json",
        "--force",
        "--no-prompt",
    ]
    result = runner.invoke(install_app, args)

    # --- Assert ---
    assert result.exit_code == 0, result.output
    rpath = target_dir / "runner.json"
    assert rpath.is_file(), "runner.json should be written by CLI from --runner-url"
    data = json.loads(rpath.read_text())
    assert data["type"] == "python" and data["entry"] == "bin/run.py"


def test_cli_install_repo_url_triggers_fake_clone(tmp_path, monkeypatch):
    """
    Given: user passes --runner-url and --repo-url
    And target does not contain the runner 'entry' file yet
    Expect: CLI clones repo (simulated), copies files into target, runner.json exists, and the entry file appears.
    """
    _patch_common_cli_bits(tmp_path, monkeypatch)

    # Controlled runner.json via --runner-url
    runner_obj = {"type": "python", "entry": "bin/run.py"}

    def _ok_urlopen(url, timeout=10):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps(runner_obj).encode("utf-8")

        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _ok_urlopen, raising=True)

    # Fake TemporaryDirectory and subprocess.run("git clone ...")
    import tempfile as _tempfile

    fake_tmp_root = Path(tmp_path) / "fakeclone"

    def _fake_tempdir():
        class _Ctx:
            def __init__(self, base):
                self.name = str(base)

            def __enter__(self):
                Path(self.name).mkdir(parents=True, exist_ok=True)
                return self.name

            def __exit__(self, *exc):
                return False

        return _Ctx(fake_tmp_root)

    monkeypatch.setattr(_tempfile, "TemporaryDirectory", _fake_tempdir, raising=True)

    def _fake_run(cmd, *args, **kwargs):
        # cmd looks like: ["git", "clone", "--depth=1", repo_url, tmpd]
        tmpd = Path(cmd[-1])
        # Simulate repo contents that the CLI will copy into target
        (tmpd / "bin").mkdir(parents=True, exist_ok=True)
        (tmpd / "bin" / "run.py").write_text(
            "#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8"
        )
        (tmpd / "requirements.txt").write_text("fastmcp\n", encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    import subprocess as _subprocess

    monkeypatch.setattr(_subprocess, "run", _fake_run, raising=True)

    # --- Act ---
    runner = CliRunner()
    target_dir = Path(tmp_path) / "inst" / "watsonx-chat" / "0.1.0"
    args = [
        "mcp_server:watsonx-agent@0.1.0",
        "--alias",
        "watsonx-chat",
        "--target",
        str(target_dir),
        "--runner-url",
        "https://example.test/runner.json",
        "--repo-url",
        "https://github.com/ruslanmv/watsonx-mcp.git",
        "--force",
        "--no-prompt",
    ]
    result = runner.invoke(install_app, args)

    # --- Assert ---
    assert result.exit_code == 0, result.output
    rpath = target_dir / "runner.json"
    assert rpath.is_file(), "runner.json should be written by CLI"
    entry = target_dir / "bin" / "run.py"
    assert entry.is_file(), (
        "--repo-url should have cloned (simulated) files into target"
    )
