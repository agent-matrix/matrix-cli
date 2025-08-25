#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Matrix CLI — End-to-End Demo Script (PoC)
# Version: v0.2.0
#
# This script shows a compact, reproducible flow that exercises key features of
# Matrix CLI: search, install, run, ps/logs, health, MCP probe/call, stop,
# and uninstall.
#
# It is safe to run multiple times; it avoids destructive operations by default
# and uses explicit alias names. Use --purge on uninstall to also delete files.
# ==============================================================================

# ----- Pretty Helpers ---------------------------------------------------------
#
# Formatted logging functions for clear, professional output.
#
log()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
step() { printf "\033[1;34m• %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
err()  { printf "\033[1;31m✗ %s\033[0m\n" "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { err "$1 not found in PATH"; exit 1; }; }

# This is our new command runner. It prints the command in green before executing it.
# Output is sent to stderr (>&2) so it doesn't interfere with command substitution.
cmd() {
  printf "\033[0;32m$ %s\033[0m\n" "$*" >&2
  "$@"
}


# ----- Prerequisites ----------------------------------------------------------
need matrix

# Optional: MCP client for probe/call
#   pip install "matrix-cli[mcp]"   # or: pip install mcp websockets

# Hub overrides (for dev/testing):
#   export MATRIX_HUB_BASE="https://api.matrixhub.io"
#   export MATRIX_HUB_TOKEN="..."

ALIAS="hello-sse-server"

# ==============================================================================
# START OF DEMO
# ==============================================================================

log "Matrix Versions"
step "CLI version flags"
cmd matrix --version || true
cmd matrix version || true

# ----- SEARCH -----------------------------------------------------------------
log "Search Examples"
step "MCP servers about 'hello'"
cmd matrix search "hello" --type mcp_server --limit 5 || true

step "Hybrid mode with snippets"
cmd matrix search "vector" --mode hybrid --with-snippets --limit 3 || true

step "Structured JSON results (truncated for display)"
cmd matrix search "sql agent" --capabilities rag,sql --json | sed -e 's/.\{120\}/&…/g' | head -n 20 || true

# ----- INSTALL ----------------------------------------------------------------
log "Install (short name → resolves to latest mcp_server)"
step "Idempotent install with explicit alias (no prompt on re-run)"
cmd matrix install hello-sse-server --alias "$ALIAS" --force --no-prompt || true

# ----- RUN --------------------------------------------------------------------
log "Run the Server"
step "Starting the component in the background"
cmd matrix run "$ALIAS" || true

# Give it a moment to boot (adjust if needed)
sleep 2

# ----- PROCESS STATUS ---------------------------------------------------------
log "List Processes (URL column visible)"
cmd matrix ps || true

# Auto-detect the port for the next steps.
PORT=$(cmd matrix ps --plain 2>/dev/null | awk -v a="$ALIAS" '$1==a{print $3}' | head -n1 || true)
if [[ -z "${PORT:-}" ]]; then
  warn "Could not auto-detect port for $ALIAS from 'matrix ps'."
  warn "Copy the URL from the PS table above, or just run:"
  printf "    matrix mcp probe --alias %s\n" "$ALIAS"
else
  URL="http://127.0.0.1:${PORT}/messages/"
  log "Probe MCP over SSE via URL"
  step "Initialize session & list tools"
  cmd matrix mcp probe --url "$URL" || true

  log "Call an MCP Tool"
  step "Call the 'hello' tool via alias autodiscovery"
  cmd matrix mcp call hello --alias "$ALIAS" --args '{}' || true

  log "Probe (JSON mode for CI/scripts)"
  cmd matrix mcp probe --url "$URL" --json || true
fi

# ----- HUB HEALTH -------------------------------------------------------------
log "Hub Health (human + JSON)"
step "Human-readable"
cmd matrix connection || true
step "Machine-friendly JSON"
cmd matrix connection --json || true

# ----- LOGS -------------------------------------------------------------------
log "Show Last 20 Log Lines"
cmd matrix logs "$ALIAS" | tail -n 20 || true

# ----- STOP -------------------------------------------------------------------
log "Stop the Server"
cmd matrix stop "$ALIAS" || true

# ----- UNINSTALL (CLEANUP) ----------------------------------------------------
log "Uninstall the Component (store entries only)"
step "Remove alias mapping (keeps files)"
cmd matrix uninstall "$ALIAS" --yes || true

log "Uninstall EVERYTHING (demo cleanup)"
step "Remove all aliases; keep files (safe)"
cmd matrix uninstall --all --yes || true

# Optional: full cleanup including files under ~/.matrix/runners (SAFE paths only)
# Uncomment the following if you want to delete local runner files too:
# log "Full purge (dangerous if you care about those files)"
# step "Remove all aliases and delete files"
# cmd matrix uninstall --all --purge --yes || true

ok "Demo finished."