#!/usr/bin/env bash
# ==============================================================================
# Matrix CLI — Watsonx Agent End-to-End Demo Script
# Version: v2.1.0 (Fixed) | Date: 2025-09-05
# ==============================================================================
# This script uses a polished visual style with the exact commands known to
# work correctly, ensuring a successful and well-presented demo.
# ==============================================================================

set -Eeuo pipefail

# ─── Pretty Helpers & Theming ─────────────────────────────────────────────────
C0="\033[0m"; C_HEAD="\033[38;5;48m"; C_DIM="\033[2m"
C_OK="\033[1;38;5;82m"; C_WARN="\033[1;33m"; C_ERR="\033[1;31m"
C_BOLD="\033[1m"; C_SPIN="\033[38;5;82m"; C_CMD="\033[0;32m"

log()  { printf "\n${C_HEAD}${C_BOLD}══ %s ══${C0}\n" "$*"; }
step() { printf "${C_DIM}• %s${C0}\n" "$*"; }
ok()   { printf "${C_OK}✓ %s${C0}\n" "$*"; }
warn() { printf "${C_WARN}⚠ %s${C0}\n" "$*"; }
err()  { printf "${C_ERR}✗ %s${C0}\n" "$*" >&2; } # Removed exit 1 to match original script behavior

# Print a command, show a spinner, capture output & status, and show output.
cmd_show() {
  printf "${C_CMD}$ %s${C0}\n" "$*" >&2
  local spin_pid; ( while :; do for c in ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏; do printf "\r${C_SPIN}${c}${C0}" >&2; sleep 0.1; done; done ) & spin_pid=$!
  local tmp; tmp="$(mktemp)"; set +e; "$@" >"$tmp" 2>&1; local st=$?; set -e
  kill $spin_pid &>/dev/null; printf "\r%80s\r" " " >&2
  CAPTURE_OUT="$(cat "$tmp")"; rm -f "$tmp"
  # Don't print dim, just print the raw output to be cleaner
  printf "%s\n" "$CAPTURE_OUT"
  return $st
}

need(){ command -v "$1" >/dev/null 2>&1 || { err "'$1' not found in PATH. Please ensure it is installed."; exit 1; }; }

# ─── Configuration (from working script) ──────────────────────────────────────
HUB="${HUB:-https://api.matrixhub.io}"
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
QUESTION="${QUESTION:-Tell me about Genoa, my current location}"
SECOND_QUESTION="${SECOND_QUESTION:-List three famous landmarks in Genoa}"
DEMO_PORT="${DEMO_PORT:-6288}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

export MATRIX_BASE_URL="${HUB}"
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
RUN_DIR="${MATRIX_HOME}/runners/${ALIAS}/${FQID##*@}"

# ─── Automatic Cleanup ────────────────────────────────────────────────────────
cleanup() {
  printf "\n"; log "🧹 AUTOMATIC CLEANUP"
  step "Ensuring agent '${ALIAS}' is stopped and uninstalled..."
  matrix stop "$ALIAS" >/dev/null 2>&1 || true
  matrix uninstall "$ALIAS" -y >/dev/null 2>&1 || true
  ok "Cleanup complete."
}
trap cleanup EXIT INT TERM

# ==============================================================================
#                            START OF DEMO
# ==============================================================================
need matrix; need curl;

log "0. SETUP: Checking Prerequisites"

step "Loading credentials from .env file..."
if [[ ! -f ".env" ]]; then
  err "Credentials not found."
  printf >&2 "Please create a '.env' file in this directory with your WatsonX credentials.\n"
  printf >&2 "Example:\n"
  printf >&2 "${C_OK}  WATSONX_API_KEY=...\n  WATSONX_URL=...\n  WATSONX_PROJECT_ID=...\n${C0}"
  exit 1
fi
set -a; source .env; set +a
ok "Credentials loaded from local .env file."

step "Checking Matrix CLI version..."
cmd_show matrix version || true

# ==============================================================================
# PART 1: THE "AHA!" MOMENT — FROM DISCOVERY TO INFERENCE
# ==============================================================================

log "1. 🔍 DISCOVER: Find Your AI Agent"
step "Search the Matrix Hub for Watsonx agents..."
cmd_show matrix search "watsonx" --type mcp_server --limit 5 || true

# ------------------------------------------------------------------------------
log "2. 📦 INSTALL: Get the Agent Ready"
step "Installing the agent and giving it the alias '$ALIAS'..."
# Using the exact working install command
cmd_show matrix install "$FQID" --alias "$ALIAS"

step "Copying local credentials for persistence..."
mkdir -p "$RUN_DIR"; cp -f .env "$RUN_DIR/.env"
ok "Copied credentials into $RUN_DIR/.env for persistence."

# ------------------------------------------------------------------------------
log "3. 🚀 RUN: Activate the Agent"
step "Launching agent in the background on port ${DEMO_PORT}..."
cmd_show matrix run "$ALIAS" --port "${DEMO_PORT}"
BASE_URL="http://127.0.0.1:${DEMO_PORT}"
SSE_URL="${BASE_URL}/sse"
HEALTH_URL="${BASE_URL}/health"

step "Waiting for server to become ready (up to ${READY_MAX_WAIT}s)..."
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
    ready=1; break
  fi
  printf "\r${C_SPIN}…waiting…${C0}"; sleep 2
done
printf "\r%80s\r" " " # Clear spinner line
if (( ! ready )); then
  err "Timed out waiting for readiness. Showing recent logs:"
  matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
  exit 3
fi
ok "Server is ready! (${SSE_URL})"

# ------------------------------------------------------------------------------
log "4. ✨ INTERACT: Get Your First Result!"
step "Asking a question with the simple and direct 'matrix do' command..."
cmd_show matrix do "$ALIAS" "$QUESTION" --url "$SSE_URL"
ok "First interaction complete."

# ==============================================================================
# PART 2: MANAGING AND UNDERSTANDING YOUR AGENT
# ==============================================================================

log "5. 📋 CHECK STATUS: See What's Running"
step "Listing all active Matrix processes..."
cmd_show matrix ps || true

# ------------------------------------------------------------------------------
log "6. 📖 GET HELP: Understand an Agent's Capabilities"
step "Inspecting the agent to see its available tools and arguments..."
cmd_show matrix help "$ALIAS" --tool chat || true

# ------------------------------------------------------------------------------
log "7. 🪵 REVIEW LOGS: Debug and Observe"
step "Showing the last 20 log lines from the agent..."
printf "${C_CMD}$ matrix logs \"%s\" | tail -n 20${C0}\n" "$ALIAS" >&2
matrix logs "$ALIAS" 2>/dev/null | tail -n 20 || true

# ==============================================================================
# PART 3: ADVANCED USAGE & CLEANUP
# ==============================================================================

log "8. ⚙️ ADVANCED INTERACTION: Using the Full MCP Command"
step "Using the structured 'mcp call' for scripting or complex arguments..."
cmd_show matrix mcp call chat --url "$SSE_URL" --args "{\"query\":\"${SECOND_QUESTION//\"/\\\"}\"}"
ok "Advanced interaction complete."

# ------------------------------------------------------------------------------
log "9. 🛑 TEARDOWN: Stop and Clean Up"
step "Stopping the running server process..."
cmd_show matrix stop "$ALIAS" || true
step "Removing the alias mapping..."
cmd_show matrix uninstall "$ALIAS" --yes || true

# ==============================================================================
# ▮▮▮                            END OF DEMO                             ▮▮▮
# ==============================================================================
printf "\n"; ok "Demo complete! ✨"
exit 0