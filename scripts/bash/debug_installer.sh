#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# scripts/bash/debug_installer.sh
#
# Collect a complete diagnostic bundle for:
#   • MatrixHub /catalog/install (catalog.py/planner)
#   • matrix-python-sdk installer (installer.py)
#
# Captures (into /tmp/matrix-debug-YYYYmmdd-HHMMSS):
#   • Environment & versions (python/pip/matrix CLI, package paths)
#   • OS release (lsb_release sanitized) and /etc/os-release fallback
#   • Hub/Gateway/SSE reachability (with /sse↔/messages fallback)
#   • Raw + patched manifest, and POST /catalog/install request/response (+curl -v)
#   • matrix install logs (MATRIX_SDK_DEBUG=1), runner dir snapshot, runner.json
#   • matrix ps --json, probe logs, socket listeners for SSE port
#   • Summary with likely root causes
#
# Safe defaults: read-only, no uninstall/stop. Does not start servers by default.
# -----------------------------------------------------------------------------
set -Eeuo pipefail

# ------------------------ Defaults & flags ------------------------
HUB="${HUB:-http://127.0.0.1:443}"
HUB_TOKEN="${HUB_TOKEN:-${MATRIX_HUB_TOKEN:-}}"

GW_BASE="${GW_BASE:-http://127.0.0.1:4444}"
GW_TOKEN="${GW_TOKEN:-${MCP_GATEWAY_TOKEN:-}}"

ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
TARGET="${TARGET:-${ALIAS}/0.1.0}"

MANIFEST_URL="${MANIFEST_URL:-https://github.com/ruslanmv/watsonx-mcp/blob/master/manifests/watsonx.manifest.json?raw=1}"
SOURCE_URL="${SOURCE_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/main/manifests/watsonx.manifest.json}"

SSE_URL="${SSE_URL:-http://127.0.0.1:6288/sse}"

# Pure diagnostics by default (no process spawn/kill)
START_LOCAL="${START_LOCAL:-0}"

OUTDIR="${OUTDIR:-/tmp/matrix-debug-$(date +%Y%m%d-%H%M%S)}"
CURL_MAX_TIME="${CURL_MAX_TIME:-5}"

# Skips for focused debugging
SKIP_HUB="${SKIP_HUB:-0}"   # skip /catalog/install
SKIP_CLI="${SKIP_CLI:-0}"   # skip matrix install/run/probe

