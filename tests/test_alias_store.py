from __future__ import annotations
import json

from matrix_cli.__main__ import app


def test_alias_crud_via_cli(runner, fake_sdk):
    # add
    r0 = runner.invoke(app, ["alias", "add", "a1", "id1", "/tmp/t1"])
    assert r0.exit_code == 0

    # list contains a1
    r1 = runner.invoke(app, ["alias", "list"])
    assert r1.exit_code == 0
    assert "a1" in r1.stdout

    # show returns JSON
    r2 = runner.invoke(app, ["alias", "show", "a1"])
    assert r2.exit_code == 0
    payload = json.loads(r2.stdout)
    assert payload["id"] == "id1"

    # remove
    r3 = runner.invoke(app, ["alias", "rm", "a1", "--yes"])
    assert r3.exit_code == 0

    # removing again should fail with exit code 1
    r4 = runner.invoke(app, ["alias", "rm", "a1", "--yes"])
    assert r4.exit_code == 1
