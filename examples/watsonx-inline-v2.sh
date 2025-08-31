#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Watsonx.ai ⚡ Matrix CLI — WOW Demo (inline manifest v2, no runner.json flag)
#
# What this does:
#   • Loads your Watsonx credentials from a local .env (fail fast if missing)
#   • Installs via the public Hub using the v2 manifest URL (no --runner-url)
#   • Copies .env to the runner dir so restarts retain credentials
#   • Starts the agent on a deterministic port
#   • Probes and calls the agent by URL for reliability
#
# Requirements:
#   • Updated matrix CLI + SDK with:
#       - `matrix install --manifest <url-or-path>`
#       - SDK writes runner.json from plan/manifest runner (connector/process)
#   • `.env` in the current directory with WATSONX_* variables
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
HUB="${HUB:-https://api.matrixhub.io}"
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"

# v2 manifest with embedded runner (no --runner-url needed)
MANIFEST_URL="${MANIFEST_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/manifests/watsonx.manifest-v2.json}"

# Optionally keep this so the code is present if your runner is a process runner
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"

QUESTION="${QUESTION:-Tell me about Genoa, my current location}"
DEMO_PORT="${DEMO_PORT:-6288}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

# --- Derived Paths & Checks ---
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
RUN_DIR="${MATRIX_HOME}/runners/${ALIAS}/${FQID##*@}"

command -v matrix >/dev/null 2>&1 || { err "matrix CLI not found in PATH"; exit 1; }
export MATRIX_BASE_URL="${HUB}"

# Make SDK more forgiving if Hub plan omits runner and only provides a manifest URL
: "${MATRIX_SDK_ALLOW_MANIFEST_FETCH:=1}"
export MATRIX_SDK_ALLOW_MANIFEST_FETCH

# Slightly deeper shallow search for runner.json (defensive)
: "${MATRIX_SDK_RUNNER_SEARCH_DEPTH:=3}"
export MATRIX_SDK_RUNNER_SEARCH_DEPTH

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
printf   "${C_CYAN}  Watsonx.ai × Matrix Hub — Inline Manifest v2 Demo${C_RESET}\n"
printf   "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
echo "  Hub:       ${HUB}"
echo "  Alias:     ${ALIAS}"
echo "  FQID:      ${FQID}"
echo "  Port:      ${DEMO_PORT}"
echo "  Manifest:  ${MANIFEST_URL}"

# --- 1) Credentials Check (Fail Fast) ---
log "Checking for WatsonX Credentials"
if [[ ! -f ".env" ]]; then
  err "Credentials not found."
  printf >&2 "Create a '.env' with:\n"
  printf >&2 "${C_GREEN}  WATSONX_API_KEY=...\n  WATSONX_URL=...\n  WATSONX_PROJECT_ID=...\n${C_RESET}"
  exit 1
fi

# Export credentials so first run inherits them
set -a
# shellcheck disable=SC1091
source .env
set +a
ok "Credentials loaded from local .env file."

# --- 2) Install via Hub using the inline manifest v2 ---
log "Installing the WatsonX Agent (inline manifest)"
# Note: no --runner-url here; runner comes from the manifest (v2) or SDK synthesis.
cmd matrix install "$FQID" \
  --alias "$ALIAS" \
  --hub "$HUB" \
  --manifest "$MANIFEST_URL" \
  --repo-url "$REPO_URL" \
  --force --no-prompt
ok "Installation complete."

# Copy .env into the runner directory for stable restarts
mkdir -p "$RUN_DIR"
if [[ -f "$RUN_DIR/.env" ]]; then
  warn "Runner .env already exists at $RUN_DIR/.env — leaving it as-is."
else
  cp -f .env "$RUN_DIR/.env"
  ok "Copied credentials into $RUN_DIR/.env for persistence."
fi

# --- 3) Start the Agent on a Known Port ---
log "Starting the agent server in the background (port ${DEMO_PORT})"
cmd matrix run "$ALIAS" --port "${DEMO_PORT}"

# Define URLs now that the port is known
BASE_URL="http://127.0.0.1:${DEMO_PORT}"
SSE_URL="${BASE_URL}/sse/"
HEALTH_URL="${BASE_URL}/health"

# --- 4) Readiness Loop ---
log "Waiting for server to become ready (up to ${READY_MAX_WAIT}s)"
deadline=$(( $(date +%s) + READY_MAX_WAIT ))
ready=0
while (( $(date +%s) < deadline )); do
  # If the process died, show logs and exit
  if ! matrix ps --plain 2>/dev/null | awk -v alias="$ALIAS" '$1==alias' | grep -q .; then
    err "Server process for '$ALIAS' is not running. Recent logs:"
    matrix logs "$ALIAS" 2>/dev/null | tail -n 80 || true
    exit 3
  fi
  # Health or MCP probe
  if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1 || \
     matrix mcp probe --url "$SSE_URL" --timeout 3 >/devnull 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if (( ! ready )); then
  err "Timed out waiting for readiness. Recent logs:"
  matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
  exit 3
fi
ok "Server is ready! (${SSE_URL})"

# --- 5) Ask a Question ---
log "Asking WatsonX: \"$QUESTION\""
cmd matrix mcp call chat --url "$SSE_URL" --args "{\"query\":\"${QUESTION//\"/\\\"}\"}"

ok "Demo complete! ✨"
exit 0
