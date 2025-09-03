# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import sys
import importlib
from types import SimpleNamespace, ModuleType
from unittest import mock
import pytest

from typer.testing import CliRunner

# We import this now, but will reload it later
from matrix_cli.commands.help import app as help_app

runner = CliRunner()

# --- Fake MCP Mock Setup ---
# This is a self-contained, simple-to-understand mock structure.
# It defines all the fake modules help.py expects.

class _DummyTransportCtx:
    async def __aenter__(self):
        return (None, None)
    async def __aexit__(self, exc_type, exc, tb):
        return False

class _FakeSession:
    def __init__(self, rs, ws):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def initialize(self):
        return {"cap": "ok"}
    async def list_tools(self):
        Tool = SimpleNamespace
        tools = [
            Tool(
                name="chat",
                description="Free-form chat",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ]
        return SimpleNamespace(tools=tools)

# The core of the fix: define the full fake module hierarchy
_fake_modules_to_patch = {
    "matrix_cli.commands.mcp": SimpleNamespace(
        _final_url_from_inputs=mock.Mock(return_value=("http://127.0.0.1:7777/messages/", SimpleNamespace())),
        DEFAULT_ENDPOINT="/messages/",
        _is_http_like=lambda url: url.startswith("http"),
        _is_ws_like=lambda url: url.startswith("ws"),
        ClientSession=_FakeSession
    ),
    "mcp": SimpleNamespace(),
    "mcp.client": SimpleNamespace(),
    "mcp.client.sse": SimpleNamespace(sse_client=lambda url, timeout: _DummyTransportCtx()),
    "mcp.client.websocket": SimpleNamespace(websocket_client=lambda url, timeout: _DummyTransportCtx())
}

@pytest.fixture(autouse=True)
def _mock_modules():
    """Patches sys.modules to simulate the required package structure."""
    with mock.patch.dict(sys.modules, _fake_modules_to_patch):
        yield

# Remaining tests go here