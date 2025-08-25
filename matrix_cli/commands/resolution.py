# matrix_cli/commands/resolution.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# We intentionally avoid importing non-stdlib packages here.


# ===============================
# Public API
# ===============================


@dataclass
class ResolutionResult:
    """Outcome of a name→fqid resolution."""

    fqid: str
    source_hub: str
    used_local_fallback: bool = False
    broadened: bool = False
    explanation: str = ""  # full sentence(s)
    note: str = ""  # one-liner suitable for CLI warn()


def resolve_fqid(
    client,
    cfg,
    raw_id: str,
    *,
    prefer_ns: str = "mcp_server",
    allow_prerelease: bool = False,
    limit: int = 100,  # MODIFIED: Increased limit to mitigate false negatives
    negative_ttl: int = 60,
    positive_ttl: int = 300,
) -> ResolutionResult:
    """
    Resolve `raw_id` into a fully qualified id 'ns:name@version' with:
      • Zero network if already fqid or cached
      • Otherwise ONE search call (TWO only if local-fallback needed)
      • Ranking: prefer exact name + prefer_ns (mcp_server), prefer stable, then highest version
      • Deterministic, human-readable explanation and short note for CLI

    Args:
        client: Matrix SDK client (must provide .search(...) and have .base_url)
        cfg:    Config with attrs: hub_base (str), token (str), home (pathlike)
        raw_id: User-provided id or shorthand (e.g., 'hello-sse-server', 'mcp_server:hello@1.0.0')
        prefer_ns: default namespace when user omits it (UX default = 'mcp_server')
        allow_prerelease: if True, pre-release can be selected when it's the highest
        limit: search limit
        negative_ttl: seconds for negative cache entries (avoid repeated 404s)
        positive_ttl: seconds for positive cache entries

    Returns:
        ResolutionResult

    Raises:
        ValueError on inability to resolve.
    """
    # 0) If it's already a fully-qualified id, return early (no network).
    if _is_fqid(raw_id):
        return ResolutionResult(
            fqid=raw_id,
            source_hub=str(cfg.hub_base),
            explanation="Input was already a fully-qualified id.",
        )

    # 1) Parse shorthand and normalize
    want_ns, want_name, want_ver = _split_short_id(raw_id)
    if not want_name:
        raise ValueError("empty or invalid name")

    norm_name = _normalize_slug(want_name)
    want_ns = _normalize_slug(want_ns) if want_ns else None
    prefer_ns = _normalize_slug(prefer_ns) if prefer_ns else prefer_ns

    # 2) Cache checks (per hub)
    cache = _ResolverCache(cfg, positive_ttl=positive_ttl, negative_ttl=negative_ttl)
    cached = cache.get_positive(raw_id)
    if cached:
        return ResolutionResult(
            fqid=cached,
            source_hub=str(cfg.hub_base),
            explanation="Resolved from local cache.",
        )
    if cache.is_negative_fresh(raw_id):
        raise ValueError(f"could not resolve id '{raw_id}' from catalog (cached miss)")

    # 3) One broad search to find all candidates.
    #    If DNS/conn failure AND current hub looks public, try local fallback ONCE.
    used_local = False
    note = ""
    items: List[Dict[str, Any]]

    try:
        items = _search_untyped(client, norm_name, limit)
    except Exception as e:
        # Try local-dev fallback only for clear DNS/conn failures
        if _looks_like_public_hub(cfg.hub_base) and _is_dns_or_conn_failure(e):
            local_cli = _try_local_client(cfg)
            if local_cli is not None:
                try:
                    items = _search_untyped(local_cli, norm_name, limit)
                    used_local = True
                    note = "(offline) public hub unreachable; used local dev hub at http://localhost:443"
                except Exception:
                    raise
            else:
                raise
        else:
            raise

    # 4) Filter, sort, and select the best candidate, while checking for ambiguity.
    all_candidates = _get_all_sorted_candidates(
        items,
        want_ns=want_ns,
        want_name=norm_name,
        want_ver=want_ver,
        allow_prerelease=allow_prerelease,
        prefer_ns=prefer_ns,
    )

    if not all_candidates:
        cache.put_negative(raw_id)
        raise ValueError(f"could not resolve id '{raw_id}' from catalog")

    best = all_candidates[0]
    fqid = _compose_fqid(best, default_ns=want_ns or prefer_ns, forced_ver=want_ver)
    cache.put_positive(raw_id, fqid)

    # 5) Generate informational note if other candidates were found.
    if len(all_candidates) > 1:
        second_best = all_candidates[1]
        ns2, name2, _, typ2 = _parse_id_fields(second_best)
        # Use type if available, otherwise namespace for the note.
        alt_type = typ2 or ns2
        if alt_type:
            ambiguity_note = (
                f"Note: Also found a '{alt_type}' version. "
                f"To install it, run: matrix install {alt_type}:{name2}"
            )
            # MODIFIED: Append to the existing note instead of overwriting it.
            if note:
                note += f"\n{ambiguity_note}"
            else:
                note = ambiguity_note

    # Human-friendly explanation
    expl = _explain_resolution(
        raw_id=raw_id,
        fqid=fqid,
        used_local=used_local,
        broadened=False,  # Broadened is no longer a separate step.
        prefer_ns=prefer_ns,
        want_ns=want_ns,
    )

    return ResolutionResult(
        fqid=fqid,
        source_hub=("http://localhost:443" if used_local else str(cfg.hub_base)),
        used_local_fallback=used_local,
        broadened=False,  # This logic is now part of the main search.
        explanation=expl,
        note=note,
    )


# ===============================
# Helpers (no external deps)
# ===============================


def _is_fqid(s: str) -> bool:
    """Fully-qualified id looks like 'ns:name@version'."""
    return (":" in s) and ("@" in s)


def _split_short_id(raw: str) -> Tuple[Optional[str], str, Optional[str]]:
    """
    Split possibly-short id into (ns, name, version).
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


def _normalize_slug(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip().lower()
    # normalize common separators to hyphen
    out = []
    prev_hyphen = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_hyphen = False
        elif ch in (" ", "_", ".", "/"):
            if not prev_hyphen:
                out.append("-")
                prev_hyphen = True
        elif ch == "-":
            if not prev_hyphen:
                out.append("-")
                prev_hyphen = True
        # ignore others
    norm = "".join(out).strip("-")
    return norm or None


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


def _to_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")  # pydantic v2
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


def _parse_id_fields(
    item: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extract (ns, name, version, type) from a search item.
    Prefer item['id']; fallback to 'type','name','version'.
    """
    iid = item.get("id")
    typ = (item.get("type") or item.get("entity_type") or "").strip() or None
    if isinstance(iid, str) and ":" in iid and "@" in iid:
        before, ver = iid.rsplit("@", 1)
        ns, name = before.split(":", 1)
        return _normalize_slug(ns), _normalize_slug(name), ver.strip(), (typ or None)
    # fallback fields
    ns2 = _normalize_slug(item.get("namespace") or None)
    name2 = _normalize_slug(item.get("name") or None)
    ver2 = item.get("version") or None
    return ns2, name2, ver2, (typ or None)


def _version_key(s: str) -> Any:
    """
    Sort key for versions.
    Tries packaging.version.Version; falls back to tuple-of-ints/strings.
    (We avoid a hard dependency on packaging.)
    """
    try:
        # Optional import. If unavailable, the fallback below is used.
        from packaging.version import Version  # type: ignore

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


def _is_prerelease(vkey: Any) -> bool:
    """Detect pre-release when using packaging.Version; else False."""
    try:
        from packaging.version import Version  # type: ignore

        if isinstance(vkey, Version):
            return bool(vkey.is_prerelease)
        return Version(str(vkey)).is_prerelease
    except Exception:
        return False


def _get_all_sorted_candidates(
    items: List[Dict[str, Any]],
    *,
    want_ns: Optional[str],
    want_name: str,
    want_ver: Optional[str],
    allow_prerelease: bool,
    prefer_ns: str,
) -> List[Dict[str, Any]]:
    """
    Filters and sorts all matching candidates based on a deterministic ranking.
    Returns a list of candidates, with the best one at index 0.
    """
    if not items:
        return []

    candidates = []
    # First, filter to get a list of all valid candidates and attach sort keys
    for it in items:
        ns_i, name_i, ver_i, _ = _parse_id_fields(it)
        if not name_i or name_i != want_name:
            continue
        if want_ns and ns_i and ns_i != want_ns:
            continue
        if want_ver and ver_i and ver_i != want_ver:
            continue

        # MODIFIED: Use a tuple to hold the item and its key to avoid mutation
        vkey = _version_key(ver_i or "0.0.0")
        if not allow_prerelease and _is_prerelease(vkey):
            continue

        candidates.append((it, vkey))

    # MODIFIED: Apply sorts in reverse order of priority for a correct stable sort

    # 1. Sort by Version (descending)
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 2. Sort by Stability (stable first)
    candidates.sort(key=lambda x: _is_prerelease(x[1]))

    # 3. Sort by Type Priority (preferred first)
    def type_priority_key(item_tuple: Tuple[Dict[str, Any], Any]):
        item = item_tuple[0]
        ns_i, _, _, typ_i = _parse_id_fields(item)
        effective_ns = want_ns or prefer_ns
        is_preferred = (typ_i or ns_i) == effective_ns
        return 0 if is_preferred else 1

    candidates.sort(key=type_priority_key)

    # Return just the dictionary items, now correctly sorted
    return [item[0] for item in candidates]


def _compose_fqid(
    item: Dict[str, Any], *, default_ns: Optional[str], forced_ver: Optional[str]
) -> str:
    iid = item.get("id")
    if isinstance(iid, str) and ":" in iid and "@" in iid:
        return iid
    ns_i, name_i, ver_i, _ = _parse_id_fields(item)
    ns_final = default_ns or ns_i or "mcp_server"
    if not name_i:
        raise ValueError("search item missing name")
    ver_final = forced_ver or ver_i
    if not ver_final:
        raise ValueError("search item missing version")
    return f"{ns_final}:{name_i}@{ver_final}"


def _search_untyped(cli, name: str, limit: int) -> List[Dict[str, Any]]:
    payload = cli.search(q=name, limit=int(limit), include_pending=True)
    return _items_from(payload)


def _explain_resolution(
    *,
    raw_id: str,
    fqid: str,
    used_local: bool,
    broadened: bool,
    prefer_ns: Optional[str],
    want_ns: Optional[str],
) -> str:
    bits: List[str] = []
    if not _is_fqid(raw_id):
        # MODIFIED: More accurate explanation text
        ns_note = want_ns or prefer_ns or "mcp_server"
        bits.append(
            f"Resolved shorthand '{raw_id}' → '{fqid}' (ranking preference: {ns_note})."
        )
    else:
        bits.append(f"Using '{fqid}'.")
    # Broadened is no longer used, but kept for compatibility if needed.
    if broadened:
        bits.append("No typed match; broadened search without type filter.")
    if used_local:
        bits.append("Public hub unreachable; used local dev hub.")
    return " ".join(bits)


def _looks_like_public_hub(hub_base: str) -> bool:
    # Keep it lightweight: treat api.matrixhub.io as public.
    try:
        from urllib.parse import urlparse

        host = (urlparse(hub_base).hostname or "").lower()
        return host == "api.matrixhub.io"
    except Exception:
        return False


def _is_dns_or_conn_failure(err: Exception) -> bool:
    """
    Heuristic match for common DNS/connection failures (requests/urllib3/socket).
    We avoid external imports and just scan the chained exception messages.
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
    cur: Optional[Exception] = err
    for _ in range(6):
        if cur is None or cur in seen:
            break
        seen.add(cur)
        s = (str(cur) or "").lower()
        if any(n in s for n in needles):
            return True
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
    return False


def _try_local_client(cfg):
    """Best-effort to create a local hub client without hard-coding SDK imports at module import time."""
    try:
        from matrix_sdk.client import (
            MatrixClient as _MC,
        )  # local import to avoid mandatory dep at import time

        return _MC(base_url="http://localhost:443", token=cfg.token)
    except Exception:
        return None


# ===============================
# Tiny on-disk cache
# ===============================


class _ResolverCache:
    """
    Simple per-hub cache:
      file: ~/.matrix/cache/resolve.json
      {
        "hub": "<hub_base>",
        "entries": { raw_id: { "fqid": "...", "ts": 1700000000.1 } },
        "neg":     { raw_id: 1700000000.1 }  # negative cache timestamps
      }
    """

    def __init__(self, cfg, *, positive_ttl: int = 300, negative_ttl: int = 60):
        self.cfg = cfg
        self.path = _cache_path(cfg)
        self.positive_ttl = max(5, int(positive_ttl))
        self.negative_ttl = max(5, int(negative_ttl))
        self._data = self._load()

    def get_positive(self, raw: str) -> Optional[str]:
        if self._data.get("hub") != str(self.cfg.hub_base):
            return None
        ent = self._data.get("entries", {}).get(raw)
        if not ent:
            return None
        if (time.time() - float(ent.get("ts", 0))) > self.positive_ttl:
            return None
        return ent.get("fqid")

    def put_positive(self, raw: str, fqid: str) -> None:
        data = self._ensure_hub()
        entries: Dict[str, Any] = data.setdefault("entries", {})
        entries[raw] = {"fqid": fqid, "ts": time.time()}
        # prune oldest ~40 if >120 entries
        if len(entries) > 120:
            keys_sorted = sorted(entries.items(), key=lambda kv: kv[1].get("ts", 0))
            for k, _ in keys_sorted[:40]:
                entries.pop(k, None)
        self._save()

    def is_negative_fresh(self, raw: str) -> bool:
        if self._data.get("hub") != str(self.cfg.hub_base):
            return False
        ts = self._data.get("neg", {}).get(raw)
        if not ts:
            return False
        return (time.time() - float(ts)) <= self.negative_ttl

    def put_negative(self, raw: str) -> None:
        data = self._ensure_hub()
        neg: Dict[str, float] = data.setdefault("neg", {})
        neg[raw] = time.time()
        # bound size
        if len(neg) > 200:
            keys_sorted = sorted(neg.items(), key=lambda kv: kv[1])
            for k, _ in keys_sorted[:80]:
                neg.pop(k, None)
        self._save()

    # internals
    def _ensure_hub(self) -> Dict[str, Any]:
        if self._data.get("hub") != str(self.cfg.hub_base):
            self._data = {"hub": str(self.cfg.hub_base), "entries": {}, "neg": {}}
        return self._data

    def _load(self) -> Dict[str, Any]:
        try:
            p = self.path
            if p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"hub": str(self.cfg.hub_base), "entries": {}, "neg": {}}

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception:
            pass


def _cache_path(cfg) -> Path:
    # ~/.matrix/cache/resolve.json
    root = Path(cfg.home).expanduser()
    cdir = root / "cache"
    try:
        cdir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cdir / "resolve.json"
