# matrix-cli/tests/test_alias_store.py
from __future__ import annotations

import json
import sys
import types

# --- Test-only shim ---------------------------------------------------------
# Some commands imported by matrix_cli.__main__ now depend on matrix_cli.resolution.
# This test exercises the alias CLI only, so we provide a lightweight stub for
# matrix_cli.resolution to avoid import failures during test collection.
if "matrix_cli.resolution" not in sys.modules:
    mock_resolution = types.ModuleType("matrix_cli.resolution")

    class _ResolutionResult:
        def __init__(self, fqid: str, note: str = "") -> None:
            self.fqid = fqid
            self.note = note
            self.source_hub = ""
            self.used_local_fallback = False
            self.broadened = False
            self.explanation = ""

    def resolve_fqid(client, cfg, raw_id: str, **kwargs):
        # Return a minimal object with the attributes used by install.py
        return _ResolutionResult(fqid=raw_id)

    mock_resolution.resolve_fqid = resolve_fqid
    sys.modules["matrix_cli.resolution"] = mock_resolution
# ---------------------------------------------------------------------------

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
