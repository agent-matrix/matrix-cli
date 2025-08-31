#!/usr/bin/env bash
# examples/ingest_watsonx_demo_v2.sh
# MatrixHub Ingestion PoC (v2) — Install, Run, and Query
# - Installs from v2 manifest (runner provided by Hub/SDK)
# - Only writes our own PYTHON runner if none exists
# - Starts on a fixed port, but detects actual port from CLI output
# - Waits for /health or SSE, prints logs on failure
# - Calls `chat` with a safely JSON-encoded query about Genova
set -Eeuo pipefail

# ── Matrix-y colors ────────────────────────────────────────────────────────────
C0="\033[0m"; C_HEAD="\033[38;5;48m"; C_DIM="\033[2m"
C_OK="\033[1;38;5;82m"; C_WARN="\033[1;38;5;214m"; C_ERR="\033[1;38;5;196m"
C_BOLD="\033[1m"; C_SPIN="\033[38;5;82m"

# ✨ FIX: New function to display a short spinner animation
animate_wait() {
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local delay=0.1
    # Animate for a short, fixed duration (~0.8s) to give an appearance of loading
    for j in {1..8}; do
        local i=$(( j % ${#spin} ))
        printf "\r${C_SPIN}  %s${C0}" "${spin:$i:1}"
        sleep "$delay"
    done
    printf "\r \r" # Erase the spinner line
}

hr(){ printf "${C_DIM}────────────────────────────────────────────────────────${C0}\n"; }
say(){ printf "• %s\n" "$*"; }
ok(){ printf "${C_OK}✓ %s${C0}\n" "$*"; }
warn(){ printf "${C_WARN}⚠ %s${C0}\n" "$*"; }
die(){ printf "\n${C_ERR}✗ %s${C0}\n" "$*" >&2; exit 1; }
title(){ printf "\n${C_HEAD}${C_BOLD}▮ %s ▮${C0}\n" "$*"; }

# ✨ FIX: Modified run functions to call the waiting animation after execution
run() {
    printf "${C_DIM}$ %s${C0}\n" "$(printf '%q ' "$@")"
    "$@"
    animate_wait
}
run_cap(){
    printf "${C_DIM}$ %s${C0}\n" "$(printf '%q ' "$@")"
    "$@" 2>&1 | tee "$TMP_DIR/capture.out"
    animate_wait
}

# ── Config (env-overridable) ───────────────────────────────────────────────────
HUB="${HUB:-https://api.matrixhub.io}"
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
MANIFEST_URL="${MANIFEST_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/manifests/watsonx.manifest-v2.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"

PORT="${PORT:-6288}"
SSE_PATH="${SSE_PATH:-/sse}"                   # change to /messages if your server uses that
READY_MAX_WAIT="${READY_MAX_WAIT:-90}"         # seconds
CURL_TIMEOUT="${CURL_TIMEOUT:-15}"
QUESTION="${QUESTION:-Tell me about Genoa (Genova), a historic port city in Italy.}"

# ── Deps ───────────────────────────────────────────────────────────────────────
need(){ command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }
need matrix; need curl; need git; need python3; need yes; need awk; need grep

export MATRIX_BASE_URL="$HUB"
export MATRIX_SDK_ALLOW_MANIFEST_FETCH=1
export MATRIX_SDK_RUNNER_SEARCH_DEPTH=3

# ── Paths (no sed: pure Bash) ──────────────────────────────────────────────────
MATRIX_HOME="${MATRIX_HOME:-$HOME/.matrix}"
temp_fqid="${FQID#mcp_server:}"; AGENT_ID="${temp_fqid%@*}"; VERSION="${FQID##*@}"
RUN_DIR="${MATRIX_HOME}/runners/${ALIAS}/${VERSION}"         # CLI uses alias-based path
# Fallback path if needed (older CLIs may use id-based path):
ALT_RUN_DIR="${MATRIX_HOME}/runners/${AGENT_ID}/${VERSION}"
SRC_DIR="${RUN_DIR}/src/watsonx-mcp"
RUNNER_JSON="${RUN_DIR}/runner.json"
ENV_FILE="${RUN_DIR}/.env"

TMP_DIR="$(mktemp -d)"; trap 'rm -rf "$TMP_DIR"' EXIT

ensure_trailing_slash(){ case "$1" in */) printf "%s" "$1";; *) printf "%s/" "$1";; esac; }
json_payload(){ python3 - "$QUESTION" <<'PY'
import json,sys
print(json.dumps({"query": sys.argv[1]}))
PY
}

wait_ready() {
    # Accepts port as $1
    local port="$1"; local base="http://127.0.0.1:${port}"
    local health="${base}/health"; local until=$(( $(date +%s) + READY_MAX_WAIT ))
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'; local i=0
    printf "${C_DIM}• Waiting up to %ss for %s or SSE … ${C0}\n" "$READY_MAX_WAIT" "$health"
    while [ "$(date +%s)" -lt "$until" ]; do
        if curl -fsS --max-time 2 "$health" >/dev/null 2>&1 \
            || matrix mcp probe --url "$(ensure_trailing_slash "${base}${SSE_PATH%/}")" --timeout 3 >/dev/null 2>&1; then
            printf "\r"; ok "Server ready at ${base}${SSE_PATH%/}/"
            echo "$port" > "$TMP_DIR/port.ok"
            return 0
        fi
        i=$(( (i+1) % ${#spin} )); printf "\r${C_SPIN}  %s${C0}" "${spin:$i:1}"; sleep 0.20
    done
    printf "\r"; return 1
}

# ── Banner ─────────────────────────────────────────────────────────────────────
title "MatrixHub Ingestion PoC"
say "Hub:        $HUB"
say "Manifest:   $MANIFEST_URL"
say "Alias/FQID: $ALIAS / $FQID"
say "Desired port: $PORT  (SSE path: $SSE_PATH)"
hr

# ── 1) Credentials ─────────────────────────────────────────────────────────────
title "Check watsonx credentials"
if [ -f ".env" ]; then ok "Loaded .env"; else die "Create .env with WATSONX_API_KEY, WATSONX_URL, WATSONX_PROJECT_ID"; fi
if ! grep -q '^WATSONX_API_KEY=' .env 2>/dev/null; then warn "WATSONX_API_KEY missing in .env"; fi
ok "Credentials present"

# ── 2) Install from v2 manifest (runner comes from Hub/SDK) ────────────────────
title "Install agent from v2 manifest"
MF="$TMP_DIR/manifest.json"
run curl -fsSL --max-time "$CURL_TIMEOUT" "$MANIFEST_URL" -o "$MF"
# non-interactive overwrite
run bash -lc "yes | matrix install '$FQID' --alias '$ALIAS' --manifest '$MF' --repo-url '$REPO_URL' --force --no-prompt >/dev/null || true"
ok "Installed/updated alias: $ALIAS"

# Resolve final run directory (alias-first, else id-based)
[ -d "$RUN_DIR" ] || RUN_DIR="$ALT_RUN_DIR"
SRC_DIR="${RUN_DIR}/src/watsonx-mcp"
RUNNER_JSON="${RUN_DIR}/runner.json"
ENV_FILE="${RUN_DIR}/.env"

# Copy creds so restarts survive
mkdir -p "$RUN_DIR"
if [ -f "$ENV_FILE" ]; then
    warn "Runner .env already exists at $ENV_FILE — keeping it"
else
    run cp -f .env "$ENV_FILE"; ok "Persisted creds to $ENV_FILE"
fi

# ── 3) Only if runner.json is missing, create robust PYTHON runner ─────────────
title "Ensure runner exists"
if [ ! -f "$RUNNER_JSON" ]; then
    warn "No runner.json found — creating a fallback PYTHON runner"
    mkdir -p "$SRC_DIR"
    # clone sources if not present (helps imports)
    if [ ! -d "$SRC_DIR/.git" ]; then
        run git clone --depth 1 "$REPO_URL" "$SRC_DIR"
    fi
    # venv only if missing
    if [ ! -x "$SRC_DIR/.venv/bin/python" ]; then
        run python3 -m venv "$SRC_DIR/.venv"
        run bash -lc "source '$SRC_DIR/.venv/bin/activate' && pip install --upgrade pip setuptools wheel && pip install -e '$SRC_DIR' || true"
    fi
    # bootstrap that injects repo path for imports and tries multiple modules
    BOOT_PY="$SRC_DIR/runner_boot.py"
    cat >"$BOOT_PY" <<'PY'
import os, sys, runpy, pathlib
root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root))          # so 'import watsonx_mcp' can find repo code if editable install failed
os.environ.setdefault("WATSONX_AGENT_PORT", os.environ.get("PORT", "6288"))
last_exc = None
for mod in ("watsonx_mcp.server", "watsonx_mcp", "watsonx_mcp.__main__"):
    try:
        runpy.run_module(mod, run_name="__main__")
        raise SystemExit(0)
    except ModuleNotFoundError:
        continue
    except SystemExit:
        raise
    except Exception as e:
        last_exc = e
if last_exc:
    raise last_exc
raise SystemExit("Could not import any watsonx_mcp entrypoint")
PY
    cat >"$RUNNER_JSON" <<EOF
{
  "type": "python",
  "entry": "src/watsonx-mcp/runner_boot.py",
  "python": { "venv": "src/watsonx-mcp/.venv" },
  "env": { "PORT": "$PORT", "WATSONX_AGENT_PORT": "$PORT" },
  "health": { "path": "/health" },
  "sse": { "endpoint": "$SSE_PATH" }
}
EOF
    ok "Created fallback runner → $RUNNER_JSON"
else
    ok "Existing runner.json detected → $RUNNER_JSON"
fi

# ── 4) Start and capture actual port ───────────────────────────────────────────
title "Start server"
run matrix stop "$ALIAS" >/dev/null 2>&1 || true
# free desired port if busy (optional)
if command -v lsof >/dev/null 2>&1 && lsof -ti TCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "Port $PORT busy; attempting to free it"
    lsof -ti TCP:"$PORT" -sTCP:LISTEN | xargs -r kill -9 || true
fi
# start and capture output
RUN_OUT="$(run_cap matrix run "$ALIAS" --port "$PORT" || true)"
# parse the actual port printed by CLI (fallback to requested port)
ACTUAL_PORT="$(printf "%s\n" "$RUN_OUT" | grep -Eo 'Port: [0-9]+' | awk '{print $2}' || true)"
ACTUAL_PORT="${ACTUAL_PORT:-$PORT}"
say "Using port: $ACTUAL_PORT"

# ── 5) Wait for readiness on the actual port ───────────────────────────────────
if ! wait_ready "$ACTUAL_PORT"; then
    echo
    matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
    die "Server did not become ready"
fi

# ── 6) Probe & call (safe JSON) ────────────────────────────────────────────────
title "Probe & call (SSE)"
BASE="http://127.0.0.1:${ACTUAL_PORT}"
SSE_URL="$(ensure_trailing_slash "${BASE}${SSE_PATH%/}")"
run matrix mcp probe --url "$SSE_URL" --timeout 8 || warn "Probe failed; continuing to call"

PAYLOAD="$(json_payload)"
printf "${C_DIM}$ matrix mcp call chat --url %q --args %q${C0}\n" "$SSE_URL" "$PAYLOAD"
matrix mcp call chat --url "$SSE_URL" --args "$PAYLOAD"

ok "Done."