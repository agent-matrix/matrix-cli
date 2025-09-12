# matrix_cli/commands/install.py
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from urllib.parse import urlparse
import subprocess
import tempfile
import shutil
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
        return Version(str(v)).is_prerelease
    except Exception:
        return False


def _pick_best_in_bucket(cands: List[Tuple[Any, Dict[str, Any]]]) -> Dict[str, Any]:
    """Prefer stable > pre-release; within each, choose highest version."""
    if not cands:
        return {}
    stable: List[Tuple[Any, Dict[str, Any]]] = []
    pre: List[Tuple[Any, Dict[str, Any]]] = []
    for vkey, it in cands:
        pre.append((vkey, it)) if _is_prerelease(vkey) else stable.append((vkey, it))
    bucket = stable or pre
    if not bucket:
        return {}
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
    """Heuristic: detect common DNS/connection failures by message text."""
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


def _env_on(name: str) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _env_on_default_true(name: str) -> bool:
    """
    True if env var is unset or truthy; False only if explicitly disabled (0/false/no/off).
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _json_pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        try:
            return json.dumps(_to_dict(obj), indent=2, ensure_ascii=False, default=str)
        except Exception:
            return repr(obj)


def _json_preview(obj: Any, *, limit: int = 6000) -> str:
    s = _json_pretty(obj)
    return (
        s if len(s) <= limit else f"{s[:limit]}\n… (truncated {len(s) - limit} chars)"
    )


# ------------------------- Tiny on-disk resolver cache -------------------------


def _cache_path(cfg) -> Path:
    # ~/.matrix/cache/resolve.json
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
    if len(entries) > 120:
        keys_sorted = sorted(entries.items(), key=lambda kv: kv[1].get("ts", 0))
        for k, _ in keys_sorted[:40]:
            entries.pop(k, None)
    _cache_save(cfg, data)


# ------------------------- Resolver & build fallback -------------------------


def _resolve_fqid_via_search(client, cfg, raw_id: str) -> str:  # pragma: no cover
    """
    Resolve a short/raw id to a fully-qualified id (ns:name@version) with minimal traffic.
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
            "include_pending": True,
        }
        if ns_hint and not broaden:
            params["type"] = ns_hint
        elif (ns_hint is None) and (not broaden):
            params["type"] = "mcp_server"
        payload = cli.search(**params)
        return _items_from(payload)

    try:
        items = _search_once(client, ns_hint=want_ns, broaden=False)
    except Exception as e:
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

    if not best and want_ns is None:
        try:
            items2 = _search_once(client, ns_hint=None, broaden=True)
        except Exception:
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
    """Build the server-safe plan label <alias>/<version> from fqid and alias."""
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


def _summarize_outcome(outcome: Dict[str, Any]) -> Dict[str, Any]:
    plan = outcome.get("plan") if isinstance(outcome.get("plan"), dict) else {}
    lockfile = (
        outcome.get("lockfile") if isinstance(outcome.get("lockfile"), dict) else {}
    )
    prov_urls: List[str] = []
    try:
        ents = lockfile.get("entities") or []
        for e in ents:
            u = ((e or {}).get("provenance") or {}).get("source_url")
            if isinstance(u, str) and u.strip():
                prov_urls.append(u.strip())
    except Exception:
        pass
    return {
        "has_plan": bool(plan),
        "plan_keys": sorted(list(plan.keys())) if isinstance(plan, dict) else [],
        "plan_artifacts_len": (
            len(plan.get("artifacts", []) or []) if isinstance(plan, dict) else 0
        ),
        "lockfile_provenance_urls": prov_urls,
    }


