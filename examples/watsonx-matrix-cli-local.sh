#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Watsonx.ai ⚡ Matrix CLI — WOW Demo (process runner) [HARDENED & REFACTORED]
#
# Combines robust practices from the successful demo run:
#  - Fails fast if local .env credentials are not found.
#  - Copies .env into the runner directory for stable restarts.
#  - Starts the agent on a deterministic port for reliability.
#  - Probes and calls the agent via URL to prevent alias/port drift.
# ----------------------------------------------------------------------------
set -Eeuo pipefail

# --- Pretty Logging ---
C_CYAN="\033[1;36m"; C_GREEN="\033[1;32m"; C_YELLOW="\033[1;33m"; C_RED="\033[1;31m"; C_RESET="\033[0m"
log()  { printf "\n${C_CYAN}▶ %s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✓ %s${C_RESET}\n" "$*"; }
warn() { printf "${C_YELLOW}! %s${C_RESET}\n" "$*"; }
err()  { printf "${C_RED}✗ %s${C_RESET}\n" "$*" >&2; }
cmd()  { printf "${C_GREEN}$ %s${C_RESET}\n" "$*" >&2; "$@"; }

# --- Demo Parameters (env-overridable) ---
HUB="${HUB:-http://localhost:443}"
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"
QUESTION="${QUESTION:-Tell me about the history of Genoa}"
DEMO_PORT="${DEMO_PORT:-6288}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

# --- Derived Paths & Pre-flight Checks ---
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
RUN_DIR="${MATRIX_HOME}/runners/${ALIAS}/${FQID##*@}"
command -v matrix >/dev/null 2>&1 || { err "matrix CLI not found in PATH"; exit 1; }

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
printf   "${C_CYAN}  Watsonx.ai × Matrix Hub — Refactored Demo${C_RESET}\n"
printf   "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
echo "  Alias: ${ALIAS}"
echo "  FQID:  ${FQID}"
echo "  Port:  ${DEMO_PORT}"

# --- 1) Credentials Check (Fail Fast) ---
log "Checking for WatsonX Credentials"
if [[ ! -f ".env" ]]; then
  err "Credentials not found."
  printf >&2 "Please create a '.env' file in this directory with your WatsonX credentials.\n"
  printf >&2 "Example:\n"
  printf >&2 "${C_GREEN}  WATSONX_API_KEY=...\n  WATSONX_URL=...\n  WATSONX_PROJECT_ID=...\n${C_RESET}"
  exit 1
fi

# Export credentials into the shell so the initial run picks them up
set -a
# shellcheck disable=SC1091
source .env
set +a
ok "Credentials loaded from local .env file."

# --- 2) Install the Agent ---
log "Installing the WatsonX Agent"
cmd matrix install "$FQID" \
  --alias "$ALIAS" \
  --hub "$HUB" \
  --runner-url "$RUNNER_URL" \
  --repo-url "$REPO_URL" \
  --force --no-prompt
ok "Installation complete."

# Copy .env into the runner directory for stable restarts
mkdir -p "$RUN_DIR"
cp -f .env "$RUN_DIR/.env"
ok "Copied credentials into $RUN_DIR/.env for persistence."

# --- 3) Start the Agent on a Known Port ---
log "Starting the agent server in the background (port ${DEMO_PORT})"
cmd matrix run "$ALIAS" --port "${DEMO_PORT}"

# Define URLs now that the port is known
BASE_URL="http://127.0.0.1:${DEMO_PORT}"
SSE_URL="${BASE_URL}/sse"
HEALTH_URL="${BASE_URL}/health"

# --- 4) Wait for Readiness ---
log "Waiting for server to become ready (up to ${READY_MAX_WAIT}s)"
deadline=$(( $(date +%s) + READY_MAX_WAIT ))
ready=0
while (( $(date +%s) < deadline )); do
  # Check if the process died unexpectedly
  if ! matrix ps --plain 2>/dev/null | awk -v alias="$ALIAS" '$1==alias' | grep -q .; then
    err "Server process for '$ALIAS' is not running. Showing recent logs:"
    matrix logs "$ALIAS" 2>/dev/null | tail -n 80 || true
    exit 3
  fi
  # Probe the health endpoint (fast) and then the MCP endpoint (thorough)
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

# --- 5) Ask a Question ---
log "Asking WatsonX: \"$QUESTION\""
# Use the direct URL for the most reliable call
cmd matrix mcp call chat --url "$SSE_URL" --args "{\"query\":\"${QUESTION//\"/\\\"}\"}"

ok "Demo complete! ✨"
exit 0