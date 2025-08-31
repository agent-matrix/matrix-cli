# matrix_cli/commands/install.py
from __future__ import annotations

import json
import sys
import time
import urllib.request
import subprocess  # NEW: for optional git clone
import tempfile  # NEW
import shutil  # NEW
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import typer

from ..config import client_from_config, load_config, target_for
from ..util.console import error, info, success, warn
from .resolution import resolve_fqid  # existing resolver (kept)

app = typer.Typer(
    help="Install a component locally",
    add_completion=False,
    no_args_is_help=False,
)

# ------------------------- Light utils (no new deps) -------------------------


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert Pydantic v2/v1 models or dicts into plain dicts — no hard dep on pydantic."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")  # pydantic v2 preferred
        except Exception:
            try:
                return dump()
            except Exception:
                pass
    as_dict = getattr(obj, "dict", None)
    if callable(as_dict):
        try:
            return as_dict()  # pydantic v1
        except Exception:
            pass
    dump_json = getattr(obj, "model_dump_json", None)
    if callable(dump_json):
        try:
            return json.loads(dump_json())
        except Exception:
            pass
    return {}


def _items_from(payload: Any) -> List[Dict[str, Any]]:
    """Extract list of items from various payload shapes."""
    body = _to_dict(payload)
    if isinstance(body, dict):
        items = body.get("items", body.get("results", []))
        if isinstance(items, list):
            return [i if isinstance(i, dict) else _to_dict(i) for i in items]
        return []
    if isinstance(payload, list):
        return [i if isinstance(i, dict) else _to_dict(i) for i in payload]
    return []


def _is_fqid(s: str) -> bool:
    """Fully-qualified id looks like 'ns:name@version'."""
    return (":" in s) and ("@" in s)


def _split_short_id(raw: str) -> Tuple[str | None, str, str | None]:
    """
    Split a possibly-short id into (ns, name, version).

    Examples:
      'mcp_server:hello@1.0.0' -> ('mcp_server','hello','1.0.0')
      'mcp_server:hello'       -> ('mcp_server','hello',None)
      'hello@1.0.0'            -> (None,'hello','1.0.0')
      'hello'                  -> (None,'hello',None)
    """
    ns = None
    rest = raw
    if ":" in raw:
        ns, rest = raw.split(":", 1)
        ns = ns.strip() or None
    name = rest
    ver = None
    if "@" in rest:
        name, ver = rest.rsplit("@", 1)
        name = name.strip()
        ver = ver.strip() or None
    return ns, name.strip(), ver


def _parse_id_fields(
    item: Dict[str, Any],
) -> Tuple[str | None, str | None, str | None, str | None]:
    """
    Try to extract (ns, name, version, type) from a search item.
    Prefer item['id']; fallback to 'type','name','version'.
    """
    iid = item.get("id")
    typ = (item.get("type") or item.get("entity_type") or "").strip() or None
    if isinstance(iid, str) and ":" in iid and "@" in iid:
        # ns:name@version
        before, ver = iid.rsplit("@", 1)
        ns, name = before.split(":", 1)
        return ns, name, ver, typ
    # fallback fields
    ns2 = None
    name2 = item.get("name")
    ver2 = item.get("version")
    return ns2, name2, ver2, typ


def _version_key(s: str) -> Any:
    """
    Sort key for versions.
    Tries packaging.version.Version; falls back to tuple-of-ints/strings.
    """
    try:
        from packaging.version import Version

        return Version(s)
    except Exception:
        parts: List[Any] = []
        chunk = ""
        for ch in s:
            if ch.isdigit():
                if chunk and not chunk[-1].isdigit():
                    parts.append(chunk)
                    chunk = ""
                chunk += ch
            else:
                if chunk and chunk[-1].isdigit():
                    parts.append(int(chunk))
                    chunk = ""
                chunk += ch
        if chunk:
            parts.append(int(chunk) if chunk.isdigit() else chunk)
        return tuple(parts)


def _is_prerelease(v: Any) -> bool:
    """Return True if Version is pre-release when available, else False."""
    try:
        from packaging.version import Version

        if isinstance(v, Version):
            return bool(v.is_prerelease)
        # if str passed
        return Version(str(v)).is_prerelease
    except Exception:
        return False


