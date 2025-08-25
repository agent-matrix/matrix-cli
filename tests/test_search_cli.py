# SPDX-License-Identifier: Apache-2.0
# tests/test_search_cli.py
from __future__ import annotations

import json
import importlib
from typing import Any, Dict

import pytest
from typer.testing import CliRunner


class FakeMatrixError(Exception):
    def __init__(self, status_code: int, detail: str = "bad"):
        super().__init__(detail)
        self.status_code = status_code


class FakeClient:
    def __init__(self, payload: Dict[str, Any] | Exception):
        self._payload = payload

    def search(self, **params) -> Dict[str, Any]:
        if isinstance(self._payload, Exception):
            raise self._payload
        # Echo the params back so we can assert them in --json mode
        out = dict(self._payload)
        out["__params__"] = params
        return out


def import_search_module():
    """
    Import the CLI search command as a package module so its relative imports resolve:
    matrix_cli.commands.search
    """
    m = importlib.import_module("matrix_cli.commands.search")
    return importlib.reload(m)


def test_cli_prints_table(monkeypatch: pytest.MonkeyPatch):
    mod = import_search_module()

    payload = {
        "items": [
            {
                "id": "tool:hello@0.1.0",
                "type": "tool",
                "name": "hello",
                "version": "0.1.0",
                "summary": "Hello from SDK",
                "score_final": 0.42,
            }
        ],
        "total": 1,
    }
    # Stub SDK client factory
    mod.client_from_config = lambda cfg: FakeClient(payload)  # type: ignore[attr-defined]

    runner = CliRunner()
    result = runner.invoke(
        mod.app, ["Hello", "--type", "tool", "--mode", "keyword", "--limit", "5"]
    )
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "tool:hello@0.1.0" in out
    assert "results" in out.lower()


def test_cli_json_flag_outputs_raw_json(monkeypatch: pytest.MonkeyPatch):
    mod = import_search_module()

    payload = {"items": [], "total": 0}
    mod.client_from_config = lambda cfg: FakeClient(payload)  # type: ignore[attr-defined]

    runner = CliRunner()
    result = runner.invoke(mod.app, ["Nothing", "--json"])
    assert result.exit_code == 0, result.stdout

    data = json.loads(result.stdout)
    assert data["items"] == []
    assert data["total"] == 0
    # New default behavior: pending included by default (even in prod) unless user requests certified-only.
    assert data["__params__"] == {"q": "Nothing", "limit": 5, "include_pending": True}


def test_cli_handles_matrix_error(monkeypatch: pytest.MonkeyPatch):
    """
    With the new graceful-degrade behavior, non-JSON mode should NOT fail the process.
    It should warn and print '0 results.' with exit code 0.
    """
    mod = import_search_module()

    err = FakeMatrixError(500, "boom")
    mod.client_from_config = lambda cfg: FakeClient(err)  # type: ignore[attr-defined]

    runner = CliRunner()
    result = runner.invoke(mod.app, ["Hello"])
    # New behavior: exit 0 in human mode (non-JSON), warn, and show '0 results.'
    assert result.exit_code == 0, result.stdout
    assert "search failed" in result.stdout.lower()
    assert "0 results" in result.stdout.lower()
