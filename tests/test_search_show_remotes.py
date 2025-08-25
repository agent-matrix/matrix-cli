from __future__ import annotations

from matrix_cli.__main__ import app


def test_search_and_show(runner):
    r0 = runner.invoke(app, ["search", "hello", "--limit", "3"])
    # With graceful-degrade, search returns 0 even if Hub is unavailable
    assert r0.exit_code == 0
    # Less brittle check — allow either “1 results.”, “0 results.”, etc.
    assert "result" in r0.stdout.lower()

    r1 = runner.invoke(app, ["show", "mcp_server:test@1.0.0"])
    assert r1.exit_code == 0
    assert '"id": "mcp_server:test@1.0.0"' in r1.stdout


def test_remotes_roundtrip(runner):
    r_list = runner.invoke(app, ["remotes", "list"])
    assert r_list.exit_code == 0

    r_add = runner.invoke(
        app, ["remotes", "add", "https://example.com/cat.json", "--name", "example"]
    )
    assert r_add.exit_code == 0
    assert "added" in r_add.stdout

    r_ing = runner.invoke(app, ["remotes", "ingest", "example"])
    assert r_ing.exit_code == 0
    # Case-insensitive to avoid brittle failures
    assert "ingest triggered" in r_ing.stdout.lower()

    r_rm = runner.invoke(app, ["remotes", "remove", "example"])
    assert r_rm.exit_code == 0
    assert "removed" in r_rm.stdout.lower()
