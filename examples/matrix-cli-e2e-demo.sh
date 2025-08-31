#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Watsonx.ai ⚡ Matrix CLI — Simplified WOW Demo (hardened)
# - Forces a deterministic port so the app + runtime agree
# - Copies .env into the runner dir so restarts preserve creds
# - Probes by URL to avoid alias/port drift
# ----------------------------------------------------------------------------
set -Eeuo pipefail

# --- Pretty logs ---
C_CYAN="\033[1;36m"; C_GREEN="\033[1;32m"; C_YELLOW="\033[1;33m"; C_RED="\033[1;31m"; C_RESET="\033[0m"
log()  { printf "\n${C_CYAN}▶ %s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✓ %s${C_RESET}\n" "$*"; }
warn() { printf "${C_YELLOW}! %s${C_RESET}\n" "$*"; }
err()  { printf "${C_RED}✗ %s${C_RESET}\n" "$*" >&2; }
cmd()  { printf "${C_GREEN}$ %s${C_RESET}\n" "$*" >&2; "$@"; }

# --- Demo params (env-overridable) ---
HUB="${HUB:-http://localhost:443}"
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"
QUESTION="${QUESTION:-Tell me about Genoa, Italy}"

# Force a deterministic port so Matrix runtime and the app agree.
# Your app will mirror PORT -> WATSONX_AGENT_PORT in its launcher.
DEMO_PORT="${DEMO_PORT:-6288}"

# Maximum seconds to wait for readiness
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

# Respect MATRIX_HOME if set; otherwise default
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
RUN_DIR="${MATRIX_HOME}/runners/${ALIAS}/${FQID##*@}"

# Ensure matrix CLI exists (fixed redirection)
command -v matrix >/dev/null 2>&1 || { err "matrix CLI not found in PATH"; exit 1; }

# --- Cleanup on exit ---
cleanup() {
  log "Cleaning up..."
  matrix stop "$ALIAS" >/dev/null 2>&1 || true
  matrix uninstall "$ALIAS" -y >/dev/null 2>&1 || true
  ok "Cleanup complete."
}
trap cleanup EXIT INT TERM

# --- Banner ---
printf "\n${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
printf   "${C_CYAN}  Watsonx.ai × Matrix Hub — Simplified Demo${C_RESET}\n"
printf   "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
echo "  Alias: ${ALIAS}"
echo "  FQID:  ${FQID}"

# --- 1) Credentials ---
log "Checking for WatsonX Credentials"
if [[ ! -f ".env" ]]; then
  err "Credentials not found."
  printf >&2 "Please create a '.env' file in this directory with your WatsonX credentials.\n"
  printf >&2 "Example:\n"
  printf >&2 "${C_GREEN}  WATSONX_API_KEY=...\n  WATSONX_URL=...\n  WATSONX_PROJECT_ID=...\n${C_RESET}"
  exit 1
fi

# Export creds into the shell so initial run picks them up
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

# Ensure runner dir exists and copy .env into it so restarts keep credentials
mkdir -p "$RUN_DIR"
if [[ -f "$RUN_DIR/.env" ]]; then
  warn "Runner .env already exists at $RUN_DIR/.env — leaving it as-is."
else
  cp -f .env "$RUN_DIR/.env"
  ok "Copied credentials into $RUN_DIR/.env for stable restarts."
fi

# --- 3) Start the Agent on a known port ---
log "Starting the agent server in the background (port ${DEMO_PORT})"
cmd matrix run "$ALIAS" --port "${DEMO_PORT}"

BASE_URL="http://127.0.0.1:${DEMO_PORT}"
SSE_URL="${BASE_URL}/sse/"
HEALTH_URL="${BASE_URL}/health"

# --- 4) Wait for readiness ---
log "Waiting for server to become ready (up to ${READY_MAX_WAIT}s)"
# First: quick health probe loop (fast fail if port mismatch)
deadline=$(( $(date +%s) + READY_MAX_WAIT ))
ready=0
while (( $(date +%s) < deadline )); do
  if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
    ready=1
    break
  fi
  # Secondary probe via MCP (URL-based to avoid alias/port drift)
  if matrix mcp probe --url "$SSE_URL" --timeout 3 >/dev/null 2>&1; then
    ready=1
    break
  fi
  # If the process died, dump logs and bail
  if ! matrix ps --plain 2>/dev/null | awk '{print $1}' | grep -qx "$ALIAS"; then
    err "Server process for '$ALIAS' is not running. Showing recent logs:"
    matrix logs "$ALIAS" 2>/dev/null | tail -n 80 || true
    exit 3
  fi
  sleep 2
done

if (( ! ready )); then
  err "Timed out waiting for readiness. Recent logs:"
  matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
  exit 3
fi
ok "Server is ready! (${SSE_URL})"

# --- 5) Ask a question ---
log "Asking WatsonX: \"$QUESTION\""
cmd matrix mcp call chat --url "$SSE_URL" --args "{\"query\":\"${QUESTION//\"/\\\"}\"}"

ok "Demo complete! ✨"
exit 0