# ------------------------ Styling & utils ------------------------
GREEN="\033[0;32m"; BLUE="\033[1;34m"; CYAN="\033[1;36m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; NC="\033[0m"
step()  { printf "\n${CYAN}▶ %s${NC}\n" "$*"; }
info()  { printf "ℹ %s\n" "$*"; }
ok()    { printf "${GREEN}✓ %s${NC}\n" "$*"; }
warn()  { printf "${YELLOW}! %s${NC}\n" "$*"; }
err()   { printf "${RED}✗ %s${NC}\n" "$*"; }
show()  { printf "${GREEN}$ %s${NC}\n" "$*"; }
MASK(){ local s="${1:-}"; [[ -z "$s" ]]&&{ echo "(empty)";return; }; local n=${#s}; ((n<=6))&&{ echo "******";return; }; printf "%s\n" "${s:0:3}***${s:n-3:3}"; }

http_code() { curl -s -o /dev/null -m "${2:-$CURL_MAX_TIME}" -w "%{http_code}" "$1"; }
is_http_ok() { local c; c="$(http_code "$1" "${2:-$CURL_MAX_TIME}" || echo 000)"; [[ "$c" =~ ^2..$ || "$c" =~ ^3..$ ]]; }
toggle_endpoint() {
  local u="$1"
  if [[ "$u" == *"/sse" || "$u" == *"/sse/" ]]; then
    echo "${u%/sse}/messages"
  else
    echo "${u%/messages}/sse"
  fi
}
parse_port_from_url() {
  local u="$1"
  if [[ "$u" =~ :([0-9]+) ]]; then echo "${BASH_REMATCH[1]}"; else echo "6288"; fi
}

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]
  --hub URL             MatrixHub base (default: ${HUB})
  --hub-token TOKEN     Hub API token (default: \$HUB_TOKEN/\$MATRIX_HUB_TOKEN)
  --gw URL              mcpgateway base (default: ${GW_BASE})
  --gw-token TOKEN      mcpgateway token (default: \$GW_TOKEN/\$MCP_GATEWAY_TOKEN)
  --alias NAME          Local alias (default: ${ALIAS})
  --fqid ID             Entity id (default: ${FQID})
  --target LABEL        Install target label (default: ${TARGET})
  --manifest-url URL    Manifest JSON URL (default: ${MANIFEST_URL})
  --source-url URL      Provenance URL (default: ${SOURCE_URL})
  --sse-url URL         SSE URL (default: ${SSE_URL})
  --outdir DIR          Output directory (default: ${OUTDIR})
  --skip-hub            Skip POST /catalog/install step
  --skip-cli            Skip matrix CLI (install/run/probe) steps
  --start-local         Try to start a local server (off by default)
  -h, --help            Show help
EOF
}

# ------------------------ Arg parse ------------------------
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
    --outdir) OUTDIR="$2"; shift 2;;
    --skip-hub) SKIP_HUB=1; shift;;
    --skip-cli) SKIP_CLI=1; shift;;
    --start-local) START_LOCAL=1; shift;;
    -h|--help) usage; exit 0;;
    *) warn "Unknown arg: $1"; usage; exit 2;;
  esac
done

# ------------------------ Preconditions ------------------------
mkdir -p "${OUTDIR}"
command -v jq >/dev/null 2>&1 || { err "jq not found"; exit 2; }
command -v curl >/dev/null 2>&1 || { err "curl not found"; exit 2; }

# Banner
printf "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf   "${CYAN} Matrix Debug Bundle → ${OUTDIR}${NC}\n"
printf   "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
info "Hub:        ${HUB}"
info "Hub Token:  $(MASK "${HUB_TOKEN}")"
info "Gateway:    ${GW_BASE}"
info "GW Token:   $(MASK "${GW_TOKEN}")"
info "Alias/FQID: ${ALIAS} / ${FQID}"
info "Target:     ${TARGET}"
info "Manifest:   ${MANIFEST_URL}"
info "SSE URL:    ${SSE_URL}"
if [[ "${HUB}" == *"0.0.0.0"* ]]; then
  warn "HUB uses 0.0.0.0 (listen address). Prefer 127.0.0.1 or a real host/IP for client calls."
fi

# ------------------------ 1) Environment snapshot ------------------------
step "Environment snapshot"
{
  echo "# uname"; uname -a
  echo
  echo "# date"; date -Iseconds
  echo
  echo "# OS release"
  if command -v lsb_release >/dev/null 2>&1; then
    # Silence the noisy 'No LSB modules are available.' line
    lsb_release -a 2>/dev/null | sed '/^No LSB modules are available\./d'
  elif [[ -f /etc/os-release ]]; then
    cat /etc/os-release
  else
    echo "(lsb_release and /etc/os-release not found)"
  fi
  echo
  echo "# python"
  if command -v python3 >/dev/null 2>&1; then
    python3 --version
    python3 - <<'PY' 2>/dev/null || true
import sys, platform
print("executable:", sys.executable)
print("prefix:", sys.prefix)
print("version_info:", sys.version.replace("\n"," "))
print("platform:", platform.platform())
PY
  else
    echo "python3 missing"
  fi
  echo
  echo "# pip"
  if command -v python3 >/dev/null 2>&1; then
    python3 -m pip --version 2>/dev/null || echo "(pip not available)"
  fi
  echo
  echo "# which python"; command -v python3 || true
  echo
  echo "# matrix CLI"; command -v matrix >/dev/null 2>&1 && matrix --version || echo "(matrix not found)"
  echo
  echo "# pip list (selected)"
  if command -v python3 >/dev/null 2>&1; then
    python3 -m pip list 2>/dev/null | grep -Ei 'matrix|httpx|uvicorn|starlette|fastmcp|ibm|watsonx' || echo "(no matching packages)"
  fi
  echo
  echo "# Python package locations"
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY' 2>/dev/null || true
import importlib, json
mods = ["matrix_sdk","matrix_cli","httpx","uvicorn","starlette","fastmcp"]
info={}
for m in mods:
    try:
        mod=importlib.import_module(m)
        info[m]=getattr(mod,"__file__",None)
    except Exception as e:
        info[m]=f"(not importable: {e})"
print(json.dumps(info, indent=2))
PY
  fi
  echo
  echo "# env (selected)"
  env | grep -E '^MATRIX_|^MCP_|^HUB_|^GW_' | sed 's/\(TOKEN=\).*/\1***masked***/' || true
} | tee "${OUTDIR}/env.txt" >/dev/null
ok "Saved → ${OUTDIR}/env.txt"

