#!/usr/bin/env bash
# scripts/bash/poc_full_demo.sh
# End-to-end PoC:
#   - Inline install to MatrixHub (ingest/registration)
#   - Local install via Matrix CLI
#   - Run & verify (probe + mcpgateway checks)
#   - Uninstall & cleanup
#
# Requirements:
#   - bash, curl, jq
#   - matrix CLI in PATH
#   - MatrixHub reachable (HUB), and token if required (MCP_GATEWAY_TOKEN)
#
# Optional:
#   - --start-local      Clone watsonx-mcp, create venv, install deps, and start it
#   - --repo-dir <dir>   Reuse existing clone (skips re-clone)
#
# Usage (defaults shown):
#   scripts/bash/poc_full_demo.sh \
#     --hub http://127.0.0.1:443 \
#     --gw http://127.0.0.1:4444 \
#     --alias watsonx-chat \
#     --fqid mcp_server:watsonx-agent@0.1.0 \
#     --target watsonx-chat/0.1.0 \
#     --manifest-url "https://github.com/ruslanmv/watsonx-mcp/blob/master/manifests/watsonx.manifest.json?raw=1" \
#     --sse-url http://127.0.0.1:6288/sse \
#     [--start-local] [--repo-url https://github.com/ruslanmv/watsonx-mcp.git] [--repo-dir /tmp/wx-demo] [--purge]

set -Eeuo pipefail

# ---------- Defaults (override via flags or env) ----------
HUB="${HUB:-http://127.0.0.1:443}"
GW_BASE="${GW_BASE:-http://127.0.0.1:4444}"
TOKEN="${MCP_GATEWAY_TOKEN:-}"

ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
TARGET="${TARGET:-${ALIAS}/0.1.0}"

# Raw manifest URL (works via ?raw=1)
MANIFEST_URL="${MANIFEST_URL:-https://github.com/ruslanmv/watsonx-mcp/blob/master/manifests/watsonx.manifest.json?raw=1}"
SOURCE_URL="${SOURCE_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/main/manifests/watsonx.manifest.json}"
SSE_URL="${SSE_URL:-http://127.0.0.1:6288/sse}"

# Optional local server bootstrap
START_LOCAL=0
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"
REPO_DIR="${REPO_DIR:-}"   # if set, reuse; if empty, make a temp clone
PURGE=0

# ---------- Helpers ----------
step()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
info()  { printf "ℹ %s\n" "$*"; }
ok()    { printf "✅ %s\n" "$*"; }
warn()  { printf "⚠ %s\n" "$*\n" >&2; }
die()   { printf "✖ %s\n" "$*\n" >&2; exit 1; }

MASK() {
  local s="${1:-}"
  [[ -z "$s" ]] && { echo "(empty)"; return; }
  local n=${#s}
  (( n <= 6 )) && { echo "******"; return; }
  printf "%s\n" "${s:0:3}***${s:n-3:3}"
}

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --hub URL             MatrixHub base (default: ${HUB})
  --gw URL              mcpgateway base (default: ${GW_BASE})
  --token TOKEN         Hub auth token (default: \$MCP_GATEWAY_TOKEN)
  --alias NAME          Local alias (default: ${ALIAS})
  --fqid ID             Entity id to install locally (default: ${FQID})
  --target LABEL        Hub plan label (default: ${TARGET})

  --manifest-url URL    Manifest JSON URL (default: ${MANIFEST_URL})
  --source-url URL      Manifest provenance URL (default: ${SOURCE_URL})
  --sse-url URL         Expected SSE URL (default: ${SSE_URL})

  --start-local         Clone+setup+run watsonx-mcp locally (requires creds)
  --repo-url URL        Repo to clone (default: ${REPO_URL})
  --repo-dir DIR        Reuse or clone into this directory (default: temp)

  --purge               Purge files on uninstall (dangerous; off by default)
  -h, --help            Show this help
EOF
}

# ---------- Parse flags ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub) HUB="$2"; shift 2 ;;
    --gw|--gw-base) GW_BASE="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --alias) ALIAS="$2"; shift 2 ;;
    --fqid) FQID="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --manifest-url) MANIFEST_URL="$2"; shift 2 ;;
    --source-url) SOURCE_URL="$2"; shift 2 ;;
    --sse-url) SSE_URL="$2"; shift 2 ;;
    --start-local) START_LOCAL=1; shift 1 ;;
    --repo-url) REPO_URL="$2"; shift 2 ;;
    --repo-dir) REPO_DIR="$2"; shift 2 ;;
    --purge) PURGE=1; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) warn "Unknown arg: $1"; usage; exit 2 ;;
  esac
done

# ---------- Preflight ----------
command -v jq >/dev/null 2>&1 || die "jq not found"
command -v curl >/dev/null 2>&1 || die "curl not found"
command -v matrix >/dev/null 2>&1 || die "matrix CLI not found in PATH"

