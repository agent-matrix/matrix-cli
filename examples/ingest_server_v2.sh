#!/usr/bin/env bash
# examples/ingest_server_v2.sh
# ──────────────────────────────────────────────────────────────────────────────
# MatrixHub • Watsonx MCP v2 — Install, Run, and Query (no admin endpoints)
# - Fetch v2 manifest
# - Install locally with repo + runner (process runner preferred)
# - Ensure runner.json exists (connector fallback only if missing)
# - Start on fixed port, wait /health, probe, and call `chat` about Genoa
# - Idempotent, non-interactive, jq-free, Matrix-styled colors
# ──────────────────────────────────────────────────────────────────────────────
set -Eeuo pipefail

# ===== Matrix-style colors =====
C0="\033[0m"
C_HEAD="\033[38;5;48m"      # neon green
C_DIM="\033[2m"
C_ACC="\033[38;5;39m"       # cyan-blue
C_OK="\033[1;38;5;82m"      # bright green
C_WARN="\033[1;38;5;214m"   # amber
C_ERR="\033[1;38;5;196m"    # red
C_BOLD="\033[1m"

hr()   { printf "${C_DIM}──────────────────────────────────────────────────────────────────────────────${C0}\n"; }
say()  { printf "${C_ACC}●${C0} %s\n" "$*"; }
ok()   { printf "${C_OK}✓${C0} %s\n" "$*"; }
warn() { printf "${C_WARN}⚠${C0} %s\n" "$*"; }
die()  { printf "${C_ERR}✗ %s${C0}\n" "$*" >&2; exit 1; }
step() { printf "\n${C_HEAD}▶ %s${C0}\n" "$*"; }

# ===== Config (override via env) =====
HUB_BASE="${HUB_BASE:-https://api.matrixhub.io}"

# v2 manifest with embedded connector (we still prefer a process runner via runner.json + repo)
MANIFEST_URL="${MANIFEST_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/manifests/watsonx.manifest-v2.json}"

# FQID + alias
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
ALIAS="${ALIAS:-watsonx-agent}"

# Process-runner hints (so `matrix run` starts a real server)
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"

# Fixed local demo port
PORT="${PORT:-6288}"

# SSE endpoint we will probe/call (always with trailing slash)
SSE_URL_DEFAULT="http://127.0.0.1:${PORT}/sse/"
SSE_URL="${SSE_URL:-$SSE_URL_DEFAULT}"

# Demo question
QUESTION="${QUESTION:-Tell me about Genoa, a historic port city in Italy}"

# Timeouts
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"  # seconds
CURL_TIMEOUT="${CURL_TIMEOUT:-15}"

# ===== Preflight =====
need() { command -v "$1" >/dev/null 2>&1 || die "Missing dependency: $1"; }
need curl
need matrix

# watsonx requires credentials; fail fast so call succeeds
if [[ ! -f ".env" ]]; then
  die "No .env found in current directory. Please provide WATSONX_API_KEY, WATSONX_URL, WATSONX_PROJECT_ID."
fi

export MATRIX_BASE_URL="${HUB_BASE}"
export MATRIX_SDK_ALLOW_MANIFEST_FETCH=1
export MATRIX_SDK_RUNNER_SEARCH_DEPTH=3

# ===== Paths =====
HOME_DIR="${HOME:-$PWD}"
RUN_ROOT="${HOME_DIR}/.matrix/runners"
AGENT_ID="$(printf "%s" "$FQID" | sed -n 's/^mcp_server:\([^@]*\)@.*/\1/p')"
VERSION="$(printf "%s" "$FQID" | sed -n 's/.*@\([0-9][^ ]*\)$/\1/p')"
TARGET_DIR="${RUN_ROOT}/${AGENT_ID}/${VERSION}"
RUNNER_JSON="${TARGET_DIR}/runner.json"
ENV_FILE="${TARGET_DIR}/.env"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# ===== Helpers =====
json_escape() { # Minimal JSON escaper
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}
ensure_trailing_slash() {
  case "$1" in */) printf "%s" "$1" ;; *) printf "%s/" "$1" ;; esac
}
free_port() {
  local p="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti TCP:"$p" -sTCP:LISTEN || true)"
    if [ -n "$pids" ]; then
      warn "Port $p busy → stopping alias and killing listeners: $pids"
      matrix stop "$ALIAS" >/dev/null 2>&1 || true
      sleep 0.3
      pids="$(lsof -ti TCP:"$p" -sTCP:LISTEN || true)"
      [ -n "$pids" ] && kill -9 $pids || true
      sleep 0.3
    fi
  elif command -v fuser >/dev/null 2>&1; then
    if fuser -n tcp "$p" >/dev/null 2>&1; then
      warn "Port $p busy → stopping alias and killing with fuser"
      matrix stop "$ALIAS" >/dev/null 2>&1 || true
      fuser -k -n tcp "$p" || true
      sleep 0.3
    fi
  fi
}
wait_ready() {
  local base="http://127.0.0.1:${PORT}"
  local health="${base}/health"
  local until=$(( $(date +%s) + READY_MAX_WAIT ))
  printf "${C_DIM}   waiting"; local dots=0
  while [ "$(date +%s)" -lt "$until" ]; do
    if curl -fsS --max-time 2 "$health" >/dev/null 2>&1; then
      printf "\n${C0}"
      ok "Server healthy at ${health}"
      return 0
    fi
    printf "."
    dots=$((dots+1))
    if [ $dots -ge 40 ]; then printf "\n${C_DIM}   waiting"; dots=0; fi
    sleep 2
  done
  printf "\n${C0}"
  return 1
}

