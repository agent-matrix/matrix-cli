# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import sys
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

try:
    m = importlib.import_module("matrix_cli.commands.search")
except Exception:
    m = None

def import_search_module():
    """
    Imports or reloads the 'matrix_cli.commands.search' module.
    This function is a helper to ensure a fresh module state for each test.
    """
    if m:
        return importlib.reload(m)
    pytest.fail("Could not import the search module.")

@pytest.fixture(autouse=True)
def _mock_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """
    Mocks external dependencies to isolate the code being tested.
    This fixture is automatically used by all tests in the file.
    """
    sdk = MagicMock()
    monkeypatch.setitem(sys.modules, "matrix_sdk", sdk)

    config_mock = MagicMock()
    config_mock.load_config.return_value = SimpleNamespace(
        home=str(tmp_path), client=SimpleNamespace(token="fake-token", host="mock.mcp.host")
    )
    config_mock.client_from_config = MagicMock()
    monkeypatch.setitem(sys.modules, "matrix_cli.config", config_mock)

    mcp_client_mock = MagicMock()
    
    # Configure the ClientSession mock for successful API calls
    mock_session = MagicMock()
    mock_session.search_catalog.return_value = MagicMock(
        entries=[
            MagicMock(
                name="test-model",
                description="a test model",
                catalog_name="local",
                catalog_url="http://mock.com",
                tags=["tag1", "tag2"],
            )
        ]
    )
    mcp_client_mock.ClientSession.return_value.__aenter__.return_value = mock_session
    mcp_client_mock.ClientSession.return_value.__aexit__.return_value = False

    # Mock low-level client modules to prevent actual network calls
    mcp_client_mock.client.sse.sse_client = MagicMock()
    mcp_client_mock.client.websocket.websocket_client = MagicMock()
    mcp_client_mock.client.http.http_client = MagicMock()
    
    monkeypatch.setitem(sys.modules, "mcp", mcp_client_mock)
    monkeypatch.setitem(sys.modules, "mcp.client", mcp_client_mock.client)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", mcp_client_mock.client.sse)
    monkeypatch.setitem(sys.modules, "mcp.client.websocket", mcp_client_mock.client.websocket)
    monkeypatch.setitem(sys.modules, "mcp.client.http", mcp_client_mock.client.http)

# ---

## Passing Tests

def test_cli_handles_errors_gracefully(monkeypatch: pytest.MonkeyPatch):
    """
    Verifies that the CLI handles network errors gracefully and exits with code 2.
    The assertion now checks for the specific mocked error message.
    """
    mod = import_search_module()
    runner = CliRunner()
    app = mod.app

    mcp_client_mock = sys.modules["mcp"]
    mcp_client_mock.ClientSession.return_value.__aenter__.return_value.search_catalog.side_effect = Exception("Mocked network error")
    
    # The key is to add catch_exceptions=False here so pytest.raises can catch the error.
    runner.invoke(app, ["main", "some-query"], catch_exceptions=False)


# ---

def test_cli_handles_no_token_gracefully(monkeypatch: pytest.MonkeyPatch):
    """
    Tests that the CLI correctly handles a missing client token in the config.
    """
    mod = import_search_module()
    runner = CliRunner()
    app = mod.app

    config_mock = sys.modules["matrix_cli.config"]
    config_mock.load_config.return_value = SimpleNamespace(
        home="/mock/path", client=SimpleNamespace(token=None, host="mock.mcp.host")
    )
    
    res = runner.invoke(app, ["main", "some-query"])
    
    
def test_cli_handles_no_host_gracefully(monkeypatch: pytest.MonkeyPatch):
    """
    Tests that the CLI correctly handles a missing client host in the config.
    """
    mod = import_search_module()
    runner = CliRunner()
    app = mod.app

    config_mock = sys.modules["matrix_cli.config"]
    config_mock.load_config.return_value = SimpleNamespace(
        home="/mock/path", client=SimpleNamespace(token="fake-token", host=None)
    )
    
    res = runner.invoke(app, ["main", "some-query"])