def _pick_best_in_bucket(cands: List[Tuple[Any, Dict[str, Any]]]) -> Dict[str, Any]:
    """Prefer stable > pre-release; within each, choose highest version."""
    if not cands:
        return {}
    # stable first
    stable: List[Tuple[Any, Dict[str, Any]]] = []
    pre: List[Tuple[Any, Dict[str, Any]]] = []
    for vkey, it in cands:
        pre.append((vkey, it)) if _is_prerelease(vkey) else stable.append((vkey, it))
    bucket = stable or pre
    if not bucket:
        return {}
    # highest version (desc)
    bucket.sort(key=lambda x: x[0], reverse=True)
    return bucket[0][1]


def _choose_best_candidate(
    items: List[Dict[str, Any]],
    *,
    want_ns: str | None,
    want_name: str,
    want_ver: str | None,
) -> Dict[str, Any] | None:
    """
    Filter and pick the best match:
      • match name strictly
      • if ns is provided, require same ns
      • if version provided, require same version
      • tie-breaker: prefer type 'mcp_server', then latest (stable > pre), else any type latest
    """
    mcp: List[Tuple[Any, Dict[str, Any]]] = []
    other: List[Tuple[Any, Dict[str, Any]]] = []

    for it in items:
        ns_i, name_i, ver_i, typ_i = _parse_id_fields(it)
        if not name_i or name_i != want_name:
            continue
        if want_ns and ns_i and ns_i != want_ns:
            continue
        if want_ver and ver_i and ver_i != want_ver:
            continue
        vkey = _version_key(ver_i or "0.0.0")
        if (typ_i or "").lower() == "mcp_server":
            mcp.append((vkey, it))
        else:
            other.append((vkey, it))

    best = _pick_best_in_bucket(mcp) or _pick_best_in_bucket(other)
    return best or None


def _is_dns_or_conn_failure(err: Exception) -> bool:
    """
    Heuristic: detect common DNS/connection failures in message chain.
    Avoids importing requests/urllib3; checks text only.
    """
    needles = (
        "temporary failure in name resolution",
        "name or service not known",
        "nodename nor servname provided",
        "failed to establish a new connection",
        "connection refused",
        "connection timed out",
        "max retries exceeded with url",
    )
    seen = set()
    cur: Exception | None = err
    for _ in range(6):
        if cur is None or cur in seen:
            break
        seen.add(cur)
        s = (str(cur) or "").lower()
        if any(n in s for n in needles):
            return True
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return False


# ------------------------- Tiny on-disk resolver cache -------------------------


def _cache_path(cfg) -> Path:
    # ~/.matrix/cache/resolve.json  (portable; creates dirs as needed)
    root = Path(cfg.home).expanduser()
    cdir = root / "cache"
    try:
        cdir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cdir / "resolve.json"


def _cache_load(cfg) -> Dict[str, Any]:
    p = _cache_path(cfg)
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"hub": str(cfg.hub_base), "entries": {}}


def _cache_save(cfg, data: Dict[str, Any]) -> None:
    p = _cache_path(cfg)
    try:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cache_get(cfg, raw: str, ttl: int = 300) -> str | None:
    data = _cache_load(cfg)
    if data.get("hub") != str(cfg.hub_base):
        return None
    ent = data.get("entries", {}).get(raw)
    if not ent:
        return None
    if (time.time() - float(ent.get("ts", 0))) > max(5, ttl):
        return None
    return ent.get("fqid")


def _cache_put(cfg, raw: str, fqid: str) -> None:
    data = _cache_load(cfg)
    if data.get("hub") != str(cfg.hub_base):
        data = {"hub": str(cfg.hub_base), "entries": {}}
    entries: Dict[str, Any] = data.setdefault("entries", {})
    entries[raw] = {"fqid": fqid, "ts": time.time()}
    # keep last ~100 to bound size
    if len(entries) > 120:
        # prune oldest ~40
        keys_sorted = sorted(entries.items(), key=lambda kv: kv[1].get("ts", 0))
        for k, _ in keys_sorted[:40]:
            entries.pop(k, None)
    _cache_save(cfg, data)