# ===== Banner =====
hr
printf "${C_HEAD}${C_BOLD}MatrixHub • Watsonx MCP v2 — Ingest & Run${C0}\n"
hr
say "Hub:        ${HUB_BASE}"
say "Manifest:   ${MANIFEST_URL}"
say "FQID/Alias: ${FQID} / ${ALIAS}"
say "SSE URL:    ${SSE_URL}"
hr

# ===== 1) Fetch manifest (no jq) =====
step "Fetching manifest (v2)"
MF="$TMP_DIR/manifest.json"
curl -fsSL --max-time "$CURL_TIMEOUT" "$MANIFEST_URL" -o "$MF" || die "Failed to download manifest from ${MANIFEST_URL}"
ok "Manifest downloaded."

# ===== 2) Stop old process / free port / uninstall alias mapping (idempotent) =====
step "Preparing environment"
matrix stop "$ALIAS" >/dev/null 2>&1 || true
free_port "$PORT"
# Uninstall alias mapping quietly; ignore failure
matrix uninstall "$ALIAS" -y >/dev/null 2>&1 || true
ok "Clean slate ready."

# ===== 3) Install with process runner hints (repo + runner) =====
step "Installing locally (manifest + runner-url + repo-url)"
# This ensures a process runner is created (not just connector), so `matrix run` actually starts a server.
matrix install "$FQID" \
  --alias "$ALIAS" \
  --hub "$HUB_BASE" \
  --manifest "$MF" \
  --runner-url "$RUNNER_URL" \
  --repo-url "$REPO_URL" \
  --force --no-prompt \
  >/dev/null || warn "matrix install returned non-zero; continuing."

# ===== 4) Ensure runner.json exists; prefer process runner, fallback to connector only if missing =====
step "Ensuring runner.json exists"
mkdir -p "$TARGET_DIR"
if [[ ! -f "$RUNNER_JSON" ]]; then
  SSE_URL="$(ensure_trailing_slash "$SSE_URL")"
  cat >"$RUNNER_JSON" <<EOF
{
  "type": "connector",
  "integration_type": "MCP",
  "request_type": "SSE",
  "url": "$(json_escape "${SSE_URL%/}")",
  "endpoint": "/sse",
  "headers": {}
}
EOF
  ok "runner.json created (connector fallback) → ${RUNNER_JSON}"
else
  ok "runner.json already present (process runner expected)."
fi

# ===== 5) Copy credentials into runner dir =====
if [[ -f ".env" ]]; then
  cp -f ".env" "$ENV_FILE"
  ok "Copied .env → ${ENV_FILE}"
fi

# ===== 6) Start server on fixed port =====
step "Starting '${ALIAS}' on port ${PORT}"
matrix run "$ALIAS" --port "$PORT" >/dev/null || die "Failed to start '${ALIAS}'"

# Detect if alias exposes a port (connector-only would not)
if ! matrix ps --plain 2>/dev/null | awk -v a="$ALIAS" '$1==a && $3 ~ /^[0-9]+$/' | grep -q .; then
  warn "Alias does not report an exposed port (may be connector-only). Continuing with URL-based health probe."
fi

# ===== 7) Wait for readiness =====
step "Waiting for readiness (health probe)"
if ! wait_ready; then
  matrix logs "$ALIAS" 2>/dev/null | tail -n 160 || true
  die "Timed out waiting for readiness."
fi

# ===== 8) Probe SSE =====
step "Probing MCP transport"
SSE_URL="$(ensure_trailing_slash "$SSE_URL")"
if matrix mcp probe --url "$SSE_URL" --timeout 6 >/dev/null 2>&1; then
  ok "Probe OK."
else
  warn "Probe failed; retrying with longer timeout…"
  if ! matrix mcp probe --url "$SSE_URL" --timeout 12 >/dev/null 2>&1; then
    matrix logs "$ALIAS" 2>/dev/null | tail -n 160 || true
    die "Probe failed."
  fi
  ok "Probe OK (retry)."
fi

# ===== 9) Call chat tool =====
step "Calling 'chat' with a question about Genoa"
ESCQ="$(json_escape "$QUESTION")"
printf "${C_DIM}\$ matrix mcp call chat --url %s --args '{\"query\":\"%s\"}'${C0}\n" "$SSE_URL" "$ESCQ" >&2
matrix mcp call chat --url "$SSE_URL" --args "{\"query\":\"$ESCQ\"}" || {
  matrix logs "$ALIAS" 2>/dev/null | tail -n 160 || true
  die "Chat call failed."
}

hr
ok "Demo complete. Tail logs with: matrix logs ${ALIAS} -f"
hr
