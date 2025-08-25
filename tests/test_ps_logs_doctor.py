from __future__ import annotations

from matrix_cli.__main__ import app


def test_ps_logs_doctor_ok_flow(runner, fake_sdk, mocker):
    # prepare alias and run
    fake_sdk["alias"].AliasStore().set(
        "svc", id="mcp_server:svc@1.0.0", target="/tmp/matrix/svc"
    )

    r0 = runner.invoke(app, ["run", "svc"])
    assert r0.exit_code == 0, r0.stdout

    # ps
    r1 = runner.invoke(app, ["ps"])
    assert r1.exit_code == 0
    assert "1 running" in r1.stdout

    # We patch the function that the 'logs' command calls to get log lines.
    mock_tail_logs = mocker.patch("matrix_sdk.runtime.tail_logs")

    # logs (last lines)
    # Configure the mock to return specific fake log lines for this call.
    mock_tail_logs.return_value = ["svc L0\n", "svc L1\n"]
    r2 = runner.invoke(app, ["logs", "svc", "--lines", "2"])
    assert r2.exit_code == 0
    assert "svc L0" in r2.stdout
    # Verify that the SDK function was called correctly by our command.
    mock_tail_logs.assert_called_with("svc", follow=False, n=2)

    # logs (follow) — our fake generator yields a bounded set
    # Re-configure the same mock for the next call.
    mock_tail_logs.return_value = ["follow line 1\n", "follow line 2\n"]
    r3 = runner.invoke(app, ["logs", "svc", "--follow"])
    assert r3.exit_code == 0
    assert "follow line" in r3.stdout
    mock_tail_logs.assert_called_with(
        "svc", follow=True, n=40
    )  # 40 is the default line count

    # doctor
    r4 = runner.invoke(app, ["doctor", "svc"])
    assert r4.exit_code == 0
    # --- FIX: Make assertion case-insensitive and less brittle ---
    assert "ok" in r4.stdout.lower()

    # stop
    r5 = runner.invoke(app, ["stop", "svc"])
    assert r5.exit_code == 0

    # doctor should now fail
    r6 = runner.invoke(app, ["doctor", "svc"])
    # --- FIX: A failed doctor check should exit with a non-zero code ---
    assert r6.exit_code == 1
    # --- FIX: Make assertion case-insensitive and less brittle ---
    assert "fail" in r6.stdout.lower()
