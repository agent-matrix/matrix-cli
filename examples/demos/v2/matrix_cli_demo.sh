#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Matrix CLI — End-to-End Demo Script (PoC)
# Script Version: v0.6.0
# Requires: matrix-cli >= v0.1.5  (for: matrix do, matrix help, enhanced mcp call)
#
# This demo showcases a clean, beginner-friendly UX:
#   • matrix do   — one-shot, zero-JSON call
#   • matrix help — schema-aware usage with “Try:” lines
#   • matrix chat — (beta) REPL over a single session (optional)
#
# It prefers your local watsonx server (watsonx_mcp/app.py) when creds + folder
# are present; otherwise it falls back to hello-sse-server.
# Safe to re-run. Avoids destructive operations by default.
# ==============================================================================

# ----- Pretty Helpers ---------------------------------------------------------
log()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
step() { printf "\033[1;34m• %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
err()  { printf "\033[1;31m✗ %s\033[0m\n" "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { err "$1 not found in PATH"; exit 1; }; }
have() { command -v "$1" >/dev/null 2>&1; }
cmd()  { printf "\033[0;32m$ %s\033[0m\n" "$*" >&2; "$@"; }

# Version compare using sort -V (present on GNU coreutils and BSD/macOS)
version_ge() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }
version_lt() { ! version_ge "$1" "$2"; }

# Resolve URL/PORT robustly from `matrix ps --plain`
ps_url_for()  { matrix ps --plain 2>/dev/null | awk -v a="$1" '$1==a{print $5; exit}'; }
ps_port_for() { matrix ps --plain 2>/dev/null | awk -v a="$1" '$1==a{print $3; exit}'; }

# Extract the first tool name shown by `matrix help <alias>` (human output)
first_tool_for() {
  matrix help "$1" 2>/dev/null | awk '/^• /{t=$2; sub(/:.*/, "", t); print t; exit}'
}

# Ensure cleanup on abrupt exit (best-effort, non-fatal)
cleanup() {
  if matrix ps --plain 2>/dev/null | awk -v a="${ALIAS:-}" '$1==a{exit 0} END{exit 1}'; then
    cmd matrix stop "${ALIAS}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# ----- Prerequisites ----------------------------------------------------------
need matrix

# Gate features by CLI version
CLI_VER="$(matrix --version 2>/dev/null || echo "0.0.0")"
REQUIRED="0.1.5"
if version_lt "$CLI_VER" "$REQUIRED"; then
  warn "matrix-cli $CLI_VER detected. This demo needs >= $REQUIRED."
  warn "Upgrade first:\n    pip install -U matrix-cli"
  exit 2
fi

# Detect local watsonx server availability (folder + creds)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
WATSONX_DIR_DEFAULT="${SCRIPT_DIR%/}/../../../watsonx_mcp"   # adjust if needed
WATSONX_DIR="${WATSONX_DIR:-$WATSONX_DIR_DEFAULT}"

have_watsonx_folder=false
if [[ -d "$WATSONX_DIR" && -f "$WATSONX_DIR/app.py" ]]; then
  have_watsonx_folder=true
fi

have_watsonx_creds=false
if [[ -n "${WATSONX_API_KEY:-}" && -n "${WATSONX_URL:-}" && -n "${WATSONX_PROJECT_ID:-}" ]]; then
  have_watsonx_creds=true
fi

USE_WATSONX=false
if $have_watsonx_folder && $have_watsonx_creds; then
  USE_WATSONX=true
fi

# Choose alias & install/link strategy
if $USE_WATSONX; then
  ALIAS="${ALIAS:-watsonx-chat}"
else
  ALIAS="${ALIAS:-hello-sse-server}"
fi

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

# ----- INSTALL / LINK ---------------------------------------------------------
if $USE_WATSONX; then
  log "Link local watsonx MCP (no download, uses your folder)"
  step "Linking $WATSONX_DIR as alias '$ALIAS' (idempotent)"
  cmd matrix link "$WATSONX_DIR" --alias "$ALIAS" --force || true
else
  log "Install (short name → resolves to latest mcp_server)"
  step "Idempotent install with explicit alias (no prompt on re-run)"
  cmd matrix install hello-sse-server --alias "$ALIAS" --force --no-prompt || true
fi

# ----- RUN --------------------------------------------------------------------
log "Run the Server"
step "Starting the component in the background"
cmd matrix run "$ALIAS" || true
# NOTE: v0.1.5 prints a smart quickstart banner right after these lines.

# Allow brief boot (avoid race in ps/probe on slow machines)
sleep 1

# ----- PROCESS STATUS ---------------------------------------------------------
log "List Processes (URL column visible)"
cmd matrix ps || true

# Discover URL first (preferred), fallback to port
URL="$(ps_url_for "$ALIAS" || true)"
if [[ -z "${URL}" ]]; then
  PORT="$(ps_port_for "$ALIAS" || true)"
  if [[ -n "${PORT:-}" ]]; then
    # Prefer /sse/ if the server exposes SSE (hello server may still use /messages/)
    URL="http://127.0.0.1:${PORT}/sse/"
    # If that 404s, the mcp probe will still succeed with /messages/ fallback via alias in later steps.
  fi
fi

# ----- FRIENDLY HELP (NEW) ----------------------------------------------------
log "Human-Friendly Usage (schema-aware)"
step "List available tools + one-liners"
cmd matrix help "$ALIAS" || true

# Derive the first tool for later (hello or chat, typically)
DEFAULT_TOOL="$(first_tool_for "$ALIAS" || true)"
if [[ -z "${DEFAULT_TOOL}" ]]; then
  DEFAULT_TOOL="hello"  # safe fallback for hello-sse-server
fi

step "Detailed usage for the primary tool"
cmd matrix help "$ALIAS" --tool "$DEFAULT_TOOL" || true

# ----- ZERO-JSON ONE-SHOT (NEW) ----------------------------------------------
log "One-Shot Calls Without JSON"
step "Run the default tool with zero input (covers no-input tools)"
cmd matrix do "$ALIAS" || true

step "If the server expects a single text input, this maps automatically"
cmd matrix do "$ALIAS" "Hello from Matrix CLI PoC" || true

# ----- MCP PROBE/CALL (LEGACY + ENHANCED) ------------------------------------
if [[ -n "${URL:-}" ]]; then
  log "Probe MCP over SSE via URL"
  step "Initialize session & list tools"
  cmd matrix mcp probe --url "$URL" || true

  log "Call an MCP Tool (strict JSON)"
  step "Call the primary tool via alias autodiscovery using {}"
  cmd matrix mcp call "$DEFAULT_TOOL" --alias "$ALIAS" --args '{}' || true

  log "Call with stdin (@-) instead of inline JSON"
  echo '{}' | cmd matrix mcp call "$DEFAULT_TOOL" --alias "$ALIAS" --args @- || true

  log "Lenient & flexible args (NEW)"
  step "--text maps to the default input key when the tool has a single text field"
  if $USE_WATSONX || [[ "$DEFAULT_TOOL" == "chat" ]]; then
    cmd matrix mcp call "$DEFAULT_TOOL" --alias "$ALIAS" --text "Hello from --text flag" || true
  else
    warn "Server has no default text field; demonstrating --wizard instead"
    cmd matrix mcp call "$DEFAULT_TOOL" --alias "$ALIAS" --wizard || true
  fi

  log "Probe (machine-friendly JSON for CI/scripts)"
  cmd matrix mcp probe --url "$URL" --json || true
else
  warn "Could not auto-detect URL for $ALIAS from 'matrix ps'."
  warn "Copy the URL from the PS table above, or just run:"
  printf "    matrix mcp probe --alias %s\n" "$ALIAS"
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

# ----- OPTIONAL: BETA REPL (NEW) ---------------------------------------------
if matrix chat --help >/dev/null 2>&1; then
  log "Interactive Chat (beta) — single session, low latency"
  step "Send a single line and quit"
  { printf "Hello from chat REPL\n/quit\n" | cmd matrix chat "$ALIAS" || true; } 2>/dev/null
else
  warn "matrix chat is not available in this build — skipping REPL demo"
fi

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

ok "Demo finished."