# ------------------------ 2) Reachability checks ------------------------
step "Reachability checks"
{
  echo "# Hub health"
  for u in "${HUB}/health" "${HUB}/"; do
    printf "%-40s -> %s\n" "$u" "$(http_code "$u" 3)"
  done
  echo
  echo "# Gateway health"
  for u in "${GW_BASE}/health" "${GW_BASE}/"; do
    printf "%-40s -> %s\n" "$u" "$(http_code "$u" 3)"
  done
  echo
  echo "# SSE endpoint (HEAD with fallback)"
  ALT="$(toggle_endpoint "${SSE_URL}")"
  printf "%-40s -> %s\n" "${SSE_URL}" "$(http_code "${SSE_URL}" 3)"
  printf "%-40s -> %s\n" "${ALT}"      "$(http_code "${ALT}" 3)"
  echo
  echo "# Who listens on port $(parse_port_from_url "${SSE_URL}")"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp | grep ":$(parse_port_from_url "${SSE_URL}")" || echo "(no listeners)"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -i :"$(parse_port_from_url "${SSE_URL}")" || echo "(no listeners)"
  else
    echo "Neither ss nor lsof available."
  fi
} | tee "${OUTDIR}/reachability.txt" >/dev/null
ok "Saved → ${OUTDIR}/reachability.txt"

# ------------------------ 3) Manifest fetch & patch ------------------------
step "Fetch & patch manifest"
RAW="${OUTDIR}/manifest.raw.json"
PATCHED="${OUTDIR}/manifest.patched.json"
show "curl -fsSL \"${MANIFEST_URL}\" -o \"${RAW}\""
curl -fsSL "${MANIFEST_URL}" -o "${RAW}" || { err "Failed to fetch manifest"; exit 2; }
ok "Saved → ${RAW}"

