#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/bash/poc_full_demo.sh
#
# Matrix PoC — runner.json-first demo for Watsonx MCP
# - Uses MatrixHub (https://api.matrixhub.io) for install planning.
# - Sends a GitHub-hosted runner.json via `runner_url` so the SDK writes it.
# - Ensures `provenance.source_url` is the repository URL (not null).
# - No manual runner.json writes in this script. The SDK/Hub handle it.
# - Still compatible with connector fallback in the SDK if Hub omits runner.
#
# What this script does:
#   1) (Optional) Starts a local Watsonx MCP server for quick tests (off by default).
#   2) Submits an inline manifest install to MatrixHub (non-destructive) with:
#        • mcp_registration.server.url patched to your SSE URL
#        • provenance.source_url = your Git repo
#        • runner_url = your GitHub raw runner.json
#   3) Installs locally via matrix CLI.
#   4) Runs the alias (process runner if provided; else connector fallback).
#   5) Probes the SSE endpoint and (optionally) registers in mcpgateway.
#   6) Calls the MCP tool twice as a smoke test.
#   7) (Optional) Cleanup stops/uninstalls the alias.
#
# Requirements:
#   - matrix CLI (>= 0.1.2.dev0)
#   - jq, curl, git (if --start-local)
#
# Example:
#   scripts/bash/poc_full_demo.sh \
#     --hub https://api.matrixhub.io \
#     --sse-url http://127.0.0.1:6289/sse \
#     --gw http://127.0.0.1:4444
# -----------------------------------------------------------------------------
set -Eeuo pipefail

# --------------------------------------------
# Optional .env loader (no-op if absent)
# --------------------------------------------
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

# --------------------------------------------
# Defaults (Hub → api.matrixhub.io)
# --------------------------------------------
HUB="${HUB:-https://api.matrixhub.io}"
HUB_TOKEN="${HUB_TOKEN:-${MATRIX_HUB_TOKEN:-}}"

GW_BASE="${GW_BASE:-http://127.0.0.1:4444}"
GW_TOKEN="${GW_TOKEN:-${MCP_GATEWAY_TOKEN:-}}"

ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
TARGET="${TARGET:-${ALIAS}/0.1.0}"

# Manifest + runner.json in GitHub
MANIFEST_URL="${MANIFEST_URL:-https://github.com/ruslanmv/watsonx-mcp/blob/master/manifests/watsonx.manifest.json?raw=1}"
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"

# Endpoint the MCP server will expose for SSE
SSE_URL="${SSE_URL:-http://127.0.0.1:6289/sse}"

# Local-run toggles (optional)
START_LOCAL="${START_LOCAL:-0}"
REPO_DIR="${REPO_DIR:-}"
PURGE="${PURGE:-0}"

# --------------------------------------------
# Helpers
# --------------------------------------------
GREEN="\033[0;32m"; BLUE="\033[1;34m"; CYAN="\033[1;36m"; NC="\033[0m"
show_cmd() { printf "${GREEN}$ %s${NC}\n" "$*"; }
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
  --hub-token TOKEN     Hub API token (Authorization) (default: $HUB_TOKEN / $MATRIX_HUB_TOKEN)
  --gw URL              mcpgateway base (default: ${GW_BASE})
  --gw-token TOKEN      mcpgateway token (default: $GW_TOKEN / $MCP_GATEWAY_TOKEN)
  --alias NAME          Local alias (default: ${ALIAS})
  --fqid ID             Entity id (default: ${FQID})
  --target LABEL        Hub plan label (default: ${TARGET})
  --manifest-url URL    Manifest JSON URL (default: ${MANIFEST_URL})
  --runner-url URL      Runner JSON URL (default: ${RUNNER_URL})
  --repo-url URL        Provenance source repo URL (default: ${REPO_URL})
  --sse-url URL         SSE URL (default: ${SSE_URL})
  --start-local         Clone+run watsonx-mcp locally (optional)
  --repo-dir DIR        Reuse or clone here (default: temp)
  --purge               Purge on uninstall
  -h, --help            Show help
EOF
}

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
    --runner-url) RUNNER_URL="$2"; shift 2;;
    --repo-url) REPO_URL="$2"; shift 2;;
    --sse-url) SSE_URL="$2"; shift 2;;
    --start-local) START_LOCAL=1; shift;;
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
info "Runner URL:  ${RUNNER_URL}"
info "Repo URL:    ${REPO_URL}"
info "SSE URL:     ${SSE_URL}"