def _log_outcome_preview_and_dump(outcome: Dict[str, Any], tgt_path: Path) -> None:
    if _env_on("MATRIX_SDK_VERBOSE_PLAN"):
        info("Hub outcome (preview):\n" + _json_preview(outcome, limit=6000))
    if _env_on("MATRIX_SDK_DUMP_PLAN"):
        try:
            dump = tgt_path / "_hub_outcome.json"
            dump.write_text(_json_pretty(outcome), encoding="utf-8")
            info(f"Wrote full Hub outcome → {dump}")
        except Exception as e:
            warn(f"Could not write _hub_outcome.json ({e})")


def _post_build_runner_hint(tgt_path: Path) -> None:
    """
    After building, print hints if the runner is a connector (PID=0 / no port).
    This helps users understand why `matrix run` won't expose a port.
    """
    try:
        rj = tgt_path / "runner.json"
        if not rj.is_file():
            return
        runner = json.loads(rj.read_text(encoding="utf-8"))
        rtype = (runner.get("type") or "").strip().lower()
        if rtype != "connector":
            return
        url = (runner.get("url") or "").strip()
        if url:
            info(f"Connector runner detected (no local process). URL → {url}")
            host = ""
            try:
                host = urlparse(url).hostname or ""
            except Exception:
                pass
            if host in {"127.0.0.1", "localhost"}:
                warn(
                    "This connector points to localhost. Ensure the MCP server is running at that URL. "
                    "Tip: use `matrix mcp probe --url <url>`.\n"
                    "Note: `matrix run` for connectors shows PID=0 and does not expose a port."
                )
    except Exception:
        # non-fatal
        pass


def _build_via_safe_plan(
    client,
    installer,
    fqid: str,
    *,
    target: str,
    alias: str,
    timeout: int = 900,
    runner_url: str | None = None,
    repo_url: str | None = None,
):
    """
    Perform install using a server *label* (<alias>/<version>) instead of a client absolute path.
    """
    tgt_path = Path(target).expanduser().resolve()
    _ensure_local_writable(tgt_path)

    label = _label_from_fqid_alias(fqid, alias)
    info(f"Requesting plan for {fqid} with label '{label}'")
    outcome = _to_dict(client.install(fqid, target=label))
    _log_outcome_preview_and_dump(outcome, tgt_path)

    info("Materializing plan…")
    report = installer.materialize(outcome, tgt_path)

    # Post-materialize assist (runner/repo)
    try:
        _maybe_fetch_runner_and_repo(
            tgt_path,
            report=outcome,
            runner_url=runner_url,
            repo_url=repo_url,
        )
    except Exception as e:
        warn(f"post-materialize runner/repo step failed (non-fatal): {e}")

    # Load runner + prepare env
    try:
        load = getattr(installer, "_load_runner_from_report", None)
        runner = (
            load(report, tgt_path) if callable(load) else _load_runner_direct(tgt_path)
        )
    except Exception:
        runner = _load_runner_direct(tgt_path)

    installer.prepare_env(tgt_path, runner, timeout=timeout)

    # Helpful summary & connector hint
    s = _summarize_outcome(outcome)
    info(
        f"Install summary → files={getattr(report, 'files_written', 0)} "
        f"artifacts={getattr(report, 'artifacts_fetched', 0)} "
        f"plan.artifacts={s.get('plan_artifacts_len')} "
        f"lockfile.provenance={s.get('lockfile_provenance_urls') or []}"
    )
    _post_build_runner_hint(tgt_path)
    return tgt_path


def _load_runner_direct(target_path: Path) -> Dict[str, Any]:
    p = target_path / "runner.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ------------------------- Inline manifest helpers -------------------------


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
    if src.lower().startswith("http://") or src.lower().startswith("https://"):
        with urllib.request.urlopen(src, timeout=15) as resp:  # nosec - dev provided URL
            data = resp.read().decode("utf-8")
        return json.loads(data), src
    if src.lower().startswith("file://"):
        p = Path(src[7:])
        return json.loads(p.read_text(encoding="utf-8")), str(p.as_uri())
    p = Path(src).expanduser().resolve()
    return json.loads(p.read_text(encoding="utf-8")), None


