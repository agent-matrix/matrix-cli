#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Watsonx.ai ⚡ Matrix CLI — WOW Demo (Unified & Hardened)
#
# Supports four modes (pick with MODE=...):
#   • inline-v2     : install via inline manifest v2 (runner embedded)   ✅ simplest
#   • inline-v1     : install via inline manifest v1 (+ runner/repo flags)
#   • hub-assisted  : let Hub return plan; SDK auto-synthesizes runner when possible
#   • hub-direct    : install via Hub + pass runner/repo up-front
#
# Robustness:
#   - Fails fast if .env creds missing; copies into runner dir for restart stability
#   - Proactively frees the chosen port (no jq dependency)
#   - Normalized /sse/ endpoint, reliable readiness probe & tool call
#   - If runner.json still missing post-install (hub-assisted), we synthesize connector
# ----------------------------------------------------------------------------
set -Eeuo pipefail

# --- Pretty Logging ---
C_CYAN="\033[1;36m"; C_GREEN="\033[1;32m"; C_YELLOW="\033[1;33m"; C_RED="\033[1;31m"; C_RESET="\033[0m"
log()  { printf "\n${C_CYAN}▶ %s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✓ %s${C_RESET}\n" "$*"; }
warn() { printf "${C_YELLOW}! %s${C_RESET}\n" "$*"; }
err()  { printf "${C_RED}✗ %s${C_RESET}\n" "$*" >&2; }

# Print a command with safe quoting, then run it preserving args
cmd() {
  printf "${C_GREEN}$"
  for a in "$@"; do printf " %q" "$a"; done
  printf "${C_RESET}\n" >&2
  "$@"
}

# --- Demo Parameters (env-overridable) ---
MODE="${MODE:-inline-v2}"                   # inline-v2 | inline-v1 | hub-assisted | hub-direct
HUB="${HUB:-https://api.matrixhub.io}"
ALIAS="${ALIAS:-watsonx-chat-demo}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"

# Inline manifests to showcase both generations
MANIFEST_V2_URL="${MANIFEST_V2_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/manifests/watsonx.manifest-v2.json}"
MANIFEST_V1_URL="${MANIFEST_V1_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/manifests/watsonx.manifest.json}"

# Fallback runner + repo for modes that need them
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"

QUESTION="${QUESTION:-Tell me about Genoa, a historic port city in Italy}"
DEMO_PORT="${DEMO_PORT:-6288}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

# --- Derived Paths & Pre-flight Checks ---
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
RUN_DIR="${MATRIX_HOME}/runners/${ALIAS}/${FQID##*@}"
command -v matrix >/dev/null 2>&1 || { err "matrix CLI not found in PATH"; exit 1; }
export MATRIX_BASE_URL="${HUB}"

# Encourage SDK synthesis paths (harmless if unused)
: "${MATRIX_SDK_ALLOW_MANIFEST_FETCH:=1}"
: "${MATRIX_SDK_RUNNER_SEARCH_DEPTH:=3}"
export MATRIX_SDK_ALLOW_MANIFEST_FETCH MATRIX_SDK_RUNNER_SEARCH_DEPTH

# --- Cleanup on Exit ---
cleanup() {
  log "Cleaning up..."
  matrix stop "$ALIAS" >/dev/null 2>&1 || true
  matrix uninstall "$ALIAS" -y >/dev/null 2>&1 || true
  ok "Cleanup complete."
}
trap cleanup EXIT INT TERM

# --- Banner ---
printf "\n${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
printf   "${C_CYAN}  Watsonx.ai × Matrix Hub — Unified Demo (${MODE})${C_RESET}\n"
printf   "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
echo "  Hub:   ${HUB}"
echo "  Alias: ${ALIAS}"
echo "  FQID:  ${FQID}"
echo "  Port:  ${DEMO_PORT}"

# --- 1) Credentials Check (Fail Fast) ---
log "Checking for WatsonX Credentials"
if [[ ! -f ".env" ]]; then
  err "Credentials not found."
  printf >&2 "Please create a '.env' with:\n"
  printf >&2 "${C_GREEN}  WATSONX_API_KEY=...\n  WATSONX_URL=...\n  WATSONX_PROJECT_ID=...\n${C_RESET}"
  exit 1
fi
set -a; source .env; set +a
ok "Credentials loaded from local .env file."

# --- 2) Install the Agent (choose strategy) ---
install_inline_v2() {
  cmd matrix install "$FQID" \
    --alias "$ALIAS" \
    --hub "$HUB" \
    --manifest "$MANIFEST_V2_URL" \
    --force --no-prompt
}

install_inline_v1() {
  cmd matrix install "$FQID" \
    --alias "$ALIAS" \
    --hub "$HUB" \
    --manifest "$MANIFEST_V1_URL" \
    --runner-url "$RUNNER_URL" \
    --repo-url "$REPO_URL" \
    --force --no-prompt
}

install_hub_assisted() {
  # No runner/repo hints; lean on Hub plan + SDK synthesis.
  cmd matrix install "$FQID" \
    --alias "$ALIAS" \
    --hub "$HUB" \
    --force --no-prompt
}

