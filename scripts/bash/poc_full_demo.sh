#!/usr/bin/env bash
# scripts/bash/poc_full_demo.sh
# Professional PoC: connector-first flow (no local process), robust, idempotent.
# - Writes/updates a connector runner that points to the desired SSE URL.
# - Starts the alias (records URL in a lock; pid=0) and probes before any MCP calls.
# - Optional Hub/Gateway registration steps are disabled by default (set flags to 1).
#
# Usage (most common):
#   scripts/bash/poc_full_demo.sh
#
# Override defaults:
#   SSE_URL=http://127.0.0.1:6289/sse ./scripts/bash/poc_full_demo.sh
#   START_LOCAL=1 ./scripts/bash/poc_full_demo.sh        # also boot local server (optional)
#   DO_HUB_INSTALL=1 REGISTER_GATEWAY=1 ./scripts/bash/poc_full_demo.sh
#
set -Eeuo pipefail

# -----------------------------------------------
# Optional .env loader (safe/no-op if absent)
# -----------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
find_env_up() {
  local d="$1"
  while [[ -n "$d" && "$d" != "/" && "$d" != "." ]]; do
    [[ -f "$d/.env" ]] && { echo "$d/.env"; return 0; }
    d="$(dirname "$d")"
  done
  return 1
}
ENV_FILE="${ENV_FILE:-"$(find_env_up "$SCRIPT_DIR" || true)"}"
if [[ -n "${ENV_FILE:-}" && -f "$ENV_FILE" ]]; then
  echo "ℹ Loading .env from $ENV_FILE"
  # shellcheck disable=SC1090
  set +u; set -a; source "$ENV_FILE"; set +a; set -u
fi

# -----------------------------------------------
# Defaults (Option A: connector runner; port 6289)
# -----------------------------------------------
HUB="${HUB:-http://127.0.0.1:443}"
HUB_TOKEN="${HUB_TOKEN:-${MATRIX_HUB_TOKEN:-}}"

GW_BASE="${GW_BASE:-http://127.0.0.1:4444}"
GW_TOKEN="${GW_TOKEN:-${MCP_GATEWAY_TOKEN:-}}"

ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
TARGET="${TARGET:-${ALIAS}/0.1.0}"

# IMPORTANT: default to 6289 per “Option A”
SSE_URL="${SSE_URL:-http://127.0.0.1:6289/sse}"

MANIFEST_URL="${MANIFEST_URL:-https://github.com/ruslanmv/watsonx-mcp/blob/master/manifests/watsonx.manifest.json?raw=1}"
SOURCE_URL="${SOURCE_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/main/manifests/watsonx.manifest.json}"

# Optional toggles (off by default to keep PoC noise-free)
DO_HUB_INSTALL="${DO_HUB_INSTALL:-0}"       # 1 → send inline install to Hub
REGISTER_GATEWAY="${REGISTER_GATEWAY:-0}"   # 1 → register tool/gateway in mcpgateway

# Optional: auto-start local server (clones and runs repo). Off by default.
START_LOCAL="${START_LOCAL:-0}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"
REPO_DIR="${REPO_DIR:-}"
PURGE="${PURGE:-0}"

# -----------------------------------------------
# Pretty helpers
# -----------------------------------------------
GREEN="\033[0;32m"; BLUE="\033[1;34m"; CYAN="\033[1;36m"; NC="\033[0m"
show_cmd() { printf "${GREEN}$ %s${NC}\n" "$*"; }
step()  { printf "\n${CYAN}▶ %s${NC}\n" "$*"; }
info()  { printf "ℹ %s\n" "$*"; }
ok()    { printf "✅ %s\n" "$*"; }
warn()  { printf "⚠ %s\n" "$*\n" >&2; }
die()   { printf "✖ %s\n" "$*\n" >&2; exit 1; }
MASK(){ local s="${1:-}"; [[ -z "$s" ]]&&{ echo "(empty)";return; }; local n=${#s}; ((n<=6))&&{ echo "******";return; }; printf "%s\n" "${s:0:3}***${s:n-3:3}"; }

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]
  --hub URL             MatrixHub base (default: ${HUB})
  --hub-token TOKEN     Hub API token (default: \$HUB_TOKEN / \$MATRIX_HUB_TOKEN)
  --gw URL              mcpgateway base (default: ${GW_BASE})
  --gw-token TOKEN      mcpgateway token (default: \$GW_TOKEN / \$MCP_GATEWAY_TOKEN)
  --alias NAME          Local alias (default: ${ALIAS})
  --fqid ID             Entity id (default: ${FQID})
  --target LABEL        Lock label (default: ${TARGET})
  --manifest-url URL    Manifest JSON URL (default: ${MANIFEST_URL})
  --source-url URL      Provenance URL (default: ${SOURCE_URL})
  --sse-url URL         SSE URL (default: ${SSE_URL})
  --start-local         Clone+run watsonx-mcp locally (optional)
  --repo-url URL        Repo to clone (default: ${REPO_URL})
  --repo-dir DIR        Reuse or clone here (default: temp)
  --purge               Purge files on uninstall
  -h, --help            Show help

Env flags (optional):
  DO_HUB_INSTALL=1      Also send inline manifest install to Hub
  REGISTER_GATEWAY=1    Register tool/gateway in mcpgateway
EOF
}

# -----------------------------------------------
# Arg parsing
# -----------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub) HUB="$2"; shift 2;;
    --hub-token) HUB_TOKEN="$2"; shift 2;;
    --gw|--gw-base) GW_BASE="$2"; shift 2;;
    --gw-token) GW_TOKEN="$2"; shift 2;;
    --alias) ALIAS="$2"; shift 2;;
    --fqid) FQID="$2"; shift 2;;
    --target) TARGET="$2"; shift 2;;
    --manifest-url) MANIFEST_URL="$2"; shift 2;;
    --source-url) SOURCE_URL="$2"; shift 2;;
    --sse-url) SSE_URL="$2"; shift 2;;
    --start-local) START_LOCAL=1; shift;;
    --repo-url) REPO_URL="$2"; shift 2;;
    --repo-dir) REPO_DIR="$2"; shift 2;;
    --purge) PURGE=1; shift;;
    -h|--help) usage; exit 0;;
    *) warn "Unknown arg: $1"; usage; exit 2;;
  esac
done

command -v jq >/dev/null 2>&1 || die "jq not found"
command -v curl >/dev/null 2>&1 || die "curl not found"
command -v matrix >/dev/null 2>&1 || die "matrix CLI not found"

step "Parameters"
info "Hub:         ${HUB}"
info "Hub Token:   $(MASK "${HUB_TOKEN}")"
info "Gateway:     ${GW_BASE}"
info "GW Token:    $(MASK "${GW_TOKEN}")"
info "Alias:       ${ALIAS}"
info "FQID:        ${FQID}"
info "Target:      ${TARGET}"
info "Manifest:    ${MANIFEST_URL}"
info "SSE URL:     ${SSE_URL}"

# -----------------------------------------------
# Optional: start local server (dev convenience)
# -----------------------------------------------
LOCAL_PID=0; LOG_FILE="/tmp/wx-mcp-demo.log"; CLEAN_TEMP=0
if (( START_LOCAL == 1 )); then
  step "Starting local watsonx MCP"
  PORT_FROM_SSE="$(echo "${SSE_URL}" | sed -E 's#^https?://[^:]+:([0-9]+).*$#\1#' || true)"
  [[ "${PORT_FROM_SSE:-}" =~ ^[0-9]+$ ]] && export PORT="${PORT_FROM_SSE}"
  if [[ -z "${REPO_DIR}" ]]; then REPO_DIR="$(mktemp -d /tmp/wx-mcp-XXXXXX)"; CLEAN_TEMP=1; fi
  if [[ ! -d "${REPO_DIR}/.git" ]]; then
    show_cmd "git clone --depth=1 \"${REPO_URL}\" \"${REPO_DIR}\""
    git clone --depth=1 "${REPO_URL}" "${REPO_DIR}" >/dev/null 2>&1 || die "git clone failed"
  else
    info "Using existing repo at ${REPO_DIR}"
  fi
  show_cmd "pushd \"${REPO_DIR}\""
  pushd "${REPO_DIR}" >/dev/null

  PY="$(command -v python3 || command -v python || true)"; [[ -z "$PY" ]] && die "python missing"
  show_cmd "${PY} -m venv .venv && source .venv/bin/activate"
  $PY -m venv .venv; source .venv/bin/activate || die "venv fail"

  show_cmd "pip install -U pip"
  pip -q install -U pip >/dev/null
  if [[ -f requirements.txt ]]; then
    show_cmd "pip install -r requirements.txt"
    pip -q install -r requirements.txt || die "pip install failed"
  else
    show_cmd "pip install ibm-watsonx-ai fastmcp starlette uvicorn python-dotenv"
    pip -q install ibm-watsonx-ai fastmcp starlette uvicorn python-dotenv || die "pip install failed"
  fi

  if [[ -f "bin/run_watsonx_mcp.py" ]]; then CMD="python bin/run_watsonx_mcp.py"; else CMD="python -m watsonx_mcp.app"; fi
  show_cmd "nohup ${CMD} > ${LOG_FILE} 2>&1 &"
  nohup ${CMD} > "${LOG_FILE}" 2>&1 & LOCAL_PID=$!

  show_cmd "popd"
  popd >/dev/null
  info "PID=${LOCAL_PID}, logs: ${LOG_FILE}"
  # give uvicorn a moment
  sleep 2
  show_cmd "curl -sI --max-time 3 \"${SSE_URL}\""
  curl -sI --max-time 3 "${SSE_URL}" | sed -n '1,2p' || true
fi

cleanup_local(){
  if (( START_LOCAL==1 && LOCAL_PID>0 )); then
    show_cmd "kill ${LOCAL_PID}"
    kill "${LOCAL_PID}" 2>/dev/null || true
  fi
  if (( CLEAN_TEMP==1 )); then
    show_cmd "rm -rf \"${REPO_DIR}\""
    rm -rf "${REPO_DIR}" || true
  fi
}
trap cleanup_local EXIT

# -----------------------------------------------
# (Optional) A) Inline install → MatrixHub
# -----------------------------------------------
if (( DO_HUB_INSTALL == 1 )); then
  step "Inline install → MatrixHub"
  TMP_MANIFEST="$(mktemp /tmp/wx-manifest-XXXX.json)"
  show_cmd "curl -fsSL \"${MANIFEST_URL}\" -o \"${TMP_MANIFEST}\""
  curl -fsSL "${MANIFEST_URL}" -o "${TMP_MANIFEST}" || die "fetch manifest failed"

  PATCHED="$(jq --arg sse "${SSE_URL}" '
    . as $m
    | .mcp_registration.server.url = $sse
    | if .mcp_registration.tool then .mcp_registration.tool.request_type = "SSE" else . end
    | del(.mcp_registration.server.transport)
  ' "${TMP_MANIFEST}")"

  PAYLOAD="$(jq -n --arg id "${FQID}" --arg target "${TARGET}" --arg src "${SOURCE_URL}" --argjson manifest "${PATCHED}" \
    '{id:$id, target:$target, manifest:$manifest, provenance:{source_url:$src}}')"

  HDR=(-H "Content-Type: application/json")
  [[ -n "${HUB_TOKEN}" ]] && HDR+=(-H "Authorization: Bearer ${HUB_TOKEN}")
  # Preview command with masked token
  PREVIEW="curl -sS -X POST \"${HUB}/catalog/install\" -H \"Content-Type: application/json\""
  [[ -n "${HUB_TOKEN}" ]] && PREVIEW="${PREVIEW} -H \"Authorization: Bearer $(MASK "${HUB_TOKEN}")\""
  PREVIEW="${PREVIEW} --data '<payload>' | jq ."
  show_cmd "${PREVIEW}"
  curl -sS -X POST "${HUB}/catalog/install" "${HDR[@]}" --data "${PAYLOAD}" | jq . || true
  ok "Install request sent."
fi

# -----------------------------------------------
# B) Local install via matrix CLI (idempotent)
# -----------------------------------------------
step "Local install via matrix CLI"
show_cmd "matrix install \"${FQID}\" --alias \"${ALIAS}\" --hub \"${HUB}\" --force --no-prompt"
set +e; matrix install "${FQID}" --alias "${ALIAS}" --hub "${HUB}" --force --no-prompt; RC=$?; set -e
(( RC == 0 )) || die "matrix install failed (${RC})"
ok "Installed locally as '${ALIAS}'."

# -----------------------------------------------
# B.1) Ensure/Update connector runner (Option A)
# Always update runner.json to point to SSE_URL (backup if exists).
# -----------------------------------------------
VERSION="${TARGET#*/}"
RUN_DIR="${HOME}/.matrix/runners/${ALIAS}/${VERSION}"
RUNNER_PATH="${RUN_DIR}/runner.json"
show_cmd "mkdir -p \"${RUN_DIR}\""
mkdir -p "${RUN_DIR}"

if [[ -f "${RUNNER_PATH}" ]]; then
  TS="$(date +%Y%m%d-%H%M%S)"
  cp -f "${RUNNER_PATH}" "${RUNNER_PATH}.bak.${TS}" || true
  info "Backed up existing runner.json → ${RUNNER_PATH}.bak.${TS}"
fi

cat > "${RUNNER_PATH}" <<JSON
{
  "type": "connector",
  "name": "${ALIAS}",
  "description": "Connector to Watsonx MCP over SSE",
  "integration_type": "MCP",
  "request_type": "SSE",
  "url": "${SSE_URL}",
  "endpoint": "/sse",
  "headers": {}
}
JSON
ok "connector runner.json written at ${RUNNER_PATH}"

# -----------------------------------------------
# C) Run alias (pre-run unlock fix) & determine URL
# -----------------------------------------------
step "Run alias '${ALIAS}'"

# PRE-RUN: ensure no running/stale lock
LOCK_DIR="${HOME}/.matrix/state/${ALIAS}"
LOCK_FILE="${LOCK_DIR}/runner.lock.json"
if matrix ps --json | jq -e --arg a "${ALIAS,,}" '.[] | select((.alias // "" | ascii_downcase) == $a)' >/dev/null; then
  info "Alias '${ALIAS}' appears active or locked — stopping before run..."
  matrix stop "${ALIAS}" >/dev/null 2>&1 || true
fi
if [[ -f "${LOCK_FILE}" ]]; then
  warn "Removing stale lock file: ${LOCK_FILE}"
  rm -f "${LOCK_FILE}" || true
fi

attempt_run() { matrix run "${ALIAS}"; }

show_cmd "matrix run \"${ALIAS}\""
set +e
RUN_OUT="$(attempt_run 2>&1)"; RC=$?
if (( RC != 0 )) && echo "${RUN_OUT}" | grep -qi "Lock file already exists for alias"; then
  warn "Run failed due to existing lock; removing lock and retrying once…"
  rm -f "${LOCK_FILE}" || true
  sleep 0.2
  RUN_OUT="$(attempt_run 2>&1)"; RC=$?
fi
set -e
(( RC == 0 )) || { echo "${RUN_OUT}"; die "Run failed."; }
echo "${RUN_OUT}" | sed -n '1,120p' | sed 's/^/   /'

# Discover URL from ps --json (prefer), else fallback to SSE_URL
ps_json="$(matrix ps --json || echo '[]')"
URL="$(jq -r --arg a "${ALIAS,,}" '.[] | select((.alias // "" | ascii_downcase) == $a) | .url // empty' <<<"$ps_json" | head -n1 || true)"
if [[ -z "${URL}" || "${URL}" == "-" || "${URL}" == "—" || "${URL}" == "N/A" ]]; then
  PORT="$(jq -r --arg a "${ALIAS,,}" '.[] | select((.alias // "" | ascii_downcase) == $a) | .port // empty' <<<"$ps_json" | head -n1 || true)"
  if [[ -n "${PORT}" && "${PORT}" =~ ^[0-9]+$ ]]; then
    URL="http://127.0.0.1:${PORT}/sse"
  else
    URL="${SSE_URL}"
  fi
fi
HEALTH_HTTP="${URL%/}/health"

# -----------------------------------------------
# C.1) Probe URL (quick)
# -----------------------------------------------
step "Probe ${URL} (3s)"
show_cmd "curl -s -I --max-time 3 \"${URL}\" || curl -s -N --max-time 3 \"${URL}\""
set +e
hdr="$(curl -s -I --max-time 3 "${URL}" 2>/dev/null)"
rc=$?
if (( rc != 0 )) || [[ -z "${hdr}" ]]; then
  curl -s -N --max-time 3 "${URL}" 2>/dev/null | head -n 2 || true
  PROBE_OK=0
else
  printf "%s\n" "${hdr}" | sed -n '1,4p'
  PROBE_OK=1
fi
set -e
ok "Probe done."

# -----------------------------------------------
# D) (Optional) Register directly in mcpgateway
# -----------------------------------------------
if (( REGISTER_GATEWAY == 1 )); then
  step "Register in mcpgateway"
  if [[ -z "${GW_TOKEN}" ]]; then
    warn "No GW token provided; skipping gateway registration."
  else
    AUTH=(-H "Authorization: Bearer ${GW_TOKEN}")
    # Minimal tool payload
    TOOL_ID="watsonx-chat"; TOOL_NAME="watsonx-chat"; TOOL_DESC="Chat with IBM watsonx.ai"
    TOOL_PAY="$(jq -nc --arg id "$TOOL_ID" --arg name "$TOOL_NAME" --arg d "$TOOL_DESC" \
      '{id:$id, name:$name, description:$d, integration_type:"MCP", request_type:"SSE"}')"

    PREVIEW="curl -sS -X POST \"${GW_BASE}/tools\" -H \"Content-Type: application/json\""
    PREVIEW="${PREVIEW} -H \"Authorization: Bearer $(MASK "${GW_TOKEN}")\" -d '<tool_json>'"
    show_cmd "${PREVIEW}"
    resp_t="$(curl -sS -X POST "${GW_BASE}/tools" -H "Content-Type: application/json" "${AUTH[@]}" -d "$TOOL_PAY" || true)"
    code_t="$(jq -r 'try .status // empty' <<<"$resp_t" 2>/dev/null || true)"
    [[ -z "$code_t" ]] && code_t="$(echo "$resp_t" | sed -n '1p' | grep -oE '^[0-9]{3}$' || true)"
    [[ "$code_t" =~ ^(200|201|409)$ ]] && ok "Tool upserted (${TOOL_ID}) [HTTP ${code_t:-???}]" || { warn "Tool response: ${resp_t}"; }

    # Gateway – minimal schema
    GW_NAME="watsonx-mcp"; GW_DESC="Watsonx SSE server"
    GW_PAY_MIN="$(jq -nc --arg n "$GW_NAME" --arg d "$GW_DESC" --arg url "$URL" \
      '{name:$n, description:$d, url:$url, integration_type:"MCP", request_type:"SSE"}')"

    show_cmd "curl -sS -X POST \"${GW_BASE}/gateways\" -H \"Content-Type: application/json\" -H \"Authorization: Bearer ***\" -d '<gateway_json>'"
    resp_g="$(curl -sS -X POST "${GW_BASE}/gateways" -H "Content-Type: application/json" "${AUTH[@]}" -d "$GW_PAY_MIN" || true)"
    code_g="$(jq -r 'try .status // empty' <<<"$resp_g" 2>/dev/null || true)"
    if [[ "$code_g" =~ ^(200|201|409)$ ]]; then
      ok "Gateway upserted (${GW_NAME}) [HTTP ${code_g:-???}]"
    else
      warn "Gateway minimal payload failed; response: ${resp_g}"
    fi
  fi
fi

# -----------------------------------------------
# E) Showcase: MCP probe & two calls (guarded)
# -----------------------------------------------
if matrix mcp --help >/dev/null 2>&1; then
  if (( PROBE_OK == 1 )); then
    step "MCP showcase (2 calls)"
    # Discover the first tool name from probe JSON
    tools_json="$(matrix mcp probe --url "${URL}" --json 2>/dev/null || echo '{}')"
    tool_name="$(jq -r '(.tools // []) | .[0].name // .[0].id // empty' <<<"$tools_json" || true)"
    [[ -z "${tool_name}" ]] && tool_name="chat"
    info "Using tool: ${tool_name}"

    printf "${BLUE}Q1:${NC} What is the capital of Italy?\n"
    show_cmd "matrix mcp call ${tool_name} --url \"${URL}\" --args '{\"query\":\"What is the capital of Italy?\"}'"
    matrix mcp call "${tool_name}" --url "${URL}" --args '{"query":"What is the capital of Italy?"}' || true
    echo

    printf "${BLUE}Q2:${NC} Tell me about Genoa.\n"
    show_cmd "matrix mcp call ${tool_name} --url \"${URL}\" --args '{\"query\":\"Tell me about Genoa\"}'"
    matrix mcp call "${tool_name}" --url "${URL}" --args '{"query":"Tell me about Genoa"}' || true
    echo
  else
    warn "SSE endpoint not reachable; skipping MCP probe/call demo."
    warn "Ensure the remote server at ${SSE_URL} is running and reachable."
  fi
fi

# -----------------------------------------------
# F) Cleanup
# -----------------------------------------------
step "Cleanup: stop & uninstall"
show_cmd "matrix stop \"${ALIAS}\""
set +e; matrix stop "${ALIAS}" >/dev/null 2>&1 || true
if (( PURGE == 1 )); then
  show_cmd "matrix uninstall \"${ALIAS}\" --purge -y"
  matrix uninstall "${ALIAS}" --purge -y || true
else
  show_cmd "matrix uninstall \"${ALIAS}\" -y"
  matrix uninstall "${ALIAS}" -y || true
fi
set -e
ok "Done."
