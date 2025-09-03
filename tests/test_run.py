# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock
from pathlib import Path

import typer
import pytest
from typer.testing import CliRunner

# We will lazily import run_app inside each test to ensure mocks are in place.

runner = CliRunner()


@pytest.fixture
def run_app():
    # Lazily import the app to ensure mocks are in place before module load
    from matrix_cli.commands.run import app as run_app
    return run_app

# --- Mocking the SDK dependencies with a fixture ---
@pytest.fixture(autouse=True)
def _mock_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Mocks external dependencies for all tests in this file."""
    
    # We create a simple, working mock for AliasStore
    class FakeAliasStore:
        _store: dict = {}

        def set(self, alias: str, target: str):
            self._store[alias] = {"target": target}

        def get(self, alias: str):
            return self._store.get(alias)

    # We mock the entire modules to control their behavior
    alias_mod_mock = MagicMock()
    alias_mod_mock.AliasStore.return_value = FakeAliasStore()
    
    runtime_mod_mock = MagicMock()
    runtime_mod_mock.start.return_value = SimpleNamespace(
        pid=1234,
        port=7777,
        host="127.0.0.1",
        url=None,
    )

    monkeypatch.setitem(sys.modules, "matrix_sdk.alias", alias_mod_mock)
    monkeypatch.setitem(sys.modules, "matrix_sdk.runtime", runtime_mod_mock)


def _write_runner_json(tmp: Path, data: dict) -> None:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "runner.json").write_text(json.dumps(data), encoding="utf-8")


def test_quickstart_no_input_banner(tmp_path: Path, run_app: typer.Typer):
    data = {
        "integration_type": "MCP",
        "tools": [{"name": "status", "input_schema": {"type": "object", "properties": {}, "required": []}}],
    }
    _write_runner_json(tmp_path, data)
    
    # Manually setup alias
    alias_mod = importlib.import_module("matrix_sdk.alias")
    alias_mod.AliasStore().set("srv0", target=str(tmp_path))
    
    runner.invoke(run_app, ["srv0"])


def test_quickstart_single_string_banner(tmp_path: Path, run_app: typer.Typer):
    data = {
        "integration_type": "MCP",
        "tools": [
            {
                "name": "chat",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
    }
    _write_runner_json(tmp_path, data)

    # Manually setup alias
    alias_mod = importlib.import_module("matrix_sdk.alias")
    alias_mod.AliasStore().set("srv1", target=str(tmp_path))
    
    runner.invoke(run_app, ["srv1"])


def test_quickstart_complex_banner(tmp_path: Path, run_app: typer.Typer):
    data = {
        "integration_type": "MCP",
        "tools": [
            {
                "name": "resize",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "width": {"type": "integer"}},
                    "required": ["path", "width"],
                },
            }
        ],
    }
    _write_runner_json(tmp_path, data)

    # Manually setup alias
    alias_mod = importlib.import_module("matrix_sdk.alias")
    alias_mod.AliasStore().set("srv2", target=str(tmp_path))
    
    runner.invoke(run_app, ["srv2"])


def test_quickstart_url_banner(tmp_path: Path, run_app: typer.Typer):
    data = {
        "integration_type": "MCP",
        "url": "http://127.0.0.1:8888/sse/",
        "tools": [
            {
                "name": "chat",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
    }
    _write_runner_json(tmp_path, data)

    # Manually setup alias
    alias_mod = importlib.import_module("matrix_sdk.alias")
    alias_mod.AliasStore().set("srv3", target=str(tmp_path))
    
    runner.invoke(run_app, ["srv3"])