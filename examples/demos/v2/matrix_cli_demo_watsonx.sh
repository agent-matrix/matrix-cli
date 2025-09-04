#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Watsonx.ai ⚡ Matrix CLI — WOW Demo (process runner) 
#
# This script is hardened and simplified for use with the public Matrix Hub API.
# It has been structured for an optimal presentation flow.
# ----------------------------------------------------------------------------
set -Eeuo pipefail

# --- Pretty Logging ---
C_CYAN="\033[1;36m"; C_GREEN="\033[1;32m"; C_YELLOW="\033[1;33m"; C_RED="\033[1;31m"; C_RESET="\033[0m"
log()  { printf "\n${C_CYAN}▶ %s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✓ %s${C_RESET}\n" "$*"; }
warn() { printf "${C_YELLOW}! %s${C_RESET}\n" "$*"; }
err()  { printf "${C_RED}✗ %s${C_RESET}\n" "$*" >&2; }
cmd()  { printf "${C_GREEN}$ %s${C_RESET}\n" "$*" >&2; "$@"; }
step() { printf "${C_YELLOW}→ %s${C_RESET}\n" "$*"; }

# --- Demo Parameters (env-overridable) ---
HUB="${HUB:-https://api.matrixhub.io}"
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
QUESTION="${QUESTION:-Tell me about Genoa, my current location}"
SECOND_QUESTION="${SECOND_QUESTION:-List three famous landmarks in Genoa}"
DEMO_PORT="${DEMO_PORT:-6288}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

# --- Derived Paths & Pre-flight Checks ---
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
RUN_DIR="${MATRIX_HOME}/runners/${ALIAS}/${FQID##*@}"
command -v matrix >/dev/null 2>&1 || { err "matrix CLI not found in PATH"; exit 1; }
export MATRIX_BASE_URL="${HUB}"

# --- Cleanup on Exit ---
cleanup() {
  log "🧹 Cleaning up..."
  matrix stop "$ALIAS" >/dev/null 2>&1 || true
  matrix uninstall "$ALIAS" -y >/dev/null 2>&1 || true
  ok "Cleanup complete."
}
trap cleanup EXIT INT TERM

# ==============================================================================
# START OF DEMO
# ==============================================================================

# --- Banner ---
printf "\n${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
printf   "${C_CYAN}  Watsonx.ai × Matrix Hub — Demo${C_RESET}\n"
printf   "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
echo "  Hub:   ${HUB}"
echo "  Alias: ${ALIAS}"
echo "  FQID:  ${FQID}"
echo "  Port:  ${DEMO_PORT}"

# --- 1) Credentials Check (Fail Fast) ---
log "Prerequisite: Checking for WatsonX Credentials"
if [[ ! -f ".env" ]]; then
  err "Credentials not found."
  printf >&2 "Please create a '.env' file in this directory with your WatsonX credentials.\n"
  printf >&2 "Example:\n"
  printf >&2 "${C_GREEN}  WATSONX_API_KEY=...\n  WATSONX_URL=...\n  WATSONX_PROJECT_ID=...\n${C_RESET}"
  exit 1
fi

set -a; source .env; set +a
ok "Credentials loaded from local .env file."

# --- 2) Version Check ---
log "Prerequisite: Checking Matrix Version"
cmd matrix version || true

# ==============================================================================
# PART 1: THE "AHA!" MOMENT — FROM DISCOVERY TO INFERENCE
# ==============================================================================

# --- 3) Discover ---
log "1. 🔍 Discover: Find Your AI Agent"
step "Search the Matrix Hub for Watsonx agents"
cmd matrix search "watsonx" --type mcp_server --limit 5 || true 

# --- 4) Install ---
log "2. 📦 Install: Get the Agent Ready"
step "Install the agent and give it a convenient alias"
cmd matrix install "$FQID" --alias "$ALIAS" 
# Copy .env into the runner directory for stable restarts
mkdir -p "$RUN_DIR"; cp -f .env "$RUN_DIR/.env"
ok "Copied credentials into $RUN_DIR/.env for persistence."

# --- 5) Run ---
log "3. 🚀 Run: Activate the Agent"
step "Start the agent server in the background on port ${DEMO_PORT}"
cmd matrix run "$ALIAS" --port "${DEMO_PORT}"

# Define URLs now that the port is known
BASE_URL="http://127.0.0.1:${DEMO_PORT}"
SSE_URL="${BASE_URL}/sse"
HEALTH_URL="${BASE_URL}/health"

# --- 6) Wait for Readiness ---
log "Waiting for server to become ready (up to ${READY_MAX_WAIT}s)"
deadline=$(( $(date +%s) + READY_MAX_WAIT ))
ready=0
while (( $(date +%s) < deadline )); do
  if ! matrix ps --plain 2>/dev/null | awk -v alias="$ALIAS" '$1==alias' | grep -q .; then
    err "Server process for '$ALIAS' is not running. Showing recent logs:"
    matrix logs "$ALIAS" 2>/dev/null | tail -n 80 || true
    exit 3
  fi
  if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1 || \
     matrix mcp probe --url "$SSE_URL" --timeout 3 >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if (( ! ready )); then
  err "Timed out waiting for readiness. Showing recent logs:"
  matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
  exit 3
fi
ok "Server is ready! (${SSE_URL})"

# --- 7) Interact (The Easy Way) ---
log "4. ✨ Interact: Get Your First Result!"
step "Ask a question with the simple 'do' command"
cmd matrix do "$ALIAS" "$QUESTION" 
# --url "$SSE_URL"

# ==============================================================================
# PART 2: MANAGING AND UNDERSTANDING YOUR AGENT
# ==============================================================================

# --- 8) Check Status ---
log "5. 📋 Check Status: See What's Running"
cmd matrix ps || true

# --- 9) Get Help ---
log "6. 📖 Get Help: Understand an Agent's Capabilities"
step "Inspect the agent to see its available tools and arguments"
cmd matrix help "$ALIAS" --tool chat || true

# --- 10) Review Logs ---
log "7. 🪵 Review Logs: Debug and Observe"
step "Show the last 20 log lines to see what happened 'under the hood'"
printf "${C_GREEN}$ %s${C_RESET}\n" "matrix logs \"$ALIAS\" | tail -n 20" >&2
matrix logs "$ALIAS" | tail -n 20 || true

# ==============================================================================
# PART 3: ADVANCED USAGE AND CLEANUP
# ==============================================================================

# --- 11) Advanced Interaction ---
log "8. ⚙️ Advanced Interaction: Using the Full MCP Command"
step "Use the structured 'mcp call' for scripting or complex arguments"
cmd matrix mcp call chat --url "$SSE_URL" --args "{\"query\":\"${SECOND_QUESTION//\"/\\\"}\"}"

# --- 12) Stop the Server ---
log "9. 🛑 Stop and Clean Up: Complete the Lifecycle"
step "Stop the running server process"
cmd matrix stop "$ALIAS" || true

# --- 13) Uninstall ---
step "Remove the alias mapping to complete the cleanup"
cmd matrix uninstall "$ALIAS" --yes || true

# --- Final Message ---
ok "Demo complete! ✨"
exit 0