jq --arg sse "${SSE_URL}" '
  . as $m
  | .mcp_registration.server.url = $sse
  | if (.runner // empty | type=="object") then
      .runner.url = $sse
      | .runner.endpoint = "/sse"
    else . end
  | if .mcp_registration.tool then .mcp_registration.tool.request_type = "SSE" else . end
  | del(.mcp_registration.server.transport)
' "${RAW}" > "${PATCHED}"
ok "Saved → ${PATCHED}"

# ------------------------ 4) POST /catalog/install ------------------------
if (( SKIP_HUB == 0 )); then
  step "POST /catalog/install (catalog.py)"
  REQ="${OUTDIR}/install.request.json"
  RES="${OUTDIR}/install.response.json"
  CURLV="${OUTDIR}/install.curl.verbose.txt"

  jq -n --arg id "${FQID}" --arg target "${TARGET}" --arg src "${SOURCE_URL}" --argjson manifest "$(cat "${PATCHED}")" \
    '{id:$id, target:$target, manifest:$manifest, provenance:{source_url:$src}}' > "${REQ}"
  ok "Prepared → ${REQ}"

  HDR=(-H "Content-Type: application/json")
  [[ -n "${HUB_TOKEN}" ]] && HDR+=(-H "Authorization: Bearer ${HUB_TOKEN}")

  show "curl -sS -X POST \"${HUB}/catalog/install\" -H \"Content-Type: application/json\" --data @${REQ} (verbose → ${CURLV})"
  ( set -o pipefail
    curl -sS -v -X POST "${HUB}/catalog/install" "${HDR[@]}" --data @"${REQ}" \
      2> "${CURLV}" | jq . > "${RES}"
  )
  ok "Saved response → ${RES}"
else
  warn "Skipping /catalog/install per --skip-hub"
  REQ=""; RES=""
fi

# ------------------------ 5) matrix CLI: install + runner snapshot ------------------------
if (( SKIP_CLI == 0 )); then
  if ! command -v matrix >/dev/null 2>&1; then
    warn "matrix CLI not found; skipping CLI steps."
  else
    step "matrix install (installer.py path)"
    CLI_LOG="${OUTDIR}/matrix.install.log"
    show "MATRIX_SDK_DEBUG=1 MATRIX_SDK_ENABLE_CONNECTOR=1 matrix install \"${FQID}\" --alias \"${ALIAS}\" --hub \"${HUB}\" --force --no-prompt"
    ( set +e
      MATRIX_SDK_DEBUG=1 MATRIX_SDK_ENABLE_CONNECTOR=1 matrix install "${FQID}" --alias "${ALIAS}" --hub "${HUB}" --force --no-prompt \
        > >(tee "${CLI_LOG}") 2>&1
      RC=$?
      set -e
      echo "exit_code=${RC}" >> "${CLI_LOG}"
    )
    ok "Saved → ${CLI_LOG}"

    # Runner snapshot
    VERSION="${TARGET#*/}"
    RUN_DIR="${HOME}/.matrix/runners/${ALIAS}/${VERSION}"
    step "Runner snapshot → ${RUN_DIR}"
    mkdir -p "${OUTDIR}/runner-snapshot"
    { echo "# ls -la ${RUN_DIR}"; ls -la "${RUN_DIR}" 2>&1 || true; } \
      | tee "${OUTDIR}/runner-snapshot/ls.txt" >/dev/null
    if [[ -f "${RUN_DIR}/runner.json" ]]; then
      jq . "${RUN_DIR}/runner.json" > "${OUTDIR}/runner-snapshot/runner.json" 2>/dev/null || cp -f "${RUN_DIR}/runner.json" "${OUTDIR}/runner-snapshot/runner.json"
      ok "Captured runner.json"
    else
      warn "runner.json not found at ${RUN_DIR}"
    fi

    # matrix ps and probe
    step "matrix ps / probe"
    matrix ps --json > "${OUTDIR}/matrix.ps.json" 2>/dev/null || echo "[]" > "${OUTDIR}/matrix.ps.json"
    ok "Saved ps → ${OUTDIR}/matrix.ps.json"

    PROBE_LOG="${OUTDIR}/matrix.probe.log"
    if matrix mcp --help >/dev/null 2>&1; then
      show "matrix mcp probe --url \"${SSE_URL}\""
      ( set +e
        matrix mcp probe --url "${SSE_URL}" > "${PROBE_LOG}" 2>&1
        RC1=$?
        if (( RC1 != 0 )); then
          ALT="$(toggle_endpoint "${SSE_URL}")"
          echo "--- retry with ${ALT} ---" >> "${PROBE_LOG}"
          matrix mcp probe --url "${ALT}" >> "${PROBE_LOG}" 2>&1
        fi
        set -e
      )
      ok "Saved → ${PROBE_LOG}"
    else
      warn "matrix mcp subcommands not available; skipping probe."
    fi
  fi
else
  warn "Skipping matrix CLI steps per --skip-cli"
fi

# ------------------------ 6) Extra: curl views for SSE + listeners ------------------------
step "SSE HEAD previews"
{
  echo "# HEAD ${SSE_URL}"
  curl -sI --max-time "${CURL_MAX_TIME}" "${SSE_URL}" || true
  echo
  ALT="$(toggle_endpoint "${SSE_URL}")"
  echo "# HEAD ${ALT}"
  curl -sI --max-time "${CURL_MAX_TIME}" "${ALT}" || true
} | tee "${OUTDIR}/sse.head.txt" >/dev/null
ok "Saved → ${OUTDIR}/sse.head.txt"

# ------------------------ 7) Summaries & likely causes ------------------------
step "Summary (quick view)"
SUM="${OUTDIR}/summary.txt"
{
  echo "Outdir: ${OUTDIR}"
  echo

  if [[ -n "${RES}" && -f "${RES}" ]]; then
    echo "Install plan (from Hub):"
    jq '{plan:{runner:.plan.runner, server_url:.plan.mcp_registration.server.url}, results:.results|map({step,ok,extra})}' "${RES}" 2>/dev/null || cat "${RES}"
    echo
  fi

  if [[ -f "${OUTDIR}/runner-snapshot/runner.json" ]]; then
    echo "Local runner.json (effective):"
    jq '{type,name,url,endpoint,integration_type,request_type}' "${OUTDIR}/runner-snapshot/runner.json" 2>/dev/null || cat "${OUTDIR}/runner-snapshot/runner.json"
    echo
  fi

  echo "Reachability (HTTP codes):"
  cat "${OUTDIR}/reachability.txt"
  echo

  # Heuristics
  echo "Likely causes:"
  HUB_HC="$(http_code "${HUB}/health" 2 || echo 000)"
  GW_HC="$(http_code "${GW_BASE}/health" 2 || echo 000)"
  SSE_HC="$(http_code "${SSE_URL}" 2 || echo 000)"
  ALT="$(toggle_endpoint "${SSE_URL}")"
  SSE_ALT_HC="$(http_code "${ALT}" 2 || echo 000)"

  if [[ "${HUB}" == *"0.0.0.0"* ]]; then
    echo "- HUB is '0.0.0.0': use 127.0.0.1 or actual host for client requests."
  fi
  if ! [[ "${SSE_HC}" =~ ^2..$ || "${SSE_HC}" =~ ^3..$ || "${SSE_ALT_HC}" =~ ^2..$ || "${SSE_ALT_HC}" =~ ^3..$ ]]; then
    echo "- SSE not reachable on ${SSE_URL} nor ${ALT}: server likely not listening/bound to a different port/interface."
  fi
  if ! [[ "${GW_HC}" =~ ^2..$ || "${GW_HC}" =~ ^3..$ ]]; then
    echo "- mcpgateway health check failing: registration will 401/5xx."
  fi
  if [[ -n "${RES}" && -f "${RES}" ]]; then
    if jq -e '.results[]? | select(.step=="gateway.register") | .extra | tostring | test("401")' "${RES}" >/dev/null 2>&1; then
      echo "- Hub-side gateway.register returned 401: fix Hub's gateway token env or ignore (client does its own registration)."
    fi
  fi
} | tee "${SUM}" >/dev/null
ok "Saved → ${SUM}"

printf "\n${BLUE}Bundle ready:${NC} ${OUTDIR}\n"
echo "Attach ${OUTDIR} when filing an issue. Key files:"
echo "  - env.txt, reachability.txt, manifest.*.json"
echo "  - install.request.json, install.response.json, install.curl.verbose.txt"
echo "  - matrix.install.log, matrix.ps.json, matrix.probe.log"
echo "  - runner-snapshot/runner.json"
echo "  - sse.head.txt, summary.txt"

exit 0