# --------------------------------------------
# Optional: start local server (for manual testing)
# --------------------------------------------
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
  $PY -m venv .venv; source .venv/bin/activate || die "venv failure"

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

# --------------------------------------------
# A) Inline install → MatrixHub (non-destructive)
#    Include runner_url and provenance.source_url (repo)
# --------------------------------------------
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

# Build an install payload with explicit runner_url + provenance.source_url
PAYLOAD="$(jq -n \
  --arg id       "${FQID}" \
  --arg target   "${TARGET}" \
  --arg src      "${REPO_URL}" \
  --arg runner   "${RUNNER_URL}" \
  --argjson manifest "${PATCHED}" \
  '{id:$id, target:$target, manifest:$manifest, provenance:{source_url:$src}, runner_url:$runner}')"

HDR=(-H "Content-Type: application/json")
[[ -n "${HUB_TOKEN}" ]] && HDR+=(-H "Authorization: Bearer ${HUB_TOKEN}")
PREVIEW="curl -sS -X POST \"${HUB}/catalog/install\" -H \"Content-Type: application/json\""
[[ -n "${HUB_TOKEN}" ]] && PREVIEW+=" -H \"Authorization: Bearer $(MASK \"${HUB_TOKEN}\")\""
PREVIEW+=" --data '<payload>' | jq ."
show_cmd "${PREVIEW}"
# Send install request (Hub may ignore runner_url today; SDK patch handles fallback)
curl -sS -X POST "${HUB}/catalog/install" "${HDR[@]}" --data "${PAYLOAD}" | jq . || true
ok "Install request sent."

# --------------------------------------------
# B) Local install via matrix CLI (no manual runner.json writes here)
# --------------------------------------------
step "Local install via matrix CLI"
show_cmd "matrix install \"${FQID}\" --alias \"${ALIAS}\" --hub \"${HUB}\" --force --no-prompt"
set +e; matrix install "${FQID}" --alias "${ALIAS}" --hub "${HUB}" --force --no-prompt; RC=$?; set -e
(( RC == 0 )) || die "matrix install failed (${RC})"
ok "Installed locally as '${ALIAS}'."

# --------------------------------------------
# C) Run & determine URL (process runner or connector)
# --------------------------------------------
step "Run alias '${ALIAS}'"

# PRE-RUN: ensure no stale lock
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

