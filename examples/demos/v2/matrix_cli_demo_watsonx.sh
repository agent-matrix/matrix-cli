#!/usr/bin/env bash
# ==============================================================================
# Matrix CLI — Watsonx Agent End-to-End Demo Script (PoC)
# examples/demos/v2/matrix_cli_demo_watsonx.sh
# Version: v1.5.2 | Date: 2025-09-04
# Requires: matrix-cli >= v0.1.5  (for: matrix do, matrix help, enhanced mcp call)
# ==============================================================================

set -Eeuo pipefail

# ─── Pretty Helpers & Theming ─────────────────────────────────────────────────
C0="\033[0m"; C_HEAD="\033[38;5;48m"; C_DIM="\033[2m"
C_OK="\033[1;38;5;82m"; C_WARN="\033[1;33m"; C_ERR="\033[1;31m"
C_BOLD="\033[1m"; C_SPIN="\033[38;5;82m"; C_CMD="\033[0;32m"
C_WHITE="\033[97m"

log()  { printf "\n${C_HEAD}${C_BOLD}══ %s ══${C0}\n" "$*"; }
step() { printf "${C_DIM}• %s${C0}\n" "$*"; }
ok()   { printf "${C_OK}✓ %s${C0}\n" "$*"; }
warn() { printf "${C_WARN}⚠ %s${C0}\n" "$*"; }
err()  { printf "${C_ERR}✗ %s${C0}\n" "$*" >&2; exit 1; }

