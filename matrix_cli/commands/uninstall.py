# matrix_cli/commands/uninstall.py
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

import typer

from ..config import load_config
from ..util.console import error, info, success, warn

app = typer.Typer(
    help="Uninstall local components by alias, or remove everything with --all.",
    add_completion=False,
    no_args_is_help=False,
)

SAFE_SUBDIR = "runners"  # we only purge targets under <MATRIX_HOME>/runners by default


# ------------------------------ helpers: alias store ------------------------------ #
def _read_aliases_from_store(matrix_home: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """
    Try the SDK AliasStore API; fall back to reading ~/.matrix/aliases.json.
    Return a unified {alias: {id, target, ...}} mapping.
    """
    # Try SDK first
    try:
        if matrix_home:
            os.environ["MATRIX_HOME"] = matrix_home
        from matrix_sdk.alias import AliasStore  # type: ignore

        store = AliasStore()
        # prefer .list() -> dict[str,dict]
        for meth in ("list", "all", "items", "dump"):
            f = getattr(store, meth, None)
            if callable(f):
                data = f()
                if isinstance(data, dict):
                    return {
                        str(k): dict(v) if isinstance(v, dict) else {}
                        for k, v in data.items()
                    }
                if isinstance(data, list):
                    # Try to canonicalize: expect entries have "alias" key
                    out: Dict[str, Dict[str, Any]] = {}
                    for it in data:
                        if isinstance(it, dict):
                            a = it.get("alias") or it.get("name")
                            if a:
                                out[str(a)] = it
                    if out:
                        return out
        # If none worked, try file fallback
    except Exception:
        pass

    # Fallback file
    home = Path(matrix_home) if matrix_home else (Path.home() / ".matrix")
    jf = home / "aliases.json"
    try:
        if jf.is_file():
            data = json.loads(jf.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    str(k): dict(v) if isinstance(v, dict) else {}
                    for k, v in data.items()
                }
    except Exception:
        pass
    return {}


def _rm_alias(alias: str, matrix_home: Optional[str]) -> bool:
    """Remove an alias from the SDK store; fallback to editing the file."""
    # SDK first
    try:
        if matrix_home:
            os.environ["MATRIX_HOME"] = matrix_home
        from matrix_sdk.alias import AliasStore  # type: ignore

        store = AliasStore()
        deleter = (
            getattr(store, "rm", None)
            or getattr(store, "remove", None)
            or getattr(store, "delete", None)
        )
        if callable(deleter):
            deleter(alias)
            return True
    except Exception:
        pass

    # File fallback
    try:
        home = Path(matrix_home) if matrix_home else (Path.home() / ".matrix")
        jf = home / "aliases.json"
        if jf.is_file():
            data = json.loads(jf.read_text(encoding="utf-8"))
            if isinstance(data, dict) and alias in data:
                data.pop(alias, None)
                jf.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return True
    except Exception:
        pass
    return False


# ------------------------------ helpers: runtime ------------------------------ #
def _runtime_rows(matrix_home: Optional[str]) -> List[Dict[str, Any]]:
    """Return runtime.status() rows as dicts. [] on error."""
    try:
        if matrix_home:
            os.environ["MATRIX_HOME"] = matrix_home
        from matrix_sdk import runtime  # type: ignore
    except Exception:
        return []
    try:
        rows = runtime.status() or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            if isinstance(r, dict):
                out.append(r)
            else:
                d: Dict[str, Any] = {}
                for key in ("alias", "pid", "port", "started_at", "target", "host"):
                    d[key] = getattr(r, key, None)
                out.append(d)
        return out
    except Exception:
        return []


def _stop_if_running(alias: str, matrix_home: Optional[str]) -> bool:
    """Attempt to stop a running alias via SDK runtime. True if stopped or not running."""
    rows = _runtime_rows(matrix_home)
    running = any((rd.get("alias") == alias and rd.get("pid")) for rd in rows)
    if not running:
        return True
    # Try to stop
    try:
        if matrix_home:
            os.environ["MATRIX_HOME"] = matrix_home
        from matrix_sdk import runtime  # type: ignore

        runtime.stop(alias)
        return True
    except Exception as e:
        warn(f"Could not stop running process '{alias}': {e}")
        return False


# ------------------------------ helpers: file safety ------------------------------ #
def _is_under_safe_root(path: Path, matrix_home: Path) -> bool:
    """
    Only purge targets under <matrix_home>/runners (defensive).
    """
    try:
        p = path.expanduser().resolve()
        root = matrix_home.expanduser().resolve()
        return (root in p.parents or p == root) and (SAFE_SUBDIR in p.parts)
    except Exception:
        return False


def _purge_target(path: Path) -> Tuple[bool, str]:
    """rm -rf target directory, defensively; return (ok, reason|'')."""
    try:
        if not path.exists():
            return True, ""
        shutil.rmtree(path)
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------- CLI ---------------------------------- #
@app.command()
def main(
    aliases: Optional[List[str]] = typer.Argument(
        None,
        help="Aliases to uninstall (zero or more). Use --all to remove everything.",
    ),
    all: bool = typer.Option(
        False, "--all", help="Uninstall all aliases in the local store."
    ),
    purge: bool = typer.Option(
        False,
        "--purge",
        help=f"Also delete target files under ~/.matrix/{SAFE_SUBDIR} (safe paths only).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Do not prompt for confirmation."
    ),
    force_stop: bool = typer.Option(
        False, "--force-stop", help="Stop running processes automatically."
    ),
    stopped_only: bool = typer.Option(
        False, "--stopped-only", help="Only uninstall aliases that are not running."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show actions without performing them."
    ),
    force_files: bool = typer.Option(
        False,
        "--force-files",
        help="Allow purging targets outside the safe runners directory (DANGEROUS).",
    ),
) -> None:
    """
    Uninstall local components safely.

    Examples:
      • matrix uninstall hello-sse-server
      • matrix uninstall hello-a hello-b --purge
      • matrix uninstall --all --force-stop --purge -y
      • matrix uninstall --all --stopped-only

    Exit codes:
      0 = success
      2 = partial/unrecoverable failures
    """
    cfg = load_config()
    matrix_home = str(cfg.home) if getattr(cfg, "home", None) else None
    home_path = Path(matrix_home) if matrix_home else (Path.home() / ".matrix")

    provided_aliases = list(aliases or [])

    # Gather aliases
    store_map = _read_aliases_from_store(matrix_home)
    if not store_map:
        info("No aliases found.")
        raise typer.Exit(0)

    selection: List[str] = []
    if all:
        selection = sorted(store_map.keys())
    else:
        # Validate provided aliases
        missing: List[str] = []
        for a in provided_aliases:
            if a in store_map:
                selection.append(a)
            else:
                # Try case-insensitive match
                matches = [k for k in store_map.keys() if k.casefold() == a.casefold()]
                if matches:
                    selection.append(matches[0])
                else:
                    missing.append(a)
        if missing:
            warn(f"Unknown alias(es): {', '.join(missing)}")

    if not selection:
        info("Nothing to uninstall.")
        raise typer.Exit(0)

    # Running state
    rows = _runtime_rows(matrix_home)
    running: Set[str] = {
        rd.get("alias") for rd in rows if rd.get("alias") and rd.get("pid")
    }
    running &= set(selection)

    # Enforce stopped-only
    if stopped_only and running:
        warn(
            f"Skipping running aliases due to --stopped-only: {', '.join(sorted(running))}"
        )
        selection = [a for a in selection if a not in running]

    if not selection:
        info("Nothing to uninstall.")
        raise typer.Exit(0)

    # Build plan: what aliases and which targets (if purge)
    targets: Dict[str, Path] = {}
    for a in selection:
        ent = store_map.get(a, {})
        tgt = ent.get("target") or ent.get("path")
        if isinstance(tgt, str) and tgt.strip():
            targets[a] = Path(tgt).expanduser().resolve()
        else:
            targets[a] = Path("")  # unknown/missing

    # Confirm
    to_stop = sorted(running) if running and not stopped_only else []
    plural = "alias" if len(selection) == 1 else "aliases"
    file_note = " and delete files" if purge else ""
    info(f"Will uninstall {len(selection)} {plural}{file_note}.")
    if to_stop:
        info(f"Running: {', '.join(to_stop)}")

    if not yes and not dry_run:
        if to_stop and not force_stop:
            if not typer.confirm("Stop running processes now?"):
                error("Aborted.")
                raise typer.Exit(2)
        if not typer.confirm(
            f"Proceed to uninstall {len(selection)} {plural}{file_note}?"
        ):
            error("Aborted.")
            raise typer.Exit(2)

    # Execute
    failures = 0

    # First stop (if needed)
    for a in to_stop:
        if dry_run:
            info(f"[dry-run] Would stop '{a}'")
        else:
            ok = _stop_if_running(a, matrix_home)
            if ok:
                info(f"Stopped '{a}'")
            else:
                warn(f"Proceeding even though '{a}' may still be running.")
                # not incrementing failures; allow best-effort uninstall

    # Build reverse index to avoid deleting a target still referenced by another alias
    alias_by_target: Dict[str, List[str]] = {}
    for al, p in targets.items():
        if str(p):
            alias_by_target.setdefault(str(p), []).append(al)

    # Check if any target is still referenced by non-selected aliases
    other_refs: Dict[str, int] = {}
    for alias, ent in store_map.items():
        if alias in selection:
            continue
        tgt = ent.get("target") or ent.get("path")
        if isinstance(tgt, str) and tgt.strip():
            other_refs[str(Path(tgt).expanduser().resolve())] = (
                other_refs.get(str(Path(tgt).expanduser().resolve()), 0) + 1
            )

    # Remove aliases and purge files
    for a in selection:
        ent = store_map.get(a, {})
        tgt_path = targets.get(a, Path(""))

        # Remove alias mapping
        if dry_run:
            info(f"[dry-run] Would remove alias '{a}'")
        else:
            if _rm_alias(a, matrix_home):
                info(f"Removed alias '{a}'")
            else:
                warn(f"Could not remove alias '{a}' from store")
                failures += 1

        # Purge files if requested and safe
        if purge and str(tgt_path):
            # Skip if other aliases still reference the same target
            if other_refs.get(str(tgt_path), 0) > 0:
                warn(
                    f"Keeping files for '{a}' — target still referenced by other aliases"
                )
                continue

            # Safety check
            safe = _is_under_safe_root(tgt_path, home_path)
            if not safe and not force_files:
                warn(
                    f"Refusing to delete '{tgt_path}' (outside safe runners). Use --force-files to override."
                )
                continue

            if dry_run:
                info(f"[dry-run] Would delete '{tgt_path}'")
            else:
                ok, reason = _purge_target(tgt_path)
                if ok:
                    info(f"Deleted '{tgt_path}'")
                else:
                    warn(f"Could not delete '{tgt_path}': {reason}")
                    failures += 1

    if failures:
        error("Uninstall completed with warnings/errors.")
        raise typer.Exit(2)

    success("Uninstall complete.")
    raise typer.Exit(0)
