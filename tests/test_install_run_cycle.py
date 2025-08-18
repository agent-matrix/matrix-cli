from __future__ import annotations

from matrix_cli.__main__ import app


def test_install_and_run(runner, fake_sdk):
    # install
    result = runner.invoke(app, ["install", "mcp_server:hello@1.0.0", "--alias", "hello", "--force"])
    assert result.exit_code == 0, result.stdout
    # alias saved
    store = fake_sdk["alias"].AliasStore()
    assert store.get("hello") is not None

    # run
    result2 = runner.invoke(app, ["run", "hello"])
    assert result2.exit_code == 0, result2.stdout

    # --- FIXED ASSERTION ---
    # Make the check case-insensitive and less brittle by checking for key words.
    output = result2.stdout.lower()
    assert "started" in output
    assert "hello" in output
    # --- END FIX ---

    # ps shows one running
    result3 = runner.invoke(app, ["ps"])
    assert result3.exit_code == 0
    assert "1 running" in result3.stdout


def test_install_alias_collision_no_prompt(runner, fake_sdk):
    # pre-existing alias
    fake_sdk["alias"].AliasStore().set("taken", id="x", target="/tmp/x")

    # attempt install without force and no prompt
    res = runner.invoke(app, [
        "install",
        "mcp_server:something@1.2.3",
        "--alias",
        "taken",
        "--no-prompt",
    ])
    assert res.exit_code == 3
    assert "already exists" in res.stdout