step "Parameters"
info "Hub:        ${HUB}"
info "Gateway:    ${GW_BASE}"
info "Alias:      ${ALIAS}"
info "FQID:       ${FQID}"
info "Target:     ${TARGET}"
info "Manifest:   ${MANIFEST_URL}"
info "SSE URL:    ${SSE_URL}"
info "Token:      $(MASK "${TOKEN}")"

# ---------- Optional: start local Watsonx MCP for the demo ----------
# We will:
#   - ensure creds exist in env or .env within repo
#   - clone repo if needed
#   - create venv & install requirements
#   - run bin/run_watsonx_mcp.py on the expected PORT
LOCAL_PID=0
LOG_FILE="/tmp/watsonx-mcp-demo.log"
CLEAN_TEMP=0

if (( START_LOCAL == 1 )); then
  step "Preparing local Watsonx MCP"

  # Require IBM creds or .env present
  if [[ -z "${WATSONX_API_KEY:-}" || -z "${WATSONX_URL:-}" || -z "${WATSONX_PROJECT_ID:-}" ]]; then
    info "No IBM creds in env; we'll look for a .env in the repo (or create from .env.example)."
  fi

  # Ensure PORT matches SSE_URL
  PORT_FROM_SSE="$(echo "${SSE_URL}" | sed -E 's#^https?://[^:]+:([0-9]+).*$#\1#' || true)"
  if [[ "${PORT_FROM_SSE:-}" =~ ^[0-9]+$ ]]; then
    export PORT="${PORT_FROM_SSE}"
  fi

  # Resolve repo directory (reuse or temp)
  if [[ -z "${REPO_DIR}" ]]; then
    REPO_DIR="$(mktemp -d /tmp/wx-mcp-XXXXXX)"
    CLEAN_TEMP=1
  fi

  if [[ ! -d "${REPO_DIR}/.git" ]]; then
    info "Cloning repo ${REPO_URL} → ${REPO_DIR}"
    git clone --depth=1 "${REPO_URL}" "${REPO_DIR}" >/dev/null 2>&1 || die "git clone failed"
  else
    info "Using existing repo at ${REPO_DIR}"
  fi

  pushd "${REPO_DIR}" >/dev/null

  # Create venv & install (best effort, fast fail if missing python)
  if command -v python3 >/dev/null 2>&1; then
    PY=python3
  else
    PY=python
  fi
  ${PY} -m venv .venv
  if [[ -f ".venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  else
    die "Failed to create venv in ${REPO_DIR}"
  fi

  pip -q install -U pip >/dev/null
  if [[ -f "requirements.txt" ]]; then
    info "Installing requirements.txt (this may take a minute)…"
    pip -q install -r requirements.txt || die "pip install failed"
  else
    info "requirements.txt not found; installing minimal deps"
    pip -q install "ibm-watsonx-ai" "fastmcp" "starlette" "uvicorn" "python-dotenv" || die "pip install failed"
  fi

  # Ensure .env exists if no env creds
  if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
      cp .env.example .env
      warn "Created .env from .env.example. Please fill IBM creds if not in env."
    else
      warn "No .env or .env.example found; relying on environment variables for IBM creds."
    fi
  fi

  # Start server
  if [[ -f "bin/run_watsonx_mcp.py" ]]; then
    step "Starting local Watsonx MCP (bin/run_watsonx_mcp.py) on PORT=${PORT:-6288}"
    set +e
    nohup python bin/run_watsonx_mcp.py > "${LOG_FILE}" 2>&1 &
    LOCAL_PID=$!
    set -e
    info "Local server PID: ${LOCAL_PID}; logs → ${LOG_FILE}"

    # Wait for a moment and do a tolerant probe
    sleep 2
    info "Attempting quick probe (3s) of ${SSE_URL}..."
    curl -s -i -N --max-time 3 "${SSE_URL}" | sed -n '1,25p' || true
  else
    warn "bin/run_watsonx_mcp.py not found in ${REPO_DIR}. Skipping local start."
  fi

  popd >/dev/null
fi

cleanup_local() {
  if (( START_LOCAL == 1 )); then
    if (( LOCAL_PID > 0 )); then
      info "Stopping local Watsonx MCP (pid=${LOCAL_PID})"
      kill "${LOCAL_PID}" 2>/dev/null || true
      sleep 1
    fi
    if (( CLEAN_TEMP == 1 )); then
      info "Removing temp clone ${REPO_DIR}"
      rm -rf "${REPO_DIR}" || true
    fi
  fi
}
trap cleanup_local EXIT

# ---------- A) Fetch & patch manifest, Inline install to MatrixHub ----------
step "Fetch & patch manifest, Inline install to MatrixHub"

TMP_MANIFEST="$(mktemp /tmp/wx-manifest-XXXXXX.json)"
curl -fsSL "${MANIFEST_URL}" -o "${TMP_MANIFEST}" || die "Failed to fetch manifest from ${MANIFEST_URL}"

PATCHED="$(jq \
  --arg sse "${SSE_URL}" '
    . as $m
    | $m
    | .mcp_registration.server.url = $sse
    | .mcp_registration.tool.request_type = "SSE"
    | if .mcp_registration.server.transport then del(.mcp_registration.server.transport) else . end
  ' "${TMP_MANIFEST}")"

PAYLOAD="$(jq -n \
  --arg id "${FQID}" \
  --arg target "${TARGET}" \
  --arg src "${SOURCE_URL}" \
  --argjson manifest "${PATCHED}" '
  { id: $id, target: $target, manifest: $manifest, provenance: { source_url: $src } }')"

HDR=(-H "Content-Type: application/json")
[[ -n "${TOKEN}" ]] && HDR+=(-H "Authorization: Bearer ${TOKEN}")

curl -sS -X POST "${HUB}/catalog/install" "${HDR[@]}" --data "${PAYLOAD}" \
  | jq -r '. | .request_id? as $id | if $id then "request_id=\($id)" else . end' || true

ok "Inline install request sent."

# ---------- B) Local install via matrix CLI ----------
step "Local install via matrix CLI"
# You can pass --hub "${HUB}" to force hub (or export MATRIX_HUB_BASE).
set +e
matrix install "${FQID}" --alias "${ALIAS}" --hub "${HUB}" --force --no-prompt
RC=$?
set -e
if (( RC != 0 )); then
  warn "matrix install exited with ${RC}. If Hub requires auth, ensure MATRIX_HUB_TOKEN is set."
  exit ${RC}
fi
ok "Installed locally as alias '${ALIAS}'."

# ---------- C) Run & verify ----------
step "Run alias '${ALIAS}'"
set +e
RUN_OUT="$(matrix run "${ALIAS}" 2>&1)"
RC=$?
set -e
if (( RC != 0 )); then
  echo "${RUN_OUT}"
  die "Run failed."
fi
echo "${RUN_OUT}" | sed -n '1,80p' | sed 's/^/   /'

# Get URL/port from ps --plain (format: alias pid port uptime_seconds url target)
step "Discover runtime details (matrix ps --plain)"
PS_LINE="$(matrix ps --plain | awk -v a="${ALIAS}" 'BEGIN{IGNORECASE=1} $1==a{print; exit}')"
if [[ -z "${PS_LINE}" ]]; then
  warn "ps did not show alias; sleeping 2s and retrying…"
  sleep 2
  PS_LINE="$(matrix ps --plain | awk -v a="${ALIAS}" 'BEGIN{IGNORECASE=1} $1==a{print; exit}')"
fi
echo "   ${PS_LINE:-<none>}"

PORT="$(echo "${PS_LINE}" | awk '{print $3}')"
URL="$(echo "${PS_LINE}" | awk '{print $5}')"
[[ -n "${URL}" ]] || URL="http://127.0.0.1:${PORT}/sse"

step "Quick probe of ${URL} (3s)"
curl -s -i -N --max-time 3 "${URL}" | sed -n '1,25p' || true
ok "Probe done (SSE often holds connection; headers/status are the signal)."

# mcpgateway verify
step "Verify in mcpgateway (${GW_BASE})"
echo "   Gateways:"
curl -s "${GW_BASE}/gateways" | jq -r \
  --arg f "${ALIAS}" \
  '[.[] | select((.name//"")|test($f;"i") or (.url//"")|test($f;"i"))] | .[] | {name,url,reachable}' || true

echo "   Tools:"
curl -s "${GW_BASE}/tools" | jq -r '.[] | {id,name,integrationType,requestType}' || true

# Optional: MCP probe via CLI if extra is present
if matrix mcp --help >/dev/null 2>&1; then
  step "MCP probe via matrix CLI"
  set +e
  matrix mcp probe --alias "${ALIAS}" --json | jq . || true
  set -e
else
  info "matrix mcp not installed (extra). Skipping CLI probe."
fi

# ---------- D) Cleanup ----------
step "Cleanup: stop & uninstall"
set +e
matrix stop "${ALIAS}" >/dev/null 2>&1 || true
if (( PURGE == 1 )); then
  matrix uninstall "${ALIAS}" --purge -y || true
else
  matrix uninstall "${ALIAS}" -y || true
fi
set -e
ok "Stopped & uninstalled alias '${ALIAS}'."

ok "🎉 PoC complete!"
echo "   - Inline installed to Hub (manifest patched to ${SSE_URL})"
echo "   - Installed locally, ran, probed"
echo "   - Verified mcpgateway"
echo "   - Cleaned up (stop/uninstall)"
