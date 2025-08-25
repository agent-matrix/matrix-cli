#!/usr/bin/env python3
"""
Matrix CLI — Standalone Integration Test

• Tests the full user workflow against a running local MatrixHub server.
• Does not require pytest; can be run directly:
  `python your_script_name.py`

Prerequisites:
  - A local MatrixHub server must be running at http://localhost:443.
  - The server must have a component available for search (e.g., 'hello').

Exit code is 0 if all checks pass, non-zero otherwise.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

from typer.testing import CliRunner

# Assume the main 'app' is importable from the CLI's entrypoint
from matrix_cli.__main__ import app

# --- Helper function for checking results ---

def out_of(result) -> str:
    """Support both Click 7 (result.output) and Click 8+ (result.stdout)"""
    return getattr(result, "stdout", getattr(result, "output", ""))

def must_ok(
    label: str,
    result,
    expect_exit: int = 0,
    *,
    contains: str | None = None,
    contains_all: list[str] | None = None,
) -> bool:
    """Unified assertion helper (case-insensitive contains checks)."""
    text = out_of(result)
    ok = (result.exit_code == expect_exit)
    print(f"\n--> {label}")
    print(text.strip())

    def has(s: str) -> bool:
        return s.lower() in text.lower()

    if contains is not None:
        ok = ok and has(contains)
    if contains_all:
        ok = ok and all(has(s) for s in contains_all)

    status = "PASS" if ok else "FAIL"
    print(f"--> Status: {status} (Exit: {result.exit_code})")
    return ok

# --- Main test logic ---

def main() -> int:
    """Runs the integration test lifecycle."""
    runner = CliRunner()
    original_hub = os.environ.get("MATRIX_HUB_BASE")
    original_home = os.environ.get("MATRIX_HOME")
    all_passed = True

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # 1. --- SETUP ---
            # Redirect the CLI to the local server and a temporary home directory.
            os.environ["MATRIX_HUB_BASE"] = "http://localhost:443"
            os.environ["MATRIX_HOME"] = temp_dir
            print("--- Starting Integration Test Lifecycle ---")
            print(f"HUB_BASE set to: {os.environ['MATRIX_HUB_BASE']}")
            print(f"MATRIX_HOME set to: {os.environ['MATRIX_HOME']}")

            # IMPORTANT: Change this to a real component ID that exists on your server.
            component_to_test = "mcp_server:hello-sse-server@0.1.0"
            search_term = "hello"
            alias = "local-hello"

            # 2. --- SEARCH ---
            r_search = runner.invoke(app, ["search", search_term])
            all_passed &= must_ok("Search", r_search, contains_all=["result", "mcp_server"])

            # 3. --- INSTALL ---
            r_install = runner.invoke(app, ["install", component_to_test, "--alias", alias])
            all_passed &= must_ok("Install", r_install, contains="installed")

            # 4. --- RUN & MANAGE ---
            r_run = runner.invoke(app, ["run", alias])
            all_passed &= must_ok("Run", r_run, contains="started")

            r_ps = runner.invoke(app, ["ps"])
            all_passed &= must_ok("Check PS (running)", r_ps, contains_all=["1 running", alias])

            r_doc_ok = runner.invoke(app, ["doctor", alias])
            all_passed &= must_ok("Check Doctor (OK)", r_doc_ok, contains="ok")

            # 5. --- STOP & CLEANUP ---
            r_stop = runner.invoke(app, ["stop", alias])
            all_passed &= must_ok("Stop", r_stop, contains="stopped")

            r_ps_after = runner.invoke(app, ["ps"])
            all_passed &= must_ok("Check PS (stopped)", r_ps_after, contains="0 running")

        except Exception as e:
            print(f"\n--- A critical error occurred: {e} ---", file=sys.stderr)
            return 1
        finally:
            # --- TEARDOWN ---
            # Restore original environment variables to avoid side effects.
            if original_hub:
                os.environ["MATRIX_HUB_BASE"] = original_hub
            else:
                os.environ.pop("MATRIX_HUB_BASE", None)

            if original_home:
                os.environ["MATRIX_HOME"] = original_home
            else:
                os.environ.pop("MATRIX_HOME", None)
            print("\n--- Test Finished. Environment restored. ---")

    print("-" * 50)
    if all_passed:
        print("✅ Summary: All checks passed!")
        return 0
    else:
        print("❌ Summary: One or more checks failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