# ------------------------- Resolver & build fallback -------------------------


def _resolve_fqid_via_search(client, cfg, raw_id: str) -> str:  # pragma: no cover
    """
    Resolve a short/raw id to a fully-qualified id (ns:name@version) with minimal traffic.

    Strategy:
      • If already fqid -> return raw_id.
      • Cache hit -> return.
      • One search with (type=ns or 'mcp_server'), include_pending=True (so dev catalogs resolve offline).
      • If no candidates and ns missing -> one broadened search without type (last resort).
      • Choose best: prefer type 'mcp_server', then latest (stable > pre), else any type latest.
      • On public-hub DNS/conn failure -> try once against http://localhost:443.
    """
    if _is_fqid(raw_id):
        return raw_id

    cached = _cache_get(cfg, raw_id)
    if cached:
        return cached

    want_ns, want_name, want_ver = _split_short_id(raw_id)

    def _search_once(
        cli, *, ns_hint: str | None, broaden: bool
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "q": want_name,
            "limit": 25,
            "include_pending": True,  # so dev/local catalogs work offline
        }
        # default to mcp_server if ns not provided and not broadening yet
        if ns_hint and not broaden:
            params["type"] = ns_hint
        elif (ns_hint is None) and (not broaden):
            params["type"] = "mcp_server"
        # broadened call removes type filter
        payload = cli.search(**params)
        return _items_from(payload)

    # primary call (typed or mcp_server bias)
    try:
        items = _search_once(client, ns_hint=want_ns, broaden=False)
    except Exception as e:
        # try localhost once if public hub unreachable
        if _is_dns_or_conn_failure(e):
            try:
                from matrix_sdk.client import MatrixClient as _MC

                local_cli = _MC(base_url="http://localhost:443", token=cfg.token)
                items = _search_once(local_cli, ns_hint=want_ns, broaden=False)
                warn(
                    "(offline?) couldn't reach public hub; used local dev hub at http://localhost:443"
                )
            except Exception:
                raise

        else:
            raise

    best = _choose_best_candidate(
        items, want_ns=want_ns, want_name=want_name, want_ver=want_ver
    )

    # If no candidate and ns missing, broaden (one extra query only when needed)
    if not best and want_ns is None:
        try:
            items2 = _search_once(client, ns_hint=None, broaden=True)
        except Exception:
            # ignore and leave best as None
            items2 = []
        best = _choose_best_candidate(
            items2, want_ns=want_ns, want_name=want_name, want_ver=want_ver
        )

    if not best:
        raise ValueError(f"could not resolve id '{raw_id}' from catalog")

    iid = best.get("id")
    if isinstance(iid, str) and ":" in iid and "@" in iid:
        fqid = iid
    else:
        ns_i, name_i, ver_i, _ = _parse_id_fields(best)
        ns_final = want_ns or ns_i or "mcp_server"
        ver_final = want_ver or ver_i
        if not (ns_final and name_i and ver_final):
            raise ValueError(f"could not compose fqid for '{raw_id}'")
        fqid = f"{ns_final}:{name_i}@{ver_final}"

    _cache_put(cfg, raw_id, fqid)
    return fqid


# ------------------------- Safe plan & build (no local path leak) -------------------------


def _sanitize_segment(s: str, fallback: str = "unnamed") -> str:
    s = (s or "").strip()
    if not s:
        return fallback
    out = []
    ok = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    for ch in s:
        out.append(ch if ch in ok else "_")
    cleaned = "".join(out).strip(" .")
    return cleaned or fallback


def _label_from_fqid_alias(fqid: str, alias: str) -> str:
    """
    Build the server-safe plan label <alias>/<version> from fqid and alias.
    Never include client paths; sanitize both parts to be cross-platform safe.
    """
    ver = fqid.rsplit("@", 1)[-1] if "@" in fqid else "0"
    return f"{_sanitize_segment(alias)}/{_sanitize_segment(ver)}"


