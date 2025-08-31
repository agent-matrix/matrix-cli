#!/usr/bin/env bash
# examples/ingest_watsonx_demo_v2.sh
# ──────────────────────────────────────────────────────────────────────────────
# MatrixHub Ingestion PoC (v2) — Install, Run, and Query (prints commands)
# - Uses a direct runner.json for faster, more reliable installation.
# - Starts on a fixed port and uses a robust multi-probe readiness check.
# - Copies credentials for stability and adds automatic cleanup.
# ──────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

# ===== Matrix-style colors =====
C0="\033[0m"
C_HEAD="\033[38;5;48m"
C_DIM="\033[2m"
C_GREEN="\033[38;5;82m"
C_OK="\033[1;38;5;82m"
C_WARN="\033[1;38;5;214m"
C_ERR="\033[1;38;5;196m"
C_BOLD="\033[1m"

hr() { printf "${C_DIM}────────────────────────────────────────────────────────${C0}\n"; }
say() { printf "• %s\n" "$*"; }
ok() { printf "${C_OK}✓ %s${C0}\n" "$*"; }
warn() { printf "${C_WARN}⚠ %s${C0}\n" "$*"; }
die() {
    printf "\n${C_ERR}✗ %s${C0}\n" "$*" >&2
    printf "${C_DIM}--- Recent Logs ---\n" >&2
    # Indent logs slightly for readability
    matrix logs "$ALIAS" 2>/dev/null | tail -n 80 | sed 's/^/  /' >&2 || true
    exit 1
}
title() { printf "\n${C_HEAD}${C_BOLD}▮ %s ▮${C0}\n" "$*"; }

# Print and run command
run() {
    printf "${C_GREEN}$ %s${C0}\n" "$(printf '%q ' "$@")"
    "$@"
}

# ===== Config (override with env) =====
HUB="${HUB:-https://api.matrixhub.io}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
ALIAS="${ALIAS:-watsonx-agent}"

# ✨ FIX: Use the official runner config for simplicity and performance
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"

# ✨ FIX: Force a deterministic port to avoid mismatches
PORT="${PORT:-6288}"
QUESTION="${QUESTION:-Tell me about Genoa, a historic port city in Italy.}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

# ===== Deps =====
need() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }
need curl
need matrix
need awk
need grep

# ===== Paths =====
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
AGENT_ID="$(printf "%s" "$FQID" | sed -n 's/^mcp_server:\([^@]*\)@.*/\1/p')"
VERSION="$(printf "%s" "$FQID" | sed -n 's/.*@\([0-9][^ ]*\)$/\1/p')"
RUN_DIR="${MATRIX_HOME}/runners/${AGENT_ID}/${VERSION}"
ENV_FILE_DEST="${RUN_DIR}/.env"

# ===== Automatic Cleanup =====
# ✨ FIX: Ensure agent is stopped/uninstalled on script exit
cleanup() {
    say "Cleaning up..."
    matrix stop "$ALIAS" >/dev/null 2>&1 || true
    matrix uninstall "$ALIAS" -y >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

# ===== Banner =====
title "MatrixHub Ingestion PoC"
say "Hub:        ${HUB}"
say "FQID/Alias: ${FQID} / ${ALIAS}"
say "Port:       ${PORT}"
hr

# ===== 1) Credentials =====
title "Check and stage watsonx credentials"
if [ ! -f ".env" ]; then
    die "Create .env with WATSONX_API_KEY, WATSONX_URL, WATSONX_PROJECT_ID"
fi
# ✨ FIX: Copy .env into the runner directory for stability
mkdir -p "$RUN_DIR"
cp -f ".env" "$ENV_FILE_DEST"
ok "Credentials staged for the runner at $ENV_FILE_DEST"

# ===== 2) Install Agent (Simplified) =====
title "Install agent from manifest"
# ✨ FIX: Greatly simplified installation using the official runner.json
run matrix install "$FQID" \
    --alias "$ALIAS" \
    --hub "$HUB" \
    --runner-url "$RUNNER_URL" \
    --repo-url "$REPO_URL" \
    --force --no-prompt
ok "Installation complete."

# ===== 3) Start Server =====
title "Start server & wait for readiness"
run matrix run "$ALIAS" --port "${PORT}"

BASE_URL="http://127.0.0.1:${PORT}"
SSE_URL="${BASE_URL}/sse/"
HEALTH_URL="${BASE_URL}/health"

# ✨ FIX: More robust readiness check from your reference code
say "Waiting up to ${READY_MAX_WAIT}s for server at ${HEALTH_URL}..."
deadline=$(( $(date +%s) + READY_MAX_WAIT ))
is_ready=0
while (( $(date +%s) < deadline )); do
    # Primary check: health endpoint
    if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
        is_ready=1
        break
    fi
    # Secondary check: MCP probe
    if matrix mcp probe --url "$SSE_URL" --timeout 3 >/dev/null 2>&1; then
        is_ready=1
        break
    fi
    # Sanity check: ensure the process is still running
    if ! matrix ps --plain 2>/dev/null | awk '{print $1}' | grep -qx "$ALIAS"; then
        die "Server process for '$ALIAS' is not running."
    fi
    sleep 2
done

if (( ! is_ready )); then
    die "Timed out waiting for server readiness."
fi
ok "Server is ready at ${SSE_URL}"

# ===== 4) Probe & Call =====
title "Probe & call (SSE)"
run matrix mcp call chat --url "$SSE_URL" --args "{\"query\":\"${QUESTION//\"/\\\"}\"}"

ok "Done."
# The cleanup trap will run automatically on exit