install_hub_direct() {
  # Push runner/repo up-front so run works even if Hub lacks runner.
  cmd matrix install "$FQID" \
    --alias "$ALIAS" \
    --hub "$HUB" \
    --runner-url "$RUNNER_URL" \
    --repo-url "$REPO_URL" \
    --force --no-prompt
}

log "Installing the WatsonX Agent"
case "$MODE" in
  inline-v2)     install_inline_v2 ;;
  inline-v1)     install_inline_v1 ;;
  hub-assisted)  install_hub_assisted ;;
  hub-direct)    install_hub_direct ;;
  *) err "Unknown MODE='$MODE'. Use: inline-v2 | inline-v1 | hub-assisted | hub-direct"; exit 2 ;;
esac
ok "Installation complete."

# Copy .env into runner dir for stable restarts
mkdir -p "$RUN_DIR"
if [[ -f "$RUN_DIR/.env" ]]; then
  warn "Runner .env already exists at $RUN_DIR/.env — leaving it as-is."
else
  cp -f .env "$RUN_DIR/.env"
  ok "Copied credentials into $RUN_DIR/.env for persistence."
fi

# If runner.json still missing (common in hub-assisted), try final fallbacks:
ensure_runner_json() {
  local rpath="${RUN_DIR}/runner.json"
  if [[ -f "$rpath" ]]; then
    return 0
  fi

  # Try to write a minimal connector runner targeting our deterministic port
  warn "runner.json missing — synthesizing a minimal MCP/SSE connector for this demo."
  cat >"$rpath" <<EOF
{
  "type": "connector",
  "integration_type": "MCP",
  "request_type": "SSE",
  "url": "http://127.0.0.1:${DEMO_PORT}/sse",
  "endpoint": "/sse",
  "headers": {}
}
EOF
  ok "runner.json written → ${rpath}"
}

if [[ "$MODE" == "hub-assisted" ]]; then
  # Rely on SDK first; if not produced, synthesize connector so 'matrix run' succeeds.
  if [[ ! -f "$RUN_DIR/runner.json" ]]; then
    warn "Hub-assisted install did not materialize runner.json."
    ensure_runner_json
  fi
fi

# --- 3) Start the Agent on a Known Port (free the port first) ---
free_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti TCP:"$port" -sTCP:LISTEN || true)"
    if [[ -n "$pids" ]]; then
      warn "Port ${port} is already in use. Terminating listener(s): $pids"
      # Try graceful stop via matrix first
      matrix stop "$ALIAS" >/dev/null 2>&1 || true
      # Then force kill if still present
      sleep 0.5
      pids="$(lsof -ti TCP:"$port" -sTCP:LISTEN || true)"
      [[ -n "$pids" ]] && kill -9 $pids || true
      sleep 0.5
    fi
  elif command -v fuser >/dev/null 2>&1; then
    if fuser -n tcp "$port" >/dev/null 2>&1; then
      warn "Port ${port} is already in use. Killing with fuser..."
      matrix stop "$ALIAS" >/dev/null 2>&1 || true
      fuser -k -n tcp "$port" || true
      sleep 0.5
    fi
  else
    warn "Neither lsof nor fuser available; assuming port ${port} is free."
  fi
}

log "Starting the agent server in the background (port ${DEMO_PORT})"
free_port "$DEMO_PORT"
cmd matrix run "$ALIAS" --port "${DEMO_PORT}"

# Define URLs now that the port is known (normalize to /sse/)
BASE_URL="http://127.0.0.1:${DEMO_PORT}"
SSE_URL="${BASE_URL}/sse/"
HEALTH_URL="${BASE_URL}/health"

# --- 4) Wait for Readiness ---
log "Waiting for server to become ready (up to ${READY_MAX_WAIT}s)"
deadline=$(( $(date +%s) + READY_MAX_WAIT ))
ready=0
while (( $(date +%s) < deadline )); do
  # If the process died, dump logs and bail
  if ! matrix ps --plain 2>/dev/null | awk '{print $1}' | grep -qx "$ALIAS"; then
    err "Server process for '$ALIAS' is not running. Showing recent logs:"
    matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
    exit 3
  fi
  # Probe health (fast) or SSE (thorough)
  if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1 || \
     matrix mcp probe --url "$SSE_URL" --timeout 4 >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if (( ! ready )); then
  err "Timed out waiting for readiness. Recent logs:"
  matrix logs "$ALIAS" 2>/dev/null | tail -n 200 || true
  exit 3
fi
ok "Server is ready! (${SSE_URL})"

# --- 5) Ask a Question ---
log "Asking WatsonX: \"$QUESTION\""
# Carefully escape quotes in JSON argument (and log with safe quoting)
JSON_PAYLOAD="{\"query\":\"${QUESTION//\"/\\\"}\"}"
cmd matrix mcp call chat --url "$SSE_URL" --args "$JSON_PAYLOAD"

ok "Demo complete! ✨"
exit 0