# Discover URL from ps --json; fallback to configured SSE_URL
ps_json="$(matrix ps --json || echo '[]')"
URL="$(jq -r --arg a "${ALIAS,,}" '
  .[] | select((.alias // "" | ascii_downcase) == $a) | .url // empty
' <<<"$ps_json" | head -n1 || true)"
if [[ -z "${URL}" || "${URL}" == "-" || "${URL}" == "—" || "${URL}" == "N/A" ]]; then
  URL="${SSE_URL}"
fi
HEALTH="${URL%/}/health"

# --------------------------------------------
# C.1) Probe URL quickly
# --------------------------------------------
step "Probe ${URL} (3s)"
show_cmd "curl -s -I --max-time 3 \"${URL}\" || curl -s -N --max-time 3 \"${URL}\""
set +e
hdr="$(curl -s -I --max-time 3 "${URL}" 2>/dev/null)"; rc=$?
if (( rc != 0 )) || [[ -z "${hdr}" ]]; then
  curl -s -N --max-time 3 "${URL}" 2>/dev/null | head -n 2 || true
else
  printf "%s\n" "${hdr}" | sed -n '1,4p'
fi
set -e
ok "Probe done."

# --------------------------------------------
# D) Register in mcpgateway (optional)
# --------------------------------------------
step "Register in mcpgateway"
if [[ -z "${GW_TOKEN}" ]]; then
  warn "No GW token provided; skipping gateway registration."
else
  AUTH=(-H "Authorization: Bearer ${GW_TOKEN}")

  # Tool payload (id/name/desc) — pull from patched manifest if available
  TOOL_ID="$(jq -r '.mcp_registration.tool.id // "watsonx-chat"' <<<"$PATCHED")"
  TOOL_NAME="$(jq -r '.mcp_registration.tool.name // "watsonx-chat"' <<<"$PATCHED")"
  TOOL_DESC="$(jq -r '.mcp_registration.tool.description // ""' <<<"$PATCHED")"
  TOOL_PAY="$(jq -nc --arg id "$TOOL_ID" --arg name "$TOOL_NAME" --arg d "$TOOL_DESC" \
    '{id:$id, name:$name, description:$d, integration_type:"MCP", request_type:"SSE"}')"

  PREVIEW="curl -sS -X POST \"${GW_BASE}/tools\" -H \"Content-Type: application/json\""
  PREVIEW+=" -H \"Authorization: Bearer $(MASK \"${GW_TOKEN}\")\" -d '<tool_json>'"
  show_cmd "${PREVIEW}"
  resp_t="$(curl -sS -X POST "${GW_BASE}/tools" -H "Content-Type: application/json" "${AUTH[@]}" -d "$TOOL_PAY" || true)"
  code_t="$(jq -r 'try .status // empty' <<<"$resp_t" 2>/dev/null || true)"
  [[ -z "$code_t" ]] && code_t="$(echo "$resp_t" | sed -n '1p' | grep -oE '^[0-9]{3}$' || true)"
  [[ "$code_t" =~ ^(200|201|409)$ ]] && ok "Tool upserted (${TOOL_ID}) [HTTP ${code_t:-???}]" || { warn "Tool response: ${resp_t}"; }

  # Gateway — minimal schema first
  GW_NAME="$(jq -r '.mcp_registration.server.name // "watsonx-mcp"' <<<"$PATCHED")"
  GW_DESC="$(jq -r '.mcp_registration.server.description // ""' <<<"$PATCHED")"
  GW_PAY_MIN="$(jq -nc --arg n "$GW_NAME" --arg d "$GW_DESC" --arg url "$URL" \
    '{name:$n, description:$d, url:$url, integration_type:"MCP", request_type:"SSE"}')"

  show_cmd "curl -sS -X POST \"${GW_BASE}/gateways\" -H \"Content-Type: application/json\" -H \"Authorization: Bearer ***\" -d '<gateway_json>'"
  resp_g="$(curl -sS -X POST "${GW_BASE}/gateways" -H "Content-Type: application/json" "${AUTH[@]}" -d "$GW_PAY_MIN" || true)"
  code_g="$(jq -r 'try .status // empty' <<<"$resp_g" 2>/dev/null || true)"
  if [[ "$code_g" =~ ^(200|201|409)$ ]]; then
    ok "Gateway upserted (${GW_NAME}) [HTTP ${code_g:-???}]"
  else
    warn "Gateway minimal payload failed; response: ${resp_g}"
    # retry with associated_tools variant
    GW_PAY_ALT="$(jq -nc --arg n "$GW_NAME" --arg d "$GW_DESC" --arg url "$URL" --arg t "$TOOL_ID" \
      '{name:$n, description:$d, url:$url, associated_tools:[$t]}')"
    resp_g2="$(curl -sS -X POST "${GW_BASE}/gateways" -H "Content-Type: application/json" "${AUTH[@]}" -d "$GW_PAY_ALT" || true)"
    code_g2="$(jq -r 'try .status // empty' <<<"$resp_g2" 2>/dev/null || true)"
    [[ "$code_g2" =~ ^(200|201|409)$ ]] && ok "Gateway upserted (alt schema) [HTTP ${code_g2:-???}]" || warn "Gateway failed [body: ${resp_g2}]"
  fi
fi

# --------------------------------------------
# E) Showcase: ask two questions via MCP
# --------------------------------------------
if matrix mcp --help >/dev/null 2>&1; then
  step "MCP showcase (2 calls)"
  # Discover tool name from probe (prefer advertised list); fallback to 'chat'
  tools_json="$(matrix mcp probe --url "${URL}" --json 2>/dev/null || echo '{}')"
  tool_name="$(jq -r '(.tools // []) | .[0].name // .[0].id // empty' <<<"$tools_json" || true)"
  [[ -z "${tool_name}" ]] && tool_name="chat"
  info "Using tool: ${tool_name}"

  printf "${BLUE}Q1:${NC} What is the capital of Italy?\n"
  show_cmd "matrix mcp call ${tool_name} --url \"${URL}\" --args '{"query":"What is the capital of Italy?"}'"
  matrix mcp call "${tool_name}" --url "${URL}" --args '{"query":"What is the capital of Italy?"}' || true
  echo

  printf "${BLUE}Q2:${NC} Tell me about Genoa.\n"
  show_cmd "matrix mcp call ${tool_name} --url \"${URL}\" --args '{"query":"Tell me about Genoa"}'"
  matrix mcp call "${tool_name}" --url "${URL}" --args '{"query":"Tell me about Genoa"}' || true
  echo
fi

# --------------------------------------------
# F) Cleanup
# --------------------------------------------
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
