# matrix_cli/commands/install.py
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import typer

from ..config import load_config, client_from_config, target_for
from ..util.console import error, info, success, warn
from .resolution import resolve_fqid  # ← added

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


def _parse_id_fields(item: Dict[str, Any]) -> Tuple[str | None, str | None, str | None, str | None]:
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


def _resolve_fqid_via_search(client, cfg, raw_id: str) -> str:
    """
    Resolve a short/raw id to a fully-qualified id (ns:name@version) with minimal traffic.

    Strategy:
      • If already fqid -> return raw_id.
      • Cache hit -> return.
      • One search with (type=ns or 'mcp_server'), include_pending=True (so dev catalogs resolve offline).
      • If no candidates and ns missing -> one broadened search without type (last resort).
      • Choose best: prefer mcp_server; prefer stable; then highest version.
      • On public-hub DNS/conn failure -> try once against http://localhost:7300.
    """
    if _is_fqid(raw_id):
        return raw_id

    cached = _cache_get(cfg, raw_id)
    if cached:
        return cached

    want_ns, want_name, want_ver = _split_short_id(raw_id)

    def _search_once(cli, *, ns_hint: str | None, broaden: bool) -> List[Dict[str, Any]]:
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

                local_cli = _MC(base_url="http://localhost:7300", token=cfg.token)
                items = _search_once(local_cli, ns_hint=want_ns, broaden=False)
                warn(
                    "(offline?) couldn't reach public hub; used local dev hub at http://localhost:7300"
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


def _try_build_with_fallback(
    primary_installer, id_fq: str, *, target: str, alias: str, cfg
) -> None:
    """
    Try LocalInstaller.build(...) on the primary Hub;
    if it fails and the primary hub is not localhost, attempt a single fallback to http://localhost:7300.
    """
    from matrix_sdk.client import MatrixClient
    from matrix_sdk.installer import LocalInstaller

    # try primary hub first
    primary_installer.build(id_fq, target=target, alias=alias)
    return

    # NOTE: We only enter fallback when primary_installer.build raises (caught where called).
    # Kept for clarity — the actual try/except lives in the caller.


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
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing alias without prompting"
    ),
    no_prompt: bool = typer.Option(
        False,
        "--no-prompt",
        help=("Do not prompt on alias collisions; exit with code 3 if the alias exists"),
    ),
) -> None:
    """
    Install a component locally using the SDK's LocalInstaller.

    Exit codes:
      0  success
      3  alias collision (with --no-prompt or declined overwrite)
     10  hub/network/build/resolve error
    """
    from matrix_sdk.alias import AliasStore
    from matrix_sdk.installer import LocalInstaller
    from matrix_sdk.ids import suggest_alias
    from matrix_sdk.client import MatrixClient

    cfg = load_config()
    if hub:
        # create a new Config instance with hub override
        cfg = type(cfg)(hub_base=hub, token=cfg.token, home=cfg.home)

    # Client & installer
    client = client_from_config(cfg)
    installer = LocalInstaller(client)

    # Resolve short ids → fully-qualified ids (use new resolver; preserves old behavior otherwise)
    try:
        res = resolve_fqid(
            client, cfg, id, prefer_ns="mcp_server", allow_prerelease=False
        )
        fqid = res.fqid
        if res.note:
            warn(res.note)  # optional: informative “used local hub …” message
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
        # IMPORTANT: --no-prompt or non-tty should exit with code 3 (tests rely on this)
        if no_prompt or not sys.stdout.isatty():
            warn(msg)
            raise typer.Exit(3)
        # interactive prompt
        warn(msg)
        if not typer.confirm("Overwrite alias to point to new target?"):
            raise typer.Exit(3)

    info(f"Installing {fqid} → {target}")
    try:
        try:
            _try_build_with_fallback(
                installer, fqid, target=target, alias=alias, cfg=cfg
            )
        except Exception as e:
            # If primary build failed due to DNS/connection on public hub, try local once.
            if _is_dns_or_conn_failure(e):
                try:
                    warn(
                        "(offline?) couldn't reach public hub; trying local dev hub at http://localhost:7300"
                    )
                    fb_client = MatrixClient(
                        base_url="http://localhost:7300", token=cfg.token
                    )
                    fb_installer = LocalInstaller(fb_client)
                    fb_installer.build(fqid, target=target, alias=alias)
                except Exception:
                    raise e
            else:
                raise
    except Exception as e:
        error(f"Install failed: {e}")
        raise typer.Exit(10)

    store.set(alias, id=fqid, target=target)
    success(f"installed {fqid}")
    info(f"→ {target}")
    info(f"Next: matrix run {alias}")
