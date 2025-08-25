from __future__ import annotations
from urllib.parse import quote

from matrix_cli.__main__ import app


def test_handle_url_installs_and_saves_alias(runner, fake_sdk):
    uid = "mcp_server:hello-sse@1.0.0"
    alias = "hello-sse"
    url = f"matrix://install?id={quote(uid)}&alias={alias}"

    res = runner.invoke(app, ["handle-url", "install", url])
    assert res.exit_code == 0, res.stdout
    # installer called
    calls = fake_sdk["installer"].build_calls
    assert calls and calls[-1][0] == uid
    # alias saved
    store = fake_sdk["alias"].AliasStore()
    assert store.get(alias) is not None
    # friendly hint
    assert "Next: matrix run" in res.stdout


def test_handle_url_requires_id(runner):
    bad = "matrix://install?alias=foo"
    res = runner.invoke(app, ["handle-url", "install", bad])
    assert res.exit_code == 2
    assert "Invalid deep link" in res.stdout