# ─── Command wrappers (robust under -e -u -o pipefail) ────────────────────────
# Run and show, capture output in CAPTURE_OUT, never leave spinner orphaned.
cmd_show() {
  printf "${C_CMD}$ %s${C0}\n" "$*" >&2
  local spinchars="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
  local tmp sp status
  tmp="$(mktemp)"
  (
    # spinner loop
    while :; do
      for ((i=0;i<${#spinchars};i++)); do
        printf "\r${C_SPIN}%s${C0}" "${spinchars:$i:1}" >&2
        sleep 0.1
      done
    done
  ) & sp=$!
  # run command, but don’t crash script on non-zero
  set +e
  "$@" >"$tmp" 2>&1
  status=$?
  set -e
  # stop spinner
  kill "$sp" >/dev/null 2>&1 || true
  wait "$sp" 2>/dev/null || true
  printf "\r%80s\r" " " >&2
  CAPTURE_OUT="$(cat "$tmp")"
  rm -f "$tmp"
  # echo captured (dim)
  printf "${C_DIM}%s${C0}\n" "$CAPTURE_OUT"
  return "$status"
}

# Capture only (don’t echo body); caller prints selectively.
cmd_spin_capture() {
  printf "${C_CMD}$ %s${C0}\n" "$*" >&2
  local spinchars="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
  local tmp sp status
  tmp="$(mktemp)"
  (
    while :; do
      for ((i=0;i<${#spinchars};i++)); do
        printf "\r${C_SPIN}%s${C0}" "${spinchars:$i:1}" >&2
        sleep 0.1
      done
    done
  ) & sp=$!
  set +e
  "$@" >"$tmp" 2>&1
  status=$?
  set -e
  kill "$sp" >/dev/null 2>&1 || true
  wait "$sp" 2>/dev/null || true
  printf "\r%80s\r" " " >&2
  CAPTURE_OUT="$(cat "$tmp")"
  rm -f "$tmp"
  return "$status"
}

# Pretty re-printers
print_call_with_white() {
  local seen=0 line
  while IFS= read -r line; do
    if [[ $seen -eq 1 ]]; then
      printf "%b%s%b\n" "$C_WHITE" "$line" "$C0"
    else
      printf "%s\n" "$line"
      [[ "$line" == "Call result:" ]] && seen=1
    fi
  done <<< "$1"
}

print_do_with_white() {
  local after=0 line
  while IFS= read -r line; do
    if [[ $after -eq 1 ]]; then
      printf "%b%s%b\n" "$C_WHITE" "$line" "$C0"
    else
      printf "%s\n" "$line"
      # accept both “Done.” and “Output:” as separators
      [[ "$line" == "✅ Done." || "$line" == "Output:" ]] && after=1
    fi
  done <<< "$1"
}

need(){ command -v "$1" >/dev/null 2>&1 || err "$1 not found in PATH. Please ensure it is installed."; }
need matrix; need curl; need python3; need grep; need awk; need find

# ─── Configuration ────────────────────────────────────────────────────────────
HUB="${HUB:-https://api.matrixhub.io}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
ALIAS="${ALIAS:-watsonx-demo-agent}"
PORT="${PORT:-6288}"
QUESTION="${QUESTION:-Tell me about Genoa, my current location, focusing on its maritime history.}"
FOLLOWUP="${FOLLOWUP:-What are the top 7 places to visit in Genoa near me? Give concise bullets with a one-line why.}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"
RECREATE="${RECREATE:-0}"

MANIFEST_URL="${MANIFEST_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/manifests/watsonx.manifest-v2.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"
FALLBACK_BOOTSTRAP="${FALLBACK_BOOTSTRAP:-1}"

export MATRIX_BASE_URL="$HUB"
export MATRIX_SDK_ALLOW_MANIFEST_FETCH=1
export MATRIX_SDK_RUNNER_SEARCH_DEPTH=3

MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
AGENT_NAME="${FQID#mcp_server:}"; AGENT_NAME="${AGENT_NAME%@*}"
VERSION="${FQID##*@}"
RUN_DIR_ALIAS="$MATRIX_HOME/runners/${ALIAS}/${VERSION}"
RUN_DIR_ID="$MATRIX_HOME/runners/${AGENT_NAME}/${VERSION}"

# ─── Load .env first (export to shell) ────────────────────────────────────────
log "0. ENV: Loading credentials from .env"
if [[ -f ".env" ]]; then
  set -a; source .env; set +a
  ok ".env loaded and exported to the current shell."
else
  warn ".env not found in current directory. If the agent needs WATSONX_* variables, it may fail."
fi

copy_env_files() {
  local dest="$1" srcdir="${2:-}"
  if [[ -f ".env" ]]; then
    mkdir -p "$dest" && cp -f ".env" "$dest/.env" && ok "Copied .env → $dest/.env" || true
    if [[ -n "$srcdir" ]]; then
      mkdir -p "$srcdir" && cp -f ".env" "$srcdir/.env" && ok "Copied .env → $srcdir/.env" || true
    fi
  fi
}

# ─── Helpers ──────────────────────────────────────────────────────────────────
wait_health() {
  local port="$1" until=$(( $(date +%s) + READY_MAX_WAIT ))
  local url="http://127.0.0.1:${port}/health"
  step "Probing health: $url"
  while [ "$(date +%s)" -lt "$until" ]; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      ok "Agent is healthy at $url"; return 0
    fi
    printf "\r${C_SPIN}  …waiting…${C0}"; sleep 0.25
  done
  printf "\r%80s\r" " "
  return 1
}

free_port() {
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids; pids="$(lsof -ti TCP:"$p" -sTCP:LISTEN || true)"
    if [ -n "$pids" ]; then warn "Port $p busy; killing: $pids"; kill -9 $pids || true; fi
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k -n tcp "$p" >/dev/null 2>&1 || true
  fi
}

clear_alias_locks() {
  local removed=0
  local LOCK_DIR="$MATRIX_HOME/locks"
  if [ -d "$LOCK_DIR" ]; then
    for f in "$LOCK_DIR/${ALIAS}.lock" "$LOCK_DIR/${ALIAS}.lck" "$LOCK_DIR/${ALIAS}.pid"; do
      [ -f "$f" ] && { warn "Removing stale lock: $f"; rm -f "$f" && removed=1; }
    done
  fi
  for base in "$RUN_DIR_ALIAS" "$RUN_DIR_ID"; do
    [ -d "$base" ] || continue
    while IFS= read -r -d '' lf; do
      warn "Removing stale lock: $lf"; rm -f "$lf" && removed=1
    done < <(find "$base" -maxdepth 2 -type f \( -name "*.lock" -o -name "lock" -o -name ".lock" \) -print0 2>/dev/null || true)
  done
  [ "$removed" -eq 1 ] && ok "Old lockfile(s) were found and overwritten." || true
}

is_lock_error() { grep -qiE 'lock file .*already exists|lockfile .*exists|lock.*exists' <<< "${1:-}"; }

# Resolve URL/PORT robustly from `matrix ps --plain`
ps_url_for()  { matrix ps --plain 2>/dev/null | awk -v a="$1" '$1==a{print $5; exit}'; }
ps_port_for() { matrix ps --plain 2>/dev/null | awk -v a="$1" '$1==a{print $3; exit}'; }

# Extract the first tool name from `matrix help <alias>`
first_tool_for() { matrix help "$1" 2>/dev/null | awk '/^• /{t=$2; sub(/:.*/, "", t); print t; exit}'; }

# Alias existence check
alias_exists() {
  [[ -d "$RUN_DIR_ALIAS" ]] || [[ -d "$RUN_DIR_ID" ]] || grep -q "\"$ALIAS\"" "$MATRIX_HOME/aliases.json" 2>/dev/null
}

# ─── Automatic Cleanup ────────────────────────────────────────────────────────
cleanup() {
  printf "\n"; log "AUTOMATIC CLEANUP"
  step "Ensuring agent '${ALIAS}' is stopped and uninstalled..."
  matrix stop "$ALIAS" --quiet >/dev/null 2>&1 || true
  matrix uninstall "$ALIAS" --yes --quiet >/dev/null 2>&1 || true
  ok "Cleanup complete."
}
trap cleanup EXIT INT TERM

# ─── Version Gate ────────────────────────────────────────────────────────────
version_ge() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }
CLI_VER="$(matrix --version 2>/dev/null || echo "0.0.0")"
REQ="0.1.5"
if ! version_ge "$CLI_VER" "$REQ"; then
  err "matrix-cli $CLI_VER found; this demo requires >= $REQ. Upgrade: pip install -U matrix-cli"
fi

# ==============================================================================
# 1) SEARCH
# ==============================================================================
log "1. SEARCH: Verifying the Watsonx Agent exists on the Hub"
step "Searching for FQID: $FQID"
cmd_show matrix search "$FQID" || true
PLAIN_OUT="$CAPTURE_OUT"
cmd_show matrix search "$FQID" --json || true
JSON_OUT="$CAPTURE_OUT"

python3 - "$JSON_OUT" "$PLAIN_OUT" "$FQID" <<'PY' || err "Agent with FQID not found on Hub."
import sys, json, re
json_s, plain_s, fqid = sys.argv[1], sys.argv[2], sys.argv[3]
found = False
try:
    data = json.loads(json_s)
    if isinstance(data, list) and len(data) > 0: found = True
    elif isinstance(data, dict):
        total = data.get("total")
        results = data.get("results") or data.get("items") or data.get("data")
        if (isinstance(total, int) and total > 0) or (isinstance(results, list) and len(results) > 0): found = True
except Exception:
    pass
if not found and (re.search(r"\b" + re.escape(fqid) + r"\b", plain_s, re.I) or re.search(r"\b\d+\s+result", plain_s, re.I)):
    found = True
print("FOUND" if found else "NOT_FOUND")
sys.exit(0 if found else 1)
PY
ok "Agent found on MatrixHub."

# ==============================================================================
# 2) INSTALL (idempotent; never aborts if alias exists)
# ==============================================================================
log "2. INSTALL: Setting up local alias for the agent"
step "This links the alias and materializes the runner via v2 manifest."
if alias_exists; then
  if [[ "$RECREATE" == "1" ]]; then
    warn "Alias '$ALIAS' exists; RECREATE=1 → uninstalling then reinstalling."
    matrix stop "$ALIAS" --quiet >/dev/null 2>&1 || true
    matrix uninstall "$ALIAS" --yes --quiet >/dev/null 2>&1 || true
  else
    warn "Alias '$ALIAS' already exists — reusing existing installation."
  fi
fi

cmd_show matrix install "$FQID" --alias "$ALIAS" || true
INSTALL_OUT="$CAPTURE_OUT"

if grep -qi "already exists" <<< "$INSTALL_OUT"; then
  ok "Alias already present: $ALIAS (reuse)."
else
  ok "Installed alias: $ALIAS"
fi
printf "${C_DIM}%s${C0}\n" "Install result summary: $(echo "$INSTALL_OUT" | tail -n 3 | tr '\n' ' ')"

# Runner location
RUN_DIR="$RUN_DIR_ALIAS"; [ -d "$RUN_DIR" ] || RUN_DIR="$RUN_DIR_ID"
RUNNER_JSON="$RUN_DIR/runner.json"
printf "${C_DIM}Runner path candidate: %s${C0}\n" "$RUNNER_JSON"

# Copy .env for python-dotenv discovery
copy_env_files "$RUN_DIR" "$RUN_DIR/src/watsonx-mcp"

# Patch runner.json if needed (idempotent)
if [[ -f "$RUNNER_JSON" ]]; then
  python3 - "$RUNNER_JSON" <<'PY'
import json,sys,os
p=sys.argv[1]
try:
    with open(p,"r",encoding="utf-8") as f: data=json.load(f)
except Exception:
    sys.exit(0)
t=(data.get("type") or "").lower()
if t in ("python","process","node"):
    # prefer local .env if present; else keep/insert project one
    envfile=".env" if os.path.exists(os.path.join(os.path.dirname(p), ".env")) else data.get("envfile") or "src/watsonx-mcp/.env"
    data.setdefault("envfile", envfile)
    env=data.setdefault("env",{})
    env.setdefault("PORT", os.environ.get("PORT","6288"))
    with open(p,"w",encoding="utf-8") as f: json.dump(data,f,indent=2)
print("OK")
PY
  ok "runner.json patched to reference envfile (if applicable)."
else
  if [[ "$FALLBACK_BOOTSTRAP" != "1" ]]; then
    err "runner.json not found at $RUN_DIR. Re-run with --manifest or set FALLBACK_BOOTSTRAP=1."
  fi
  warn "runner.json not found; creating a minimal python runner as fallback."
  SRC_DIR="$RUN_DIR/src/watsonx-mcp"; mkdir -p "$SRC_DIR"
  cat >"$SRC_DIR/runner_boot.py" <<'PY'
import os, sys, runpy, pathlib
root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root))
os.environ.setdefault("WATSONX_AGENT_PORT", os.environ.get("PORT", "6288"))
for mod in ("watsonx_mcp.server","watsonx_mcp","watsonx_mcp.__main__"):
  try:
    runpy.run_module(mod, run_name="__main__"); raise SystemExit(0)
  except ModuleNotFoundError:
    pass
raise SystemExit("Could not import watsonx_mcp* entrypoint")
PY
  cat >"$RUNNER_JSON" <<EOF
{
  "type": "python",
  "entry": "src/watsonx-mcp/runner_boot.py",
  "python": { "venv": "src/watsonx-mcp/.venv" },
  "envfile": ".env",
  "env": { "PORT": "$PORT", "WATSONX_AGENT_PORT": "$PORT" },
  "health": { "path": "/health" },
  "sse": { "endpoint": "/sse" }
}
EOF
  ok "Fallback runner written → $RUNNER_JSON"
fi
printf "${C_DIM}Runner path: %s${C0}\n" "$RUNNER_JSON"

# ==============================================================================
# 3) RUN
# ==============================================================================
log "3. RUN: Starting the Watsonx Agent"
step "Ensuring port ${PORT} is available…"; free_port "$PORT"

step "Checking for stale locks (will overwrite if present)…"
cmd_show matrix stop "$ALIAS" --quiet || true
clear_alias_locks

ENV_PREFIX=()
for k in WATSONX_API_KEY WATSONX_URL WATSONX_PROJECT_ID WATSONX_SPACE_ID WATSONX_REGION; do
  v="${!k:-}"; [[ -n "$v" ]] && ENV_PREFIX+=("$k=$v")
done

step "Launching agent (capturing the actual bound port)…"
if [[ ${#ENV_PREFIX[@]} -gt 0 ]]; then
  CAPTURE_OUT=$(env "${ENV_PREFIX[@]}" matrix run "$ALIAS" --port "$PORT" 2>&1 || true)
else
  cmd_show matrix run "$ALIAS" --port "$PORT" || true
fi
RUN_OUT="$CAPTURE_OUT"

# Handle lock conflicts gracefully (retry once)
if is_lock_error "$RUN_OUT"; then
  warn "Detected lock conflict; removing old lockfile(s) and retrying once…"
  clear_alias_locks
  if [[ ${#ENV_PREFIX[@]} -gt 0 ]]; then
    CAPTURE_OUT=$(env "${ENV_PREFIX[@]}" matrix run "$ALIAS" --port "$PORT" 2>&1 || true)
  else
    cmd_show matrix run "$ALIAS" --port "$PORT" || true
  fi
  RUN_OUT="$CAPTURE_OUT"
fi

printf "${C_DIM}%s${C0}\n" "$RUN_OUT"

# Port parsing is tolerant to formats: “Port: NNNN” or URL lines.
ACTUAL_PORT="$(grep -Eo 'Port: [0-9]+' <<< "$RUN_OUT" | awk '{print $2}' || true)"
if [[ -z "${ACTUAL_PORT:-}" ]]; then
  ACTUAL_PORT="$(ps_port_for "$ALIAS" || true)"
fi
ACTUAL_PORT="${ACTUAL_PORT:-$PORT}"
ok "Agent process launch reported port: ${ACTUAL_PORT}"
step "Note: v0.1.5 prints a smart quickstart banner after startup."

# ==============================================================================
# 4) VALIDATE
# ==============================================================================
log "4. VALIDATE: Waiting for server to become ready"
if ! wait_health "$ACTUAL_PORT"; then
  printf "${C_DIM}Recent logs:${C0}\n"; matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
  err "Timed out waiting for readiness."
fi

# ==============================================================================
# 5) INTERACT (New UX: help + do + probe + call)
# ==============================================================================
log "5. INTERACT: Discover and Talk to the Agent"

# 5a. Human-friendly help
step "List available tools (schema-aware)"
cmd_show matrix help "$ALIAS" || true

DEFAULT_TOOL="$(first_tool_for "$ALIAS" || true)"; [[ -z "${DEFAULT_TOOL:-}" ]] && DEFAULT_TOOL="chat"
step "Detailed usage for the primary tool → ${DEFAULT_TOOL}"
cmd_show matrix help "$ALIAS" --tool "$DEFAULT_TOOL" || true

BASE_URL="http://127.0.0.1:${ACTUAL_PORT}"
SSE_URL="${BASE_URL}/sse/"

# 5b. One-shot ask via `matrix do` (result in WHITE)
step "One-shot ask (no JSON) via 'matrix do' (text → primary input)"
cmd_spin_capture matrix do "$ALIAS" "$QUESTION" || true
print_do_with_white "$CAPTURE_OUT"

# 5c. Probe (classic)
step "Probe over SSE (classic, shows tools and connection)"
cmd_show matrix mcp probe --url "$SSE_URL" --timeout 8 || true
printf "${C_DIM}%s${C0}\n" "Probe summary: $(echo "$CAPTURE_OUT" | head -n 2 | tr '\n' ' ')"

# 5d. Call with strict JSON (LLM result in WHITE)
step "Call '${DEFAULT_TOOL}' with strict JSON (CI parity)"
PAYLOAD="$(python3 - <<PY
import json,sys
print(json.dumps({"query": sys.argv[1]}))
PY
"$QUESTION")"
cmd_spin_capture matrix mcp call "$DEFAULT_TOOL" --url "$SSE_URL" --args "$PAYLOAD" || true
print_call_with_white "$CAPTURE_OUT"

# 5e. Call with --text (LLM result in WHITE)
step "Call '${DEFAULT_TOOL}' with --text (zero-JSON, schema-aware)"
cmd_spin_capture matrix mcp call "$DEFAULT_TOOL" --url "$SSE_URL" --text "$QUESTION" || true
print_call_with_white "$CAPTURE_OUT"

# 5f. Follow-up ask
step "Follow-up: ask for the top places to visit in Genoa (nearby highlights)"
cmd_spin_capture matrix mcp call "$DEFAULT_TOOL" --url "$SSE_URL" --text "$FOLLOWUP" || true
print_call_with_white "$CAPTURE_OUT"

# 5g. (Optional) Beta REPL
if [[ "${ENABLE_CHAT:-0}" == "1" ]] && matrix chat --help >/dev/null 2>&1; then
  step "Interactive chat (beta): type then /quit"
  { printf "%s\n/quit\n" "$FOLLOWUP" | cmd_show matrix chat "$ALIAS" || true; } 2>/dev/null
else
  warn "Skipping chat REPL (set ENABLE_CHAT=1 to enable)."
fi

ok "Interaction complete."

# ==============================================================================
# 5+) INTERACT (Advanced): Raw probe/call + Chat beta
# ==============================================================================
log "5+. INTERACT: Probing and Calling the Agent via MCP (advanced)"
BASE_URL="http://127.0.0.1:${ACTUAL_PORT}"
SSE_URL="${BASE_URL}/sse/"

step "Probing available tools…"
cmd_show matrix mcp probe --url "$SSE_URL" --timeout 8 || true
printf "${C_DIM}%s${C0}\n" "Probe summary: $(echo "$CAPTURE_OUT" | head -n 2 | tr '\n' ' ')"

step "Calling 'chat' with a question…"
PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$QUESTION")"
cmd_spin_capture matrix mcp call chat --url "$SSE_URL" --args "$PAYLOAD" || true
# Print raw captured output without special coloring
printf "%s\n" "$CAPTURE_OUT"
ok "Advanced MCP interaction complete."

# (Optional) Advanced Chat beta (separate flag to avoid duplicate runs)
if [[ "${ENABLE_CHAT_ADV:-0}" == "1" ]] && matrix chat --help >/dev/null 2>&1; then
  step "Advanced chat REPL (beta): type then /quit"
  { printf "%s\n/quit\n" "$QUESTION" | cmd_show matrix chat "$ALIAS" || true; } 2>/dev/null
else
  warn "Advanced chat REPL skipped (set ENABLE_CHAT_ADV=1 to enable)."
fi

# ==============================================================================
# 6) TEARDOWN
# ==============================================================================
log "6. TEARDOWN: Stopping and cleaning up the agent"
cmd_show matrix stop "$ALIAS" --quiet || true
printf "${C_DIM}%s${C0}\n" "Stop result: $(echo "$CAPTURE_OUT" | tail -n 1)"

# Uninstall handled by trap
sleep 1

printf "\n"; ok "Product Demo PoC Concluded Successfully. ✨"
