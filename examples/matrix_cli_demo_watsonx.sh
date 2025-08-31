#!/usr/bin/env bash
# ==============================================================================
# Matrix CLI — Watsonx Agent End-to-End Demo Script (PoC)
# matrix_cli_demo_watsonx.sh
# Version: v1.3.5 | Date: 2025-08-31
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
err()  { printf "${C_ERR}✗ %s${C0}\n" "$*" >&2; exit 1; }

# Print a command, show a spinner, capture output & status, and show output.
cmd_show() {
  printf "${C_CMD}$ %s${C0}\n" "$*" >&2

  # Start spinner in the background
  (
    local spin_chars="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    while :; do
      for (( i=0; i<${#spin_chars}; i++ )); do
        printf "\r${C_SPIN}${spin_chars:$i:1}${C0}" >&2
        sleep 0.1
      done
    done
  ) &
  local spin_pid=$!

  # Execute the command, capturing output and status
  local tmp; tmp="$(mktemp)"
  set +e
  "$@" >"$tmp" 2>&1
  local st=$?
  set -e

  # Stop the spinner
  kill $spin_pid &>/dev/null
  # Clear the spinner line by overwriting with spaces
  printf "\r%80s\r" " " >&2

  # Process and show the output
  CAPTURE_OUT="$(cat "$tmp")"
  rm -f "$tmp"
  printf "${C_DIM}%s${C0}\n" "$CAPTURE_OUT"
  return $st
}

# Print a command, show a spinner, and capture output, but DO NOT print it.
cmd_spin_capture() {
  printf "${C_CMD}$ %s${C0}\n" "$*" >&2
  (
    local spin_chars="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    while :; do
      for (( i=0; i<${#spin_chars}; i++ )); do
        printf "\r${C_SPIN}${spin_chars:$i:1}${C0}" >&2; sleep 0.1
      done
    done
  ) &
  local spin_pid=$!
  local tmp; tmp="$(mktemp)"
  set +e
  "$@" >"$tmp" 2>&1
  local st=$?
  set -e
  kill $spin_pid &>/dev/null
  printf "\r%80s\r" " " >&2
  CAPTURE_OUT="$(cat "$tmp")"
  rm -f "$tmp"
  return $st
}

need(){ command -v "$1" >/dev/null 2>&1 || err "$1 not found in PATH. Please ensure it is installed."; }
need matrix; need curl; need python3; need grep; need awk; need find

# ─── Configuration ────────────────────────────────────────────────────────────
HUB="${HUB:-https://api.matrixhub.io}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
ALIAS="${ALIAS:-watsonx-demo-agent}"
PORT="${PORT:-6288}"
QUESTION="${QUESTION:-Tell me about Genoa, my current location, focusing on its maritime history.}"
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"

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
  # export everything in .env to this shell
  # shellcheck disable=SC1091
  set -a; source .env; set +a
  ok ".env loaded and exported to the current shell."
else
  warn ".env not found in current directory. If the agent needs WATSONX_* variables, it may fail."
fi

# Helper: copy .env where runners will find it (runner dir and/or src dir)
copy_env_files() {
  local dest="$1" srcdir="$2"
  if [[ -f ".env" ]]; then
    mkdir -p "$dest"
    cp -f ".env" "$dest/.env" && ok "Copied .env → $dest/.env"
    if [[ -n "$srcdir" ]]; then
      mkdir -p "$srcdir"
      cp -f ".env" "$srcdir/.env" && ok "Copied .env → $srcdir/.env"
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
      ok "Agent is healthy at $url"
      return 0
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
    if [ -n "$pids" ]; then
      warn "Port $p busy; killing: $pids"
      kill -9 $pids || true
    fi
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k -n tcp "$p" >/dev/null 2>&1 || true
  fi
}

clear_alias_locks() {
  local removed=0
  local LOCK_DIR="$MATRIX_HOME/locks"
  if [ -d "$LOCK_DIR" ]; then
    for f in "$LOCK_DIR/${ALIAS}.lock" "$LOCK_DIR/${ALIAS}.lck" "$LOCK_DIR/${ALIAS}.pid"; do
      if [ -f "$f" ]; then
        warn "Removing stale lock: $f"
        rm -f "$f" && removed=1
      fi
    done
  fi
  for base in "$RUN_DIR_ALIAS" "$RUN_DIR_ID"; do
    [ -d "$base" ] || continue
    while IFS= read -r -d '' lf; do
      warn "Removing stale lock: $lf"
      rm -f "$lf" && removed=1
    done < <(find "$base" -maxdepth 2 -type f \( -name "*.lock" -o -name "lock" -o -name ".lock" \) -print0 2>/dev/null || true)
  done
  if [ "$removed" -eq 1 ]; then
    ok "Old lockfile(s) were found and overwritten."
  fi
}

is_lock_error() {
  echo "$1" | grep -qiE 'lock file .*already exists|lockfile .*exists|lock.*exists'
}

# ─── Automatic Cleanup ────────────────────────────────────────────────────────
cleanup() {
  printf "\n"
  log "AUTOMATIC CLEANUP"
  step "Ensuring agent '${ALIAS}' is stopped and uninstalled..."
  matrix stop "$ALIAS" --quiet >/dev/null 2>&1 || true
  matrix uninstall "$ALIAS" --yes --quiet >/dev/null 2>&1 || true
  ok "Cleanup complete."
}
trap cleanup EXIT INT TERM

# ==============================================================================
# 1) SEARCH
# ==============================================================================
log "1. SEARCH: Verifying the Watsonx Agent exists on the Hub"
step "Searching for FQID: $FQID"
cmd_show matrix search "$FQID" || true
PLAIN_OUT="$CAPTURE_OUT"
cmd_show matrix search "$FQID" --json || true
JSON_OUT="$CAPTURE_OUT"

if python3 - "$JSON_OUT" "$PLAIN_OUT" "$FQID" <<'PY'
import sys, json, re
json_s, plain_s, fqid = sys.argv[1], sys.argv[2], sys.argv[3]
found = False
try:
    data = json.loads(json_s)
    if isinstance(data, list) and len(data) > 0:
        found = True
    elif isinstance(data, dict):
        total = data.get("total")
        results = data.get("results") or data.get("items") or data.get("data")
        if (isinstance(total, int) and total > 0) or (isinstance(results, list) and len(results) > 0):
            found = True
except Exception:
    pass
if not found:
    if re.search(r"\b" + re.escape(fqid) + r"\b", plain_s, re.I) or re.search(r"\b\d+\s+result", plain_s, re.I):
        found = True
print("FOUND" if found else "NOT_FOUND")
sys.exit(0 if found else 1)
PY
then
  ok "Agent found on MatrixHub."
else
  err "Agent with FQID '$FQID' not found on Hub '$HUB'. Ensure it’s published."
fi

# ==============================================================================
# 2) INSTALL
# ==============================================================================
log "2. INSTALL: Setting up local alias for the agent"
step "This links the alias and materializes the runner via v2 manifest."
cmd_show matrix install "$FQID" \
  --alias "$ALIAS" \
  --manifest "$MANIFEST_URL" \
  --repo-url "$REPO_URL" \
  --force --no-prompt
INSTALL_OUT="$CAPTURE_OUT"
ok "Installed alias: $ALIAS"
printf "${C_DIM}%s${C0}\n" "Install result summary: $(echo "$INSTALL_OUT" | tail -n 3 | tr '\n' ' ')"

# Runner location
RUN_DIR="$RUN_DIR_ALIAS"; [ -d "$RUN_DIR" ] || RUN_DIR="$RUN_DIR_ID"
RUNNER_JSON="$RUN_DIR/runner.json"
printf "${C_DIM}Runner path candidate: %s${C0}\n" "$RUNNER_JSON"

# Copy .env into the runner dir and potential src dir so python-dotenv can find it
copy_env_files "$RUN_DIR" "$RUN_DIR/src/watsonx-mcp"

# If runner.json exists and looks like a process/python runner, add envfile for robustness
if [[ -f "$RUNNER_JSON" ]]; then
  python3 - "$RUNNER_JSON" <<'PY'
import json,sys,os
p=sys.argv[1]
try:
    data=json.load(open(p,"r",encoding="utf-8"))
except Exception:
    sys.exit(0)
t=(data.get("type") or "").lower()
if t in ("python","process"):
    # Prefer .env in runner dir; fallback to src/watsonx-mcp/.env
    envfile=".env" if os.path.exists(os.path.join(os.path.dirname(p), ".env")) else "src/watsonx-mcp/.env"
    if not data.get("envfile"):
        data["envfile"]=envfile
    # ensure PORT present (runner merges with parent env)
    env=data.setdefault("env",{})
    env.setdefault("PORT", os.environ.get("PORT","6288"))
    with open(p,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=2)
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
  except ModuleNotFoundError: pass
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
step "Ensuring port ${PORT} is available…"
free_port "$PORT"

step "Checking for stale locks (will overwrite if present)…"
cmd_show matrix stop "$ALIAS" || true
clear_alias_locks

# Build env prefix (pass WATSONX_* directly to matrix run for extra safety)
ENV_PREFIX=()
for k in WATSONX_API_KEY WATSONX_URL WATSONX_PROJECT_ID WATSONX_SPACE_ID WATSONX_REGION; do
  v="${!k:-}"
  [[ -n "$v" ]] && ENV_PREFIX+=("$k=$v")
done

step "Launching agent (capturing the actual bound port)…"
if [[ ${#ENV_PREFIX[@]} -gt 0 ]]; then
  # This command is executed but not displayed to the user as requested
  CAPTURE_OUT=$(env "${ENV_PREFIX[@]}" matrix run "$ALIAS" --port "$PORT" 2>&1 || true)
else
  cmd_show matrix run "$ALIAS" --port "$PORT" || true
fi
RUN_OUT="$CAPTURE_OUT"

# If lock error, clear and retry once
if echo "$RUN_OUT" | grep -qiE 'lock file .*already exists|lockfile .*exists|lock.*exists'; then
  warn "Detected lock conflict; removing old lockfile(s) and retrying once…"
  clear_alias_locks
  if [[ ${#ENV_PREFIX[@]} -gt 0 ]]; then
    # This command is executed but not displayed to the user as requested
    CAPTURE_OUT=$(env "${ENV_PREFIX[@]}" matrix run "$ALIAS" --port "$PORT" 2>&1 || true)
  else
    cmd_show matrix run "$ALIAS" --port "$PORT" || true
  fi
  RUN_OUT="$CAPTURE_OUT"
fi

printf "${C_DIM}%s${C0}\n" "$RUN_OUT"
ACTUAL_PORT="$(printf "%s\n" "$RUN_OUT" | grep -Eo 'Port: [0-9]+' | awk '{print $2}')"
ACTUAL_PORT="${ACTUAL_PORT:-$PORT}"
ok "Agent process launch reported port: ${ACTUAL_PORT}"

# ==============================================================================
# 4) VALIDATE
# ==============================================================================
log "4. VALIDATE: Waiting for server to become ready"
if ! wait_health "$ACTUAL_PORT"; then
  printf "${C_DIM}Recent logs:${C0}\n"
  matrix logs "$ALIAS" 2>/dev/null | tail -n 120
  err "Timed out waiting for readiness."
fi

# ==============================================================================
# 5) INTERACT
# ==============================================================================
log "5. INTERACT: Probing and Calling the Agent via MCP"
BASE_URL="http://127.0.0.1:${ACTUAL_PORT}"
SSE_URL="${BASE_URL}/sse/"
step "Probing available tools…"
cmd_show matrix mcp probe --url "$SSE_URL" --timeout 8 || true
printf "${C_DIM}%s${C0}\n" "Probe summary: $(echo "$CAPTURE_OUT" | head -n 2 | tr '\n' ' ')"

step "Calling 'chat' with a question…"
PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"query": sys.argv[1]}))' "$QUESTION")"
cmd_spin_capture matrix mcp call chat --url "$SSE_URL" --args "$PAYLOAD"
# Print the captured output without any special coloring (i.e., in "white")
printf "%s\n" "$CAPTURE_OUT"
ok "Interaction complete."

# ==============================================================================
# 6) TEARDOWN
# ==============================================================================
log "6. TEARDOWN: Stopping and cleaning up the agent"
cmd_show matrix stop "$ALIAS" || true
printf "${C_DIM}%s${C0}\n" "Stop result: $(echo "$CAPTURE_OUT" | tail -n 1)"

# Uninstall handled by trap
sleep 1

# ==============================================================================
# ▮▮▮                               END OF DEMO                                ▮▮▮
# ==============================================================================
printf "\n"; ok "Product Demo PoC Concluded Successfully. ✨"