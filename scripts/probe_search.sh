#!/usr/bin/env bash
# scripts/probe_search.sh
# Quick diagnostic: Is search failure due to the server (HTTP/API) or SDK/CLI?
#
# Usage:
#   bash scripts/probe_search.sh "hello"
#   MATRIX_HUB_BASE=http://localhost:443 bash scripts/probe_search.sh "hello-sse-server"
#
# Env:
#   MATRIX_HUB_BASE   (default: https://api.matrixhub.io)
#   MATRIX_HUB_TOKEN  (optional bearer token)
#   LIMIT             (default: 5)
#   INCLUDE_PENDING   (default: 1 → true, use 0 to disable)
#
# Exit code:
#   Always 0. The script prints a diagnosis; use that in CI/logs.

set -u

Q="${1:-hello}"
HUB="${MATRIX_HUB_BASE:-https://api.matrixhub.io}"
TOKEN="${MATRIX_HUB_TOKEN:-}"
LIMIT="${LIMIT:-5}"
INCLUDE_PENDING="${INCLUDE_PENDING:-1}"
LOCAL_HUB="http://localhost:443"

# internal flags
HAS_JQ=0
HAS_MATRIX=0
HAS_PY_SDK=0

command -v jq >/dev/null 2>&1 && HAS_JQ=1
command -v matrix >/dev/null 2>&1 && HAS_MATRIX=1

# Check if Python SDK is importable (quietly)
# Note: Using python3 -c to avoid heredoc issues in some shells
if python3 -c 'import importlib; importlib.import_module("matrix_sdk.client")' >/dev/null 2>&1; then
  HAS_PY_SDK=1
fi

echo "Matrix Hub search probe"
echo "Query: '$Q'  limit=$LIMIT  include_pending=$INCLUDE_PENDING"
echo

_auth_args=()
if [[ -n "$TOKEN" ]]; then
  _auth_args=(-H "Authorization: Bearer $TOKEN")
fi

# ---- helpers ---------------------------------------------------------------
_bold() { printf "\033[1m%s\033[0m\n" "$*"; }
warn() { printf "\033[33m! %s\033[0m\n" "$*"; }
ok() { printf "\033[32m✓ %s\033[0m\n" "$*"; }

curl_json() {
  # $1=url; pass extra curl args after it
  local url="$1"; shift || true
  curl -sS -m 5 -H "Accept: application/json" "${_auth_args[@]}" "$@" "$url"
}

count_items() {
  # read JSON from stdin; print integer count of items/results (fallback 0)
  if [[ $HAS_JQ -eq 1 ]]; then
    jq -r '(.items // .results // []) | length' 2>/dev/null || echo 0
  else
    python3 -c 'import sys, json; print(len(json.load(sys.stdin).get("items", [])))' 2>/dev/null || echo 0
  fi
}

print_top_ids() {
  # read JSON from stdin; print up to n ids with summaries
  local n="${1:-4}"
  if [[ $HAS_JQ -eq 1 ]]; then
    jq -r --argjson n "$n" '(.items // .results // [])[:$n][] | .id + "  " + .summary' 2>/dev/null || true
  else
    python3 - "$n" <<'PY' 2>/dev/null || true
import sys, json
limit = int(sys.argv[1])
try:
    data = json.load(sys.stdin)
    for it in data.get("items", [])[:limit]:
        print(f"{it.get('id','?')}  {it.get('summary','')}")
except Exception:
    pass
PY
  fi
}

# ---- Liveness Check & Hub Selection ----------------------------------------
echo "== Hub Health & Selection"
echo "Probing primary hub: $HUB"
health_json="$(curl_json "$HUB/health" || true)"

if [[ -n "$health_json" ]]; then
  ok "Primary hub is alive."
  echo "Hub  : $HUB"
  echo "Token: $([[ -n "$TOKEN" ]] && echo "<set>" || echo "<none>")"
else
  warn "Primary hub unreachable. Falling back to local dev hub."
  HUB="$LOCAL_HUB"
  TOKEN="" # Unset token as it's likely invalid for a local hub
  _auth_args=() # Reset auth args
  echo "Hub  : $HUB (fallback)"
  echo "Token: <none> (fallback)"
  # Re-check health on the local hub
  health_json_local="$(curl_json "$HUB/health" || true)"
  if [[ -n "$health_json_local" ]]; then
    ok "Local fallback hub is alive."
  else
    warn "Local fallback hub is also unreachable. Most checks will fail."
  fi
fi
echo

# ---- Probes ----------------------------------------------------------------

echo "== Raw HTTP probes (bypass SDK/CLI)"
paths=(/search /v1/search /api/search /catalog/search)
raw_any_ok=0
raw_any_count=0
for p in "${paths[@]}"; do
  # GET with query params
  resp="$(curl_json "$HUB$p" -G \
        --data-urlencode "q=$Q" \
        --data-urlencode "limit=$LIMIT" \
        $([[ "$INCLUDE_PENDING" == "1" ]] && echo --data-urlencode include_pending=true) \
        || true)"
  if [[ -z "$resp" ]]; then
    printf "• GET %-20s → (no response)\n" "$p"
    continue
  fi
  c="$(printf "%s" "$resp" | count_items)"
  raw_any_ok=1
  raw_any_count=$(( raw_any_count + c ))
  printf "• GET %-20s → items=%s\n" "$p" "$c"
  if [[ "$c" -gt 0 ]]; then
    printf "%s\n" "$resp" | print_top_ids 4
  fi
done
echo

echo "== CLI probe (matrix search --json)"
cli_ok=0
cli_count=0
if [[ $HAS_MATRIX -eq 1 ]]; then
  # Prefer pending to show something when catalog is dev/empty
  cli_json="$(MATRIX_HUB_BASE="$HUB" MATRIX_HUB_TOKEN="$TOKEN" \
        matrix search "$Q" --limit "$LIMIT" --json --include-pending 2>/dev/null || true)"
  if [[ -n "$cli_json" ]]; then
    cli_ok=1
    cli_count="$(printf "%s" "$cli_json" | count_items)"
    echo "• matrix search → items=$cli_count"
  else
    echo "! matrix search → failed or empty output"
  fi
else
  echo "(matrix CLI not found in PATH — skipping)"
fi
echo

echo "== SDK probe (Python MatrixClient)"
sdk_ok=0
sdk_count=0
if [[ $HAS_PY_SDK -eq 1 ]]; then
  sdk_json="$(HUB="$HUB" TOKEN="$TOKEN" Q="$Q" LIMIT="$LIMIT" INCLUDE_PENDING="$INCLUDE_PENDING" \
    python3 - <<PY 2>/dev/null || true
import os, json
from matrix_sdk.client import MatrixClient
hub = os.environ.get("HUB")
tok = os.environ.get("TOKEN")
q = os.environ.get("Q")
limit = int(os.environ.get("LIMIT") or 5)
inc = os.environ.get("INCLUDE_PENDING") == "1"
try:
    c = MatrixClient(base_url=hub, token=tok)
    payload = c.search(q=q, limit=limit, include_pending=inc)
    try:
        dump = payload.model_dump(mode="json")  # pydantic v2
    except Exception:
        dump = payload.dict() if hasattr(payload, "dict") else dict(payload)
    print(json.dumps(dump))
except Exception:
    print("") # Fail gracefully
PY
)"
  if [[ -n "$sdk_json" ]]; then
    sdk_ok=1
    sdk_count="$(printf "%s" "$sdk_json" | count_items)"
    echo "• SDK MatrixClient.search → items=$sdk_count"
  else
    echo "! SDK MatrixClient.search → failed or empty output"
  fi
else
  echo "(Python or matrix_sdk not importable — skipping)"
fi
echo

# ---- Diagnosis -------------------------------------------------------------
echo "== Diagnosis"
if [[ $raw_any_ok -eq 1 && $raw_any_count -gt 0 ]]; then
  echo "• Server HTTP search returned items. If CLI/SDK showed 0, investigate SDK/CLI parameters or filtering."
elif [[ $raw_any_ok -eq 1 && $raw_any_count -eq 0 ]]; then
  echo "• Server HTTP search responded but with 0 items. Catalog may be empty for this query; try broader terms."
else
  echo "• Raw HTTP search endpoints did not return valid JSON. If SDK/CLI worked, they may use a different API path."
fi

if [[ $HAS_MATRIX -eq 1 ]]; then
  if [[ $cli_ok -eq 1 ]]; then
    echo "• CLI probe: $cli_count item(s)."
  else
    echo "• CLI probe failed — check env MATRIX_HUB_BASE/TOKEN and connectivity."
  fi
fi

if [[ $HAS_PY_SDK -eq 1 ]]; then
  if [[ $sdk_ok -eq 1 ]]; then
    echo "• SDK probe: $sdk_count item(s)."
  else
    echo "• SDK probe failed — verify SDK installation and hub URL."
  fi
fi

echo
echo "Done."
exit 0