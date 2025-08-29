#!/usr/bin/env bash
# scripts/bash/poc_full_demo_native.sh (fixed)
# End-to-end PoC (native/connector-first) adapted to the upgraded installer.
# Key fixes:
#   • Use the runtime URL emitted by `matrix run` / `matrix ps --json` (no hardcoded 6288 probe)
#   • Probe with a one-time /sse <-> /messages/ fallback
#   • Discover tool name from probe JSON (handles array-of-strings or array-of-objects)
#   • Handle connector semantics (pid=0) + stale lock cleanup
#   • Keep minimal “write connector runner if missing” step (non-destructive)

set -Eeuo pipefail

# ---------- Defaults ----------
HUB="${HUB:-http://127.0.0.1:443}"
HUB_TOKEN="${HUB_TOKEN:-${MATRIX_HUB_TOKEN:-}}"

GW_BASE="${GW_BASE:-http://127.0.0.1:4444}"
GW_TOKEN="${GW_TOKEN:-${MCP_GATEWAY_TOKEN:-}}"

ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
TARGET="${TARGET:-${ALIAS}/0.1.0}"

# Fallback only — we will prefer URL discovered at runtime
SSE_URL="${SSE_URL:-http://127.0.0.1:6288/sse}"

MANIFEST_URL="${MANIFEST_URL:-https://github.com/ruslanmv/watsonx-mcp/blob/master/manifests/watsonx.manifest.json?raw=1}"
SOURCE_URL="${SOURCE_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/main/manifests/watsonx.manifest.json}"

START_LOCAL=0
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"
REPO_DIR="${REPO_DIR:-}"
PURGE=0

# ---------- Helpers ----------
GREEN='\033[0;32m'; CYAN='\033[1;36m'; NC='\033[0m'
show_cmd(){ printf "${GREEN}$ %s${NC}\n" "$*"; }
step()  { printf "\n${CYAN}▶ %s${NC}\n" "$*"; }
info()  { printf "ℹ %s\n" "$*"; }
ok()    { printf "✅ %s\n" "$*"; }
warn()  { printf "⚠ %s\n" "$*"; }
die()   { printf "✖ %s\n" "$*"; exit 1; }
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
  --target LABEL        Hub plan label (default: ${TARGET})
  --manifest-url URL    Manifest JSON URL (default: ${MANIFEST_URL})
  --source-url URL      Provenance URL (default: ${SOURCE_URL})
  --sse-url URL         SSE URL fallback (default: ${SSE_URL})
  --start-local         Clone+run watsonx-mcp locally (dev convenience)
  --repo-url URL        Repo to clone (default: ${REPO_URL})
  --repo-dir DIR        Reuse or clone here (default: temp)
  --purge               Purge files on uninstall
  -h, --help            Show help
EOF
}

# ---------- Args ----------
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

# ---------- Preflight ----------
command -v jq >/dev/null 2>&1 || die "jq not found"
command -v curl >/dev/null 2>&1 || die "curl not found"
command -v matrix >/dev/null 2>&1 || die "matrix CLI not found"

# Optional .env (creds etc.)
if [[ -f ".env" ]]; then
  info "Loading .env from .env"
  show_cmd "source .env"
  set +u; set -a; source .env; set +a; set -u
fi

step "Parameters"
info "Hub:         ${HUB}"
info "Hub Token:   $(MASK "${HUB_TOKEN}")"
info "Gateway:     ${GW_BASE}"
info "GW Token:    $(MASK "${GW_TOKEN}")"
info "Alias:       ${ALIAS}"
info "FQID:        ${FQID}"
info "Target:      ${TARGET}"
info "Manifest:    ${MANIFEST_URL}"
info "SSE URL:     ${SSE_URL} (fallback only)"

# ---------- Optional: start local server (dev convenience) ----------
LOCAL_PID=0; LOG_FILE="/tmp/wx-mcp-demo.log"; CLEAN_TEMP=0
if (( START_LOCAL == 1 )); then
  step "Starting local watsonx MCP"
  PORT_FROM_SSE="$(echo "${SSE_URL}" | sed -E 's#^https?://[^:]+:([0-9]+).*$#\1#' || true)"
  [[ "${PORT_FROM_SSE:-}" =~ ^[0-9]+$ ]] && export PORT="${PORT_FROM_SSE}"
  if [[ -z "${REPO_DIR}" ]]; then REPO_DIR="$(mktemp -d /tmp/wx-mcp-XXXXXX)"; CLEAN_TEMP=1; fi
  if [[ ! -d "${REPO_DIR}/.git" ]]; then
    show_cmd "git clone --depth=1 \"${REPO_URL}\" \"${REPO_DIR}\""
    git clone --depth=1 "${REPO_URL}" "${REPO_DIR}" >/dev/null 2>&1 || die "git clone failed"
  fi
  pushd "${REPO_DIR}" >/dev/null
  PY="$(command -v python3 || command -v python || true)"; [[ -z "$PY" ]] && die "python missing"
  show_cmd "$PY -m venv .venv && source .venv/bin/activate && pip -q install -U pip"
  $PY -m venv .venv; source .venv/bin/activate || die "venv fail"; pip -q install -U pip >/dev/null
  if [[ -f requirements.txt ]]; then
    show_cmd "pip -q install -r requirements.txt"
    pip -q install -r requirements.txt || die "pip install failed"
  else
    show_cmd "pip -q install ibm-watsonx-ai fastmcp starlette uvicorn python-dotenv"
    pip -q install ibm-watsonx-ai fastmcp starlette uvicorn python-dotenv || die "pip install failed"
  fi
  if [[ -f "bin/run_watsonx_mcp.py" ]]; then CMD="python bin/run_watsonx_mcp.py"; else CMD="python -m watsonx_mcp.app"; fi
  show_cmd "nohup ${CMD} > \"${LOG_FILE}\" 2>&1 &"
  nohup ${CMD} > "${LOG_FILE}" 2>&1 & LOCAL_PID=$!
  popd >/dev/null
  info "PID=${LOCAL_PID}, logs: ${LOG_FILE}"
  show_cmd "curl -sI --max-time 3 \"${SSE_URL}\""
  sleep 2; curl -sI --max-time 3 "${SSE_URL}" | sed -n '1,2p' || true
fi
cleanup_local(){
  if (( START_LOCAL==1 && LOCAL_PID>0 )); then
    info "Stopping local Watsonx MCP (pid=${LOCAL_PID})"
    show_cmd "kill ${LOCAL_PID}"
    kill "${LOCAL_PID}" 2>/dev/null || true
  fi
  if (( CLEAN_TEMP==1 )); then
    info "Removing temp clone ${REPO_DIR}"
    show_cmd "rm -rf \"${REPO_DIR}\""
    rm -rf "${REPO_DIR}" || true
  fi
}
trap cleanup_local EXIT

# ---------- A) Inline install → MatrixHub ----------
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
show_cmd "curl -sS -X POST \"${HUB}/catalog/install\" -H 'Content-Type: application/json' -H 'Authorization: Bearer ***' --data '<payload>' | jq ."
curl -sS -X POST "${HUB}/catalog/install" "${HDR[@]}" --data "${PAYLOAD}" | jq . || true
ok "Install request sent."

# ---------- B) Local install via matrix CLI ----------
step "Local install via matrix CLI"
show_cmd "matrix install \"${FQID}\" --alias \"${ALIAS}\" --hub \"${HUB}\" --force --no-prompt"
set +e; matrix install "${FQID}" --alias "${ALIAS}" --hub "${HUB}" --force --no-prompt; RC=$?; set -e
(( RC == 0 )) || die "matrix install failed (${RC})"
ok "Installed locally as '${ALIAS}'."

# ---------- B.1) Write connector runner if missing (non-destructive) ----------
VERSION="${TARGET#*/}"
RUN_DIR="${HOME}/.matrix/runners/${ALIAS}/${VERSION}"
RUNNER_FILE="${RUN_DIR}/runner.json"
show_cmd "mkdir -p \"${RUN_DIR}\""
mkdir -p "${RUN_DIR}"
if [[ ! -f "${RUNNER_FILE}" ]]; then
  step "runner.json missing → writing connector runner"
  cat > "${RUNNER_FILE}" <<JSON
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
  ok "connector runner.json written at ${RUNNER_FILE}"
fi

# ---------- C) Run & resolve URL (handle stale lock for connectors) ----------
LOCK_DIR="${HOME}/.matrix/state/${ALIAS}"
LOCK_FILE="${LOCK_DIR}/runner.lock.json"
if matrix ps --json | jq -e --arg a "${ALIAS,,}" '.[] | select((.alias // "" | ascii_downcase) == $a)' >/dev/null 2>&1; then
  info "Alias '${ALIAS}' appears active/locked — stopping before run…"
  matrix stop "${ALIAS}" >/dev/null 2>&1 || true