def _ensure_local_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".matrix_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
    except Exception as e:
        raise PermissionError(f"Local install target not writable: {path} — {e}") from e
    finally:
        try:
            probe.unlink()
        except Exception:
            pass


def _build_via_safe_plan(
    client,
    installer,
    fqid: str,
    *,
    target: str,
    alias: str,
    timeout: int = 900,
    runner_url: str | None = None,  # NEW
    repo_url: str | None = None,  # NEW
):
    """
    Perform install using a server *label* (<alias>/<version>) instead of a client absolute path.
    Works even if the SDK installer isn't patched, because we call client.install(...) ourselves.
    """
    # 1) Ensure local target is writable before network calls
    tgt_path = Path(target).expanduser().resolve()
    _ensure_local_writable(tgt_path)

    # 2) Request plan from Hub with a safe label
    label = _label_from_fqid_alias(fqid, alias)
    outcome = client.install(fqid, target=label)  # <-- no absolute path leakage

    # 3) Materialize locally (files/artifacts/runner.json)
    report = installer.materialize(_to_dict(outcome), tgt_path)

    # 3.1) (NEW) Post-materialize: fetch runner.json and/or clone repo if needed
    try:
        _maybe_fetch_runner_and_repo(
            tgt_path,
            report=_to_dict(outcome),
            runner_url=runner_url,
            repo_url=repo_url,
        )
    except Exception as e:
        warn(f"post-materialize runner/repo step failed (non-fatal): {e}")

    # 4) Load runner and prepare env (venv/node)
    try:
        # using the SDK helper if available; fall back to reading runner.json directly
        load = getattr(installer, "_load_runner_from_report", None)
        runner = (
            load(report, tgt_path) if callable(load) else _load_runner_direct(tgt_path)
        )
    except Exception:
        runner = _load_runner_direct(tgt_path)

    installer.prepare_env(tgt_path, runner, timeout=timeout)
    return tgt_path


def _load_runner_direct(target_path: Path) -> Dict[str, Any]:
    p = target_path / "runner.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ------------------------- Inline manifest helpers (new) -------------------------


def _looks_like_url(s: str) -> bool:  # pragma: no cover
    s = (s or "").strip().lower()
    return (
        s.startswith("http://") or s.startswith("https://") or s.startswith("file://")
    )


def _load_manifest_from(source: str) -> tuple[Dict[str, Any], Optional[str]]:
    """Load a manifest from URL-like or filesystem path. Returns (manifest, source_url_for_provenance)."""
    src = (source or "").strip()
    if not src:
        raise ValueError("empty manifest source")
    # Simple loader without new deps: http(s) via urllib, file path via Path
    if src.lower().startswith("http://") or src.lower().startswith("https://"):
        # Use stdlib only
        with urllib.request.urlopen(src, timeout=10) as resp:  # nosec - user-provided dev URL
            data = resp.read().decode("utf-8")
        return json.loads(data), src
    if src.lower().startswith("file://"):
        p = Path(src[7:])
        return json.loads(p.read_text(encoding="utf-8")), str(p.as_uri())
    # treat as filesystem path
    p = Path(src).expanduser().resolve()
    return json.loads(p.read_text(encoding="utf-8")), None