def _normalize_manifest_for_sse(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize SSE url and strip 'transport' if present (non-destructive)."""
    try:
        mcp = manifest.setdefault("mcp_registration", {})
        server = mcp.setdefault("server", {})
        url = (server.get("url") or "").strip()
        if url:
            while url.endswith("/"):
                url = url[:-1]
            if not url.endswith("/sse"):
                url = f"{url}/sse"
            server["url"] = url
        server.pop("transport", None)
    except Exception:
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
    runner_url: str | None = None,
    repo_url: str | None = None,
):
    """Install using an inline manifest via client.install_manifest when available."""
    tgt_path = Path(target).expanduser().resolve()
    _ensure_local_writable(tgt_path)

    label = _label_from_fqid_alias(fqid, alias)
    install_manifest_fn = getattr(client, "install_manifest", None)
    if not callable(install_manifest_fn):
        raise RuntimeError(
            "This matrix-sdk build does not support inline manifest installs. "
            "Please upgrade the SDK (client.install_manifest) or omit --manifest."
        )

    body_provenance = {"source_url": provenance_url} if provenance_url else None
    info(f"Sending inline manifest for {fqid} with label '{label}'")
    outcome = _to_dict(
        install_manifest_fn(
            fqid, manifest=manifest, target=label, provenance=body_provenance
        )
    )
    _log_outcome_preview_and_dump(outcome, tgt_path)

    info("Materializing inline manifest…")
    report = installer.materialize(outcome, tgt_path)

    try:
        _maybe_fetch_runner_and_repo(
            tgt_path,
            report=outcome,
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

    s = _summarize_outcome(outcome)
    info(
        f"Install summary → files={getattr(report, 'files_written', 0)} "
        f"artifacts={getattr(report, 'artifacts_fetched', 0)} "
        f"plan.artifacts={s.get('plan_artifacts_len')} "
        f"lockfile.provenance={s.get('lockfile_provenance_urls') or []}"
    )
    _post_build_runner_hint(tgt_path)
    return tgt_path


# ------------------------- Runner & repo helpers -------------------------


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
      • Else: try plan.runner_url, then ALWAYS fetch lockfile.provenance.source_url → manifest.runner.
      • If a connector runner already exists, replace it with a non-connector (python/node) runner
        from the manifest when MATRIX_CLI_PREFER_MANIFEST_RUNNER (default ON).
      • Clone repository:
          - If --repo-url provided → use that.
          - Else, if manifest.repository (or repositories[0]) exists and the runner’s entry file is missing → clone.
            Respect 'subdir'/'subdirectory'/'path' if present in the manifest repo spec.
      • Controlled by env:
          - MATRIX_CLI_PREFER_MANIFEST_RUNNER (default: 1 / ON)
          - MATRIX_CLI_AUTO_CLONE (default: 1 / ON)

    Non-fatal on failures; logs warnings.
    """
    prefer_manifest_runner = _env_on_default_true("MATRIX_CLI_PREFER_MANIFEST_RUNNER")
    auto_clone = _env_on_default_true("MATRIX_CLI_AUTO_CLONE")

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

    def _current_runner() -> Dict[str, Any]:
        try:
            return json.loads(rpath.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _first_provenance_url(rep: Dict[str, Any] | None) -> str:
        if not isinstance(rep, dict):
            return ""
        try:
            lockfile = rep.get("lockfile") or {}
            for e in lockfile.get("entities") or []:
                u = ((e or {}).get("provenance") or {}).get("source_url")
                if isinstance(u, str) and u.strip():
                    return u.strip()
        except Exception:
            pass
        return ""

    def _fetch_json(url: str, timeout: int = 20) -> Dict[str, Any]:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _manifest_repo_spec(mf: Dict[str, Any]) -> Dict[str, Any] | None:
        repo = mf.get("repository")
        if isinstance(repo, dict):
            return repo
        repos = mf.get("repositories")
        if isinstance(repos, list) and repos and isinstance(repos[0], dict):
            return repos[0]
        return None

    # 1) Strong override: --runner-url
    if (runner_url or "").strip():
        try:
            obj = _fetch_json(runner_url)
            if _valid_runner_schema(obj):
                _write_runner(obj)
            else:
                warn(
                    "--runner-url: fetched runner.json failed schema validation (ignored)"
                )
        except Exception as e:
            warn(f"--runner-url: failed to fetch runner.json ({e})")

    # 2) Plan hint (runner_url) if we still don't have a runner
    elif not rpath.exists():
        url = _plan_runner_url(report or {})
        if url:
            try:
                obj = _fetch_json(url)
                if _valid_runner_schema(obj):
                    _write_runner(obj)
                else:
                    warn(
                        "plan.runner_url: fetched runner.json failed schema validation (ignored)"
                    )
            except Exception as e:
                warn(f"plan.runner_url: failed to fetch runner.json ({e})")

    # 3) Manifest via lockfile provenance: ALWAYS try (even if a connector runner.json exists)
    manifest: Dict[str, Any] | None = None
    prov_url = _first_provenance_url(report or {})
    if prov_url:
        try:
            manifest = _fetch_json(prov_url)
        except Exception as e:
            warn(f"provenance.manifest: failed to fetch manifest ({e})")

    # If a manifest runner exists and is valid, prefer it for non-connector execution.
    if manifest:
        mf_runner = manifest.get("runner") or {}
        if mf_runner and _valid_runner_schema(mf_runner):
            cur = _current_runner()
            cur_type = (cur.get("type") or "").strip().lower()
            mf_type = (mf_runner.get("type") or "").strip().lower()
            if (not rpath.exists()) or (
                prefer_manifest_runner
                and cur_type == "connector"
                and mf_type in {"python", "node"}
            ):
                info("Using runner from manifest (writing/replacing runner.json).")
                _write_runner(mf_runner)

    # 4) Clone repository if the runner requires an entry file that isn't present.
    #    Decide URL: explicit --repo-url > manifest.repository.url/repo
    clone_from = (repo_url or "").strip()
    mf_repo_spec = None
    if not clone_from and manifest:
        mf_repo_spec = _manifest_repo_spec(manifest)
        if isinstance(mf_repo_spec, dict):
            clone_from = (
                mf_repo_spec.get("url") or mf_repo_spec.get("repo") or ""
            ).strip()

    # Determine if we need code based on the (possibly replaced) runner.json
    try:
        runner_obj = _current_runner()
    except Exception:
        runner_obj = {}

    rtype = (runner_obj.get("type") or "").strip().lower()
    entry = (runner_obj.get("entry") or "").strip()
    need_clone = bool(
        rtype in {"python", "node"} and (not entry or not (tgt_path / entry).exists())
    )

    if clone_from and (need_clone and (auto_clone or bool(repo_url))):
        try:
            with tempfile.TemporaryDirectory() as tmpd:
                # honor branch/tag ref if present in manifest repo spec
                clone_cmd = ["git", "clone", "--depth=1"]
                ref = ""
                if isinstance(mf_repo_spec, dict):
                    ref = (
                        mf_repo_spec.get("ref")
                        or mf_repo_spec.get("branch")
                        or mf_repo_spec.get("tag")
                        or ""
                    ).strip()
                if ref and ref.upper() != "HEAD":
                    clone_cmd += ["--branch", ref]
                clone_cmd += [clone_from, tmpd]
                subprocess.run(clone_cmd, check=True)

                # Respect subdir if present
                src_dir = Path(tmpd)
                if isinstance(mf_repo_spec, dict):
                    sub = (
                        mf_repo_spec.get("subdir")
                        or mf_repo_spec.get("subdirectory")
                        or mf_repo_spec.get("path")
                        or ""
                    ).strip()
                    if sub:
                        src_dir = src_dir / sub

                for p in src_dir.iterdir():
                    if p.name == ".git":
                        continue
                    dest = tgt_path / p.name
                    if p.is_dir():
                        shutil.copytree(p, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(p, dest)
            info(f"Repository cloned into {tgt_path}")
        except Exception as e:
            warn(f"repo clone: failed to clone into target ({e})")

    # 5) If repo provided a runner.json, prefer it when current runner is invalid
    if not _valid_runner_schema(_current_runner()):
        try:
            obj = _current_runner()
            if _valid_runner_schema(obj):
                info("Loaded runner from repository.")
        except Exception:
            pass


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
    Install a component locally using the SDK — with safe planning to avoid server 500s.

    New (non-breaking):
      • --manifest/--from lets you provide a manifest inline when Hub lacks source_url.
      • Resolver prefers the namespace the user typed (tool:/mcp_server:/server:), falling back to mcp_server.
      • --runner-url and --repo-url let you fetch a runner.json and optionally clone code even when the plan
        doesn't include them.

    Env toggles (default ON):
      • MATRIX_CLI_PREFER_MANIFEST_RUNNER=1  — prefer manifest runner over connector
      • MATRIX_CLI_AUTO_CLONE=1              — auto-clone repo when entry file is missing
    """
    from matrix_sdk.alias import AliasStore
    from matrix_sdk.client import MatrixClient
    from matrix_sdk.ids import suggest_alias
    from matrix_sdk.installer import LocalInstaller

    cfg = load_config()
    if hub:
        cfg = type(cfg)(hub_base=hub, token=cfg.token, home=cfg.home)

    client = client_from_config(cfg)
    installer = LocalInstaller(client)

    # Resolve short ids → fully-qualified ids (derive prefer_ns from input)
    try:
        ns_input = id.split(":", 1)[0] if ":" in id else None
        prefer_ns = ns_input or "mcp_server"
        info(f"Resolving '{id}' (prefer_ns={prefer_ns})…")
        try:
            res = resolve_fqid(
                client, cfg, id, prefer_ns=prefer_ns, allow_prerelease=False
            )
        except TypeError:
            res = resolve_fqid(client, cfg, id)
        fqid = res.fqid
        if res.note:
            warn(res.note)
        info(f"Resolved → {fqid}")
    except Exception as e:
        error(f"Could not resolve id '{id}': {e}")
        raise typer.Exit(10)

    # Alias & target
    alias = alias or suggest_alias(fqid)
    target = target or target_for(fqid, alias=alias, cfg=cfg)

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
            try:
                mf, src_url = _load_manifest_from(manifest)
                mf = _normalize_manifest_for_sse(mf)
                info(f"Loaded manifest from '{manifest}' (provenance={bool(src_url)})")
            except Exception as e:
                error(f"Failed to load manifest from '{manifest}': {e}")
                raise typer.Exit(10)

            try:
                _build_via_inline_manifest(
                    client,
                    installer,
                    fqid,
                    manifest=mf,
                    provenance_url=src_url,
                    target=target,
                    alias=alias,
                    runner_url=runner_url,
                    repo_url=repo_url,
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
                            runner_url=runner_url,
                            repo_url=repo_url,
                        )
                    except Exception:
                        raise
                else:
                    raise
        else:
            try:
                _build_via_safe_plan(
                    client,
                    installer,
                    fqid,
                    target=target,
                    alias=alias,
                    runner_url=runner_url,
                    repo_url=repo_url,
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
                            runner_url=runner_url,
                            repo_url=repo_url,
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

    # Save alias mapping to the new target
    try:
        store.set(alias, id=fqid, target=target)
    except Exception as e:
        warn(f"Install succeeded but failed to persist alias mapping: {e}")
    success(f"installed {fqid}")
    info(f"→ {target}")
    info(f"Next: matrix run {alias}")