fi
[[ -f "${LOCK_FILE}" ]] && { warn "Removing stale lock file: ${LOCK_FILE}"; rm -f "${LOCK_FILE}" || true; }

step "Run alias '${ALIAS}'"
show_cmd "matrix run \"${ALIAS}\""
set +e; RUN_OUT="$(matrix run "${ALIAS}" 2>&1)"; RC=$?; set -e
(( RC == 0 )) || { echo "${RUN_OUT}"; die "Run failed."; }
echo "${RUN_OUT}" | sed -n '1,120p' | sed 's/^/   /'

# Prefer URL printed by run, then ps --json; fallback to SSE_URL
URL="$(echo "${RUN_OUT}" | sed -nE 's/.*Open in browser:[[:space:]]*([^[:space:]]+).*/\1/p' | head -n1 || true)"
if [[ -z "${URL}" ]]; then
  ps_json="$(matrix ps --json || echo '[]')"
  URL="$(jq -r --arg a "${ALIAS,,}" '.[] | select((.alias // "" | ascii_downcase) == $a) | .url // empty' <<<"$ps_json" | head -n1 || true)"
fi
[[ -z "${URL}" || "${URL}" == "-" || "${URL}" == "—" || ! "${URL}" =~ ^https?:// ]] && URL="${SSE_URL}"
URL="${URL%% *}" # trim

# ---------- C.1) Probe with one /sse <-> /messages/ fallback ----------
probe_once(){ local u="$1"; curl -sS -I --max-time 3 "$u" 2>/dev/null | head -n1 | awk '{print $2}'; }
swap_endpoint(){
  local u="$1"; local p="${u%/}"
  if [[ "$p" =~ /sse$ ]]; then echo "${p%/sse}/messages/"; else echo "${p%/}/sse"; fi
}

step "Probe ${URL} (with fallback if needed)"
show_cmd "curl -s -I --max-time 3 \"${URL}\""
status="$(probe_once "${URL}")" || status=""
if [[ ! "$status" =~ ^2[0-9][0-9]$ ]]; then
  ALT="$(swap_endpoint "${URL}")"
  warn "Primary probe HTTP ${status:-???}; trying fallback: ${ALT}"
  show_cmd "curl -s -I --max-time 3 \"${ALT}\""
  status2="$(probe_once "${ALT}")" || status2=""
  if [[ "$status2" =~ ^2[0-9][0-9]$ ]]; then URL="${ALT}"; ok "Fallback endpoint is reachable (HTTP ${status2})"; else warn "Fallback also failed (HTTP ${status2:-???})"; fi
else
  ok "Probe OK (HTTP ${status})"
fi

# ---------- D) Ask the Agent — discover tools & call ----------
step "Ask the Agent — quick Q&A"
show_cmd "matrix mcp probe --url \"${URL}\" --json | jq ."
TOOLS_JSON="$(matrix mcp probe --url "${URL}" --json 2>/dev/null || echo '{}')"

# tools may be ["chat", ...] or [{"name":"chat"}, {"id":"..."}]
TOOLS_CSV="$(jq -r '((.tools // []) | map(.name // .id // .) | join(","))' <<<"${TOOLS_JSON}" || true)"
IFS=',' read -r -a TOOL_ARR <<<"${TOOLS_CSV}"

TOOL="chat"
FOUND_CHAT=0
if (( ${#TOOL_ARR[@]} > 0 )); then
  for t in "${TOOL_ARR[@]}"; do
    if [[ "$t" == "chat" ]]; then FOUND_CHAT=1; break; fi
  done
  if (( FOUND_CHAT == 0 )); then TOOL="${TOOL_ARR[0]}"; fi
fi
info "Using tool: ${TOOL}"

Q1='{"query":"What is the capital of Italy?"}'
Q2='{"query":"Tell me about Genova"}'

show_cmd "matrix mcp call ${TOOL} --url \"${URL}\" --args '${Q1}'"
set +e; OUT1="$(matrix mcp call "${TOOL}" --url "${URL}" --args "${Q1}" 2>&1)"; RC1=$?; set -e
if (( RC1 != 0 )); then warn "Call 1 failed (${RC1})"; echo "${OUT1}" | sed 's/^/   /'; else echo "${OUT1}" | sed -n '1,120p' | sed 's/^/   /'; fi

show_cmd "matrix mcp call ${TOOL} --url \"${URL}\" --args '${Q2}'"
set +e; OUT2="$(matrix mcp call "${TOOL}" --url "${URL}" --args "${Q2}" 2>&1)"; RC2=$?; set -e
if (( RC2 != 0 )); then warn "Call 2 failed (${RC2})"; echo "${OUT2}" | sed 's/^/   /'; fi

# ---------- E) Register directly in mcpgateway (optional; kept for parity) ----------
step "Register in mcpgateway"
if [[ -z "${GW_TOKEN}" ]]; then
  warn "No GW token provided; skipping gateway registration."
else
  AUTH=(-H "Authorization: Bearer ${GW_TOKEN}")
  TOOL_ID="$(jq -r '.mcp_registration.tool.id // "watsonx-chat"' <<<"$PATCHED")"
  TOOL_NAME="$(jq -r '.mcp_registration.tool.name // "watsonx-chat"' <<<"$PATCHED")"
  TOOL_DESC="$(jq -r '.mcp_registration.tool.description // ""' <<<"$PATCHED")"
  TOOL_PAY="$(jq -nc --arg id "$TOOL_ID" --arg name "$TOOL_NAME" --arg d "$TOOL_DESC" '{id:$id, name:$name, description:$d, integration_type:"MCP", request_type:"SSE"}')"
  show_cmd "curl -sS -X POST \"${GW_BASE}/tools\" -H 'Content-Type: application/json' -H 'Authorization: Bearer ***' -d '<tool_json>'"
  tmp="$(mktemp)"; code="$(curl -sS -w '%{http_code}' -o "$tmp" -X POST "${GW_BASE}/tools" -H "Content-Type: application/json" "${AUTH[@]}" -d "$TOOL_PAY" || true)"
  if [[ "$code" =~ ^(200|201|409)$ ]]; then ok "Tool upserted (${TOOL_ID}) [HTTP ${code}]"; else warn "Tool failed [HTTP ${code}]"; sed -e 's/^/   body: /' "$tmp" || true; fi
  rm -f "$tmp"

  GW_NAME="$(jq -r '.mcp_registration.server.name // "watsonx-mcp"' <<<"$PATCHED")"
  GW_DESC="$(jq -r '.mcp_registration.server.description // ""' <<<"$PATCHED")"
  GW_PAY_MIN="$(jq -nc --arg n "$GW_NAME" --arg d "$GW_DESC" --arg url "$URL" '{name:$n, description:$d, url:$url, integration_type:"MCP", request_type:"SSE"}')"
  show_cmd "curl -sS -X POST \"${GW_BASE}/gateways\" -H 'Content-Type: application/json' -H 'Authorization: Bearer ***' -d '<gateway_json>'"
  resp_g="$(curl -sS -X POST "${GW_BASE}/gateways" -H "Content-Type: application/json" "${AUTH[@]}" -d "$GW_PAY_MIN" || true)"
  code_g="$(jq -r 'try .status // empty' <<<"$resp_g" 2>/dev/null || true)"
  if [[ "$code_g" =~ ^(200|201|409)$ ]]; then ok "Gateway upserted (${GW_NAME}) [HTTP ${code_g:-???}]"; else warn "Gateway response: ${resp_g}"; fi
fi

# ---------- F) Optional final probe ----------
if matrix mcp --help >/dev/null 2>&1; then
  step "matrix mcp probe (final)"
  show_cmd "matrix mcp probe --url \"${URL}\" --json | jq ."
  set +e; matrix mcp probe --url "${URL}" --json | jq . || true; set -e
fi

# ---------- G) Cleanup ----------
step "Cleanup: stop & uninstall"
show_cmd "matrix stop \"${ALIAS}\" || true"
set +e; matrix stop "${ALIAS}" >/dev/null 2>&1 || true; set -e
if (( PURGE == 1 )); then
  show_cmd "matrix uninstall \"${ALIAS}\" --purge -y || true"
  set +e; matrix uninstall "${ALIAS}" --purge -y || true; set -e
else
  show_cmd "matrix uninstall \"${ALIAS}\" -y || true"
  set +e; matrix uninstall "${ALIAS}" -y || true; set -e
fi
ok "Done."