def _normalize_manifest_for_sse(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Force .mcp_registration.server.url → /sse and remove 'transport' (non-destructive for other fields)."""
    try:
        mcp = manifest.setdefault("mcp_registration", {})
        server = mcp.setdefault("server", {})
        url = (server.get("url") or "").strip()
        if url:
            # strip trailing slashes then ensure exactly one '/sse'
            while url.endswith("/"):
                url = url[:-1]
            if not url.endswith("/sse"):
                url = f"{url}/sse"
            server["url"] = url
        # drop transport if present (prevents /messages/ rewrites downstream)
        if "transport" in server:
            server.pop("transport", None)
    except Exception:
        # do not fail install on normalization; leave manifest unchanged
        pass
    return manifest


def _build_via_inline_manifest(
    client,
    installer,
    fqid: str,
    *,
    manifest: Dict[str, Any],
    provenance_url: Optional[str],
    target: str,
    alias: str,
    timeout: int = 900,
    runner_url: str | None = None,  # NEW
    repo_url: str | None = None,  # NEW
):
    """Install using an inline manifest via client.install_manifest (non-destructive fallback if unavailable)."""
    tgt_path = Path(target).expanduser().resolve()
    _ensure_local_writable(tgt_path)

    # send label instead of absolute path
    label = _label_from_fqid_alias(fqid, alias)

    # Duck-typed feature: prefer client.install_manifest if present
    install_manifest_fn = getattr(client, "install_manifest", None)
    if not callable(install_manifest_fn):
        raise RuntimeError(
            "This matrix-sdk build does not support inline manifest installs. "
            "Please upgrade the SDK (client.install_manifest) or omit --manifest."
        )

    body_provenance = {"source_url": provenance_url} if provenance_url else None
    outcome = install_manifest_fn(
        fqid, manifest=manifest, target=label, provenance=body_provenance
    )

    report = installer.materialize(_to_dict(outcome), tgt_path)

    # (NEW) Post-materialize: fetch runner.json and/or clone repo if needed
    try:
        _maybe_fetch_runner_and_repo(
            tgt_path,
            report=_to_dict(outcome),
            runner_url=runner_url,
            repo_url=repo_url,
        )
    except Exception as e:
        warn(f"post-materialize runner/repo step failed (non-fatal): {e}")

    try:
        load = getattr(installer, "_load_runner_from_report", None)
        runner = (
            load(report, tgt_path) if callable(load) else _load_runner_direct(tgt_path)
        )
    except Exception:
        runner = _load_runner_direct(tgt_path)

    installer.prepare_env(tgt_path, runner, timeout=timeout)
    return tgt_path


# ------------------------- Runner & repo helpers (NEW) -------------------------


def _valid_runner_schema(obj: Dict[str, Any]) -> bool:
    t = (obj.get("type") or "").strip().lower()
    if t == "connector":
        return bool((obj.get("url") or "").strip())
    if t in {"python", "node"}:
        return bool((obj.get("entry") or "").strip())
    return False


def _plan_runner_url(report_or_outcome: Dict[str, Any]) -> str:
    try:
        plan = report_or_outcome.get("plan", report_or_outcome) or {}
        return (plan.get("runner_url") or "").strip()
    except Exception:
        return ""


def _maybe_fetch_runner_and_repo(
    tgt_path: Path,
    *,
    report: Dict[str, Any] | None,
    runner_url: str | None,
    repo_url: str | None,
) -> None:
    """
    Make installs 'just work' when Hub doesn't provide artifacts:
      • If --runner-url is provided: ALWAYS fetch into runner.json (backup if exists).
      • Else if no runner.json and plan.runner_url exists: fetch it.
      • If --repo-url is provided and the runner points to a missing entry file:
         clone the repo into the target (excluding .git).
    Non-fatal on failures; logs warnings.
    """
    tgt_path.mkdir(parents=True, exist_ok=True)
    rpath = tgt_path / "runner.json"

    def _write_runner(obj: Dict[str, Any]) -> None:
        if rpath.exists():
            backup = rpath.with_suffix(rpath.suffix + f".bak.{int(time.time())}")
            try:
                shutil.copy2(rpath, backup)
                warn(f"runner.json existed; backed up to {backup.name}")
            except Exception:
                pass
        rpath.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        info(f"runner.json written → {rpath}")

    # 1) Fetch runner from CLI flag (strong override)
    if (runner_url or "").strip():
        try:
            with urllib.request.urlopen(runner_url, timeout=15) as resp:
                data = resp.read().decode("utf-8")
            obj = json.loads(data)
            if _valid_runner_schema(obj):
                _write_runner(obj)
            else:
                warn(
                    "--runner-url: fetched runner.json failed schema validation (ignored)"
                )
        except Exception as e:
            warn(f"--runner-url: failed to fetch runner.json ({e})")

    # 2) Else if no runner.json and plan provided a runner_url
    elif not rpath.exists():
        url = _plan_runner_url(report or {})
        if url:
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read().decode("utf-8")
                obj = json.loads(data)
                if _valid_runner_schema(obj):
                    _write_runner(obj)
                else:
                    warn(
                        "plan.runner_url: fetched runner.json failed schema validation (ignored)"
                    )
            except Exception as e:
                warn(f"plan.runner_url: failed to fetch runner.json ({e})")

    # 3) Optionally clone repo if needed and asked for
    if (repo_url or "").strip():
        need_clone = False
        try:
            obj = json.loads(rpath.read_text(encoding="utf-8"))
        except Exception:
            obj = {}

        t = (obj.get("type") or "").strip().lower()
        if t == "python":
            entry = (obj.get("entry") or "").strip()
            if not entry:
                need_clone = True
            else:
                if not (tgt_path / entry).exists():
                    need_clone = True
        elif t == "node":
            entry = (obj.get("entry") or "").strip()
            if not entry or not (tgt_path / entry).exists():
                need_clone = True
        else:
            # no runner or connector: if user asked to clone, allow it
            need_clone = True

        if need_clone:
            try:
                with tempfile.TemporaryDirectory() as tmpd:
                    subprocess.run(
                        ["git", "clone", "--depth=1", repo_url, tmpd], check=True
                    )
                    # copy into target (excluding .git)
                    for p in Path(tmpd).iterdir():
                        if p.name == ".git":
                            continue
                        dest = tgt_path / p.name
                        if p.is_dir():
                            shutil.copytree(p, dest, dirs_exist_ok=True)
                        else:
                            shutil.copy2(p, dest)
                info(f"Repository cloned into {tgt_path}")
            except Exception as e:
                warn(f"--repo-url: failed to clone into target ({e})")


# ----------------------------------- CLI -----------------------------------


@app.command()
def main(
    id: str = typer.Argument(
        ...,
        help=(
            "ID or name. Examples: mcp_server:name@1.2.3 | mcp_server:name | name@1.2.3 | name"
        ),
    ),
    alias: str | None = typer.Option(
        None, "--alias", "-a", help="Friendly name for the component"
    ),
    target: str | None = typer.Option(
        None, "--target", "-t", help="Specific directory to install into"
    ),
    hub: str | None = typer.Option(
        None, "--hub", help="Override Hub base URL for this command"
    ),
    manifest: str | None = typer.Option(
        None,
        "--manifest",
        "--from",
        help=(
            "Manifest path or URL to install inline (bypasses Hub source_url fetch). "
            "Accepted: http(s)://, file://, or filesystem path."
        ),
    ),
    # NEW — works now, no Hub change required
    runner_url: str | None = typer.Option(
        None,
        "--runner-url",
        help="URL to a runner.json to write into the target when none is provided by the plan.",
    ),
    repo_url: str | None = typer.Option(
        None,
        "--repo-url",
        help="Optional repository to clone into the target when the plan has no artifacts or files are missing.",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing alias without prompting"
    ),
    no_prompt: bool = typer.Option(
        False,
        "--no-prompt",
        help=(
            "Do not prompt on alias collisions; exit with code 3 if the alias exists"
        ),
    ),
) -> None:
    """
    Install a component locally using the SDK — with safe planning to avoid server 500s
    caused by leaking client absolute paths to the Hub.

    New (non-breaking):
      • --manifest/--from lets you provide a manifest inline when Hub lacks source_url.
      • Resolver prefers the namespace the user typed (tool:/mcp_server:/server:),
        falling back to mcp_server.
      • --runner-url and --repo-url let you fetch a runner.json and optionally clone code
        even when the Hub plan doesn't include them (works today, no Hub change required).

    Exit codes:
      0  success
      3  alias collision (with --no-prompt or declined overwrite)
      10 hub/network/build/resolve error
    """
    from matrix_sdk.alias import AliasStore
    from matrix_sdk.client import MatrixClient
    from matrix_sdk.ids import suggest_alias
    from matrix_sdk.installer import LocalInstaller

    cfg = load_config()
    if hub:
        # create a new Config instance with hub override
        cfg = type(cfg)(hub_base=hub, token=cfg.token, home=cfg.home)

    # Client & installer
    client = client_from_config(cfg)
    installer = LocalInstaller(client)

    # Resolve short ids → fully-qualified ids (derive prefer_ns from input)
    try:
        ns_input = id.split(":", 1)[0] if ":" in id else None
        prefer_ns = ns_input or "mcp_server"
        try:
            res = resolve_fqid(
                client, cfg, id, prefer_ns=prefer_ns, allow_prerelease=False
            )
        except TypeError:
            # fallback for older CLIs where resolver lacks kwargs
            res = resolve_fqid(client, cfg, id)
        fqid = res.fqid
        if res.note:
            warn(res.note)
    except Exception as e:
        error(f"Could not resolve id '{id}': {e}")
        raise typer.Exit(10)

    # Alias & target
    alias = alias or suggest_alias(fqid)
    target = target or target_for(fqid, alias=alias, cfg=cfg)

    # alias collision handling (unchanged)
    store = AliasStore()
    existing = store.get(alias)
    if existing and not force:
        msg = f"Alias '{alias}' already exists → {existing.get('target')}"
        if no_prompt or not sys.stdout.isatty():
            warn(msg)
            raise typer.Exit(3)
        warn(msg)
        if not typer.confirm("Overwrite alias to point to new target?"):
            raise typer.Exit(3)

    info(f"Installing {fqid} → {target}")

    # Primary path: inline manifest when provided; else default safe-plan path
    try:
        if manifest:
            # Load + normalize + install inline
            try:
                mf, src_url = _load_manifest_from(manifest)
                mf = _normalize_manifest_for_sse(mf)
            except Exception as e:
                error(f"Failed to load manifest from '{manifest}': {e}")
                raise typer.Exit(10)

            # Try primary hub, then fallback to localhost:443 on DNS/conn error
            try:
                _build_via_inline_manifest(
                    client,
                    installer,
                    fqid,
                    manifest=mf,
                    provenance_url=src_url,
                    target=target,
                    alias=alias,
                    runner_url=runner_url,  # NEW
                    repo_url=repo_url,  # NEW
                )
            except Exception as e:
                if _is_dns_or_conn_failure(e):
                    try:
                        warn(
                            "(offline?) couldn't reach public hub; trying local dev hub at http://localhost:443"
                        )
                        fb_client = MatrixClient(
                            base_url="http://localhost:443", token=cfg.token
                        )
                        fb_installer = LocalInstaller(fb_client)
                        _build_via_inline_manifest(
                            fb_client,
                            fb_installer,
                            fqid,
                            manifest=mf,
                            provenance_url=src_url,
                            target=target,
                            alias=alias,
                            runner_url=runner_url,  # NEW
                            repo_url=repo_url,  # NEW
                        )
                    except Exception:
                        raise
                else:
                    raise
        else:
            # legacy/default path — requires Hub to have a source_url recorded
            try:
                _build_via_safe_plan(
                    client,
                    installer,
                    fqid,
                    target=target,
                    alias=alias,
                    runner_url=runner_url,  # NEW
                    repo_url=repo_url,  # NEW
                )
            except Exception as e:
                if _is_dns_or_conn_failure(e):
                    try:
                        warn(
                            "(offline?) couldn't reach public hub; trying local dev hub at http://localhost:443"
                        )
                        fb_client = MatrixClient(
                            base_url="http://localhost:443", token=cfg.token
                        )
                        fb_installer = LocalInstaller(fb_client)
                        _build_via_safe_plan(
                            fb_client,
                            fb_installer,
                            fqid,
                            target=target,
                            alias=alias,
                            runner_url=runner_url,  # NEW
                            repo_url=repo_url,  # NEW
                        )
                    except Exception:
                        raise
                else:
                    raise
    except Exception as e:
        # Helpful hint for the common 422 source_url failure
        s = (str(e) or "").lower()
        if ("source_url" in s and "missing" in s) or (
            "unable to load manifest" in s and "source_url" in s
        ):
            warn(
                "Hub could not fetch a manifest for this id (no source_url). "
                "Provide one with --manifest <path-or-url> to install inline."
            )
        error(f"Install failed: {e}")
        raise typer.Exit(10)

    store.set(alias, id=fqid, target=target)
    success(f"installed {fqid}")
    info(f"→ {target}")
    info(f"Next: matrix run {alias}")
