#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Watsonx.ai ⚡ Matrix CLI — WOW Demo (process runner)
#
# This demo:
#   1) Installs the Watsonx MCP spec from Matrix Hub (idempotent).
#   2) Fetches the *official* runner.json from GitHub (python runner).
#   3) Ensures the repo code is present in the runner directory (+venv deps).
#   4) Starts the server with `matrix run` (process mode, not connector).
#   5) Calls the `chat` tool over MCP/SSE.
#   6) Stops and (optionally) uninstalls.
#
# Prereqs:
#   - matrix CLI >= 0.1.2  (and install the MCP extras for probe/call)
#       pip install "matrix-cli[mcp]"
#   - Git available in PATH
#   - Watsonx creds exported in your shell (required to get real answers):
#       export WATSONX_API_KEY=...
#       export WATSONX_URL=...
#       export WATSONX_PROJECT_ID=...
#
# Usage:
#   chmod +x watsonx-matrix-cli-wow.sh
#   ./watsonx-matrix-cli-wow.sh --question "Tell me about Genoa"
#
# Tunables:
#   --hub URL          (default: https://api.matrixhub.io)
#   --alias NAME       (default: watsonx-chat)
#   --fqid ID          (default: mcp_server:watsonx-agent@0.1.0)
#   --runner-url URL   (default: official GitHub runner.json)
#   --repo-url URL     (default: https://github.com/ruslanmv/watsonx-mcp.git)
#   --question TEXT    (default: "Tell me about Genoa")
#   --keep             (keep files/alias; default behavior is uninstall)
# ----------------------------------------------------------------------------
set -Eeuo pipefail

C_CYAN="\033[1;36m"; C_BLUE="\033[1;34m"; C_GREEN="\033[1;32m"; C_YELLOW="\033[1;33m"; C_RED="\033[1;31m"; C_RESET="\033[0m"
log()  { printf "\n${C_CYAN}▶ %s${C_RESET}\n" "$*"; }
step() { printf "${C_BLUE}• %s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✓ %s${C_RESET}\n" "$*"; }
warn() { printf "${C_YELLOW}! %s${C_RESET}\n" "$*"; }
err()  { printf "${C_RED}✗ %s${C_RESET}\n" "$*"; }
cmd()  { printf "${C_GREEN}$ %s${C_RESET}\n" "$*" >&2; "$@"; }
need() { command -v "$1" >/dev/null 2>&1 || { err "$1 not found in PATH"; exit 1; }; }

# Defaults
HUB="${HUB:-https://api.matrixhub.io}"
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"
QUESTION="${QUESTION:-Tell me about Genoa}"
KEEP="${KEEP:-0}"

# Flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub) HUB="$2"; shift 2;;
    --alias) ALIAS="$2"; shift 2;;
    --fqid) FQID="$2"; shift 2;;
    --runner-url) RUNNER_URL="$2"; shift 2;;
    --repo-url) REPO_URL="$2"; shift 2;;
    --question) QUESTION="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    -h|--help)
      cat <<EOF
Usage: $0 [--hub URL] [--alias NAME] [--fqid ID] [--runner-url URL] [--repo-url URL] [--question TEXT] [--keep]
Defaults: HUB=${HUB}  ALIAS=${ALIAS}  FQID=${FQID}
          RUNNER_URL=${RUNNER_URL}
          REPO_URL=${REPO_URL}
EOF
      exit 0;;
    *) warn "Unknown arg: $1"; shift;;
  esac
done

# Derived paths
VERSION="${FQID##*@}"
RUN_DIR="${HOME}/.matrix/runners/${ALIAS}/${VERSION}"
RUNNER_JSON="${RUN_DIR}/runner.json"

# Checks
need matrix
need git
if ! command -v curl >/dev/null 2>&1; then warn "curl not found — fetching runner.json will fail."; fi
if ! command -v jq >/dev/null 2>&1; then warn "jq not found — JSON validation will be skipped."; fi

printf "\n${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
printf   "${C_CYAN}  Watsonx.ai × Matrix Hub — process‑runner WOW demo${C_RESET}\n"
printf   "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
echo     "Hub:        ${HUB}"
echo     "Alias:      ${ALIAS}"
echo     "FQID:       ${FQID}"
echo     "Runner URL: ${RUNNER_URL}"
echo     "Repo URL:   ${REPO_URL}"

# 1) Install spec (idempotent)
log "Install spec from Matrix Hub"
cmd matrix install "${FQID}" --alias "${ALIAS}" --hub "${HUB}" --force --no-prompt || true
ok "Installed (or already present)."

# 2) Fetch the official runner.json (python runner)
log "Fetch runner.json → ${RUNNER_JSON}"
mkdir -p "${RUN_DIR}"
if [[ -f "${RUNNER_JSON}" ]]; then cp -f "${RUNNER_JSON}" "${RUNNER_JSON}.bak.$(date +%s)" || true; fi
cmd curl -fsSL "${RUNNER_URL}" -o "${RUNNER_JSON}"
if command -v jq >/dev/null 2>&1; then
  typ="$(jq -r '.type // empty' "${RUNNER_JSON}" 2>/dev/null || true)"
  entry="$(jq -r '.entry // empty' "${RUNNER_JSON}" 2>/dev/null || true)"
  [[ "${typ}" == "python" && -n "${entry}" ]] || { err "runner.json did not validate (expect type=python with an entry)."; exit 2; }
fi
ok "runner.json ready (process runner)."

# 3) Ensure repo code is present in RUN_DIR (+ venv deps)
log "Ensure code & venv deps present in ${RUN_DIR}"
if [[ ! -f "${RUN_DIR}/bin/run_watsonx_mcp.py" ]]; then
  step "Code missing → cloning repo into runner directory"
  TMPD="$(mktemp -d)"
  cmd git clone --depth=1 "${REPO_URL}" "${TMPD}"
  if command -v rsync >/dev/null 2>&1; then
    cmd rsync -a --exclude ".git" "${TMPD}/" "${RUN_DIR}/"
  else
    # fallback copy (includes dotfiles)
    ( shopt -s dotglob nullglob; cmd cp -R "${TMPD}"/* "${RUN_DIR}/" )
  fi
  rm -rf "${TMPD}"
else
  ok "Code already present."
fi

# Create venv and install requirements
PY="$(command -v python3 || command -v python || true)"
[[ -n "${PY}" ]] || { err "python not found"; exit 2; }
if [[ ! -x "${RUN_DIR}/.venv/bin/python" ]]; then
  step "Create venv"
  (cd "${RUN_DIR}" && cmd "${PY}" -m venv .venv)
fi
step "Install dependencies"
if [[ -f "${RUN_DIR}/requirements.txt" ]]; then
  (cd "${RUN_DIR}" && cmd ".venv/bin/pip" install -U pip && cmd ".venv/bin/pip" install -r requirements.txt)
else
  (cd "${RUN_DIR}" && cmd ".venv/bin/pip" install -U pip && cmd ".venv/bin/pip" install ibm-watsonx-ai fastmcp starlette uvicorn python-dotenv)
fi

# Hint if Watsonx creds are not set
missing=()
[[ -z "${WATSONX_API_KEY:-}" ]] && missing+=(WATSONX_API_KEY)
[[ -z "${WATSONX_URL:-}" ]] && missing+=(WATSONX_URL)
[[ -z "${WATSONX_PROJECT_ID:-}" ]] && missing+=(WATSONX_PROJECT_ID)
if (( ${#missing[@]} > 0 )); then
  warn "Missing env: ${missing[*]} — the server will not answer real questions until set."
fi

# 4) Start via matrix run (process mode)
log "Start server (process runner)"
cmd matrix run "${ALIAS}" || true
sleep 2

# Determine URL from ps --json
URL=""
if command -v jq >/dev/null 2>&1; then
  psj="$(matrix ps --json 2>/dev/null || echo '[]')"
  URL="$(jq -r --arg a "${ALIAS,,}" '.[] | select((.alias // "" | ascii_downcase) == $a) | .url // empty' <<<"${psj}" | head -n1 || true)"
fi
if [[ -z "${URL}" || "${URL}" == "-" || "${URL}" == "—" || "${URL}" == "N/A" ]]; then
  # fallback: build from port
  PORT="$(matrix ps --plain 2>/dev/null | awk -v a="${ALIAS}" '$1==a{print $3}' | head -n1 || true)"
  if [[ -n "${PORT}" && "${PORT}" =~ ^[0-9]+$ ]]; then
    URL="http://127.0.0.1:${PORT}/sse"
  fi
fi
[[ -n "${URL}" ]] || { err "Could not discover URL from ps; is the server running?"; exit 3; }
ok "Running at: ${URL}"

# Optional: quick probe
if command -v curl >/dev/null 2>&1; then
  log "Probe SSE endpoint"
  cmd curl -sI --max-time 3 "${URL}" || true
fi

# 5) Ask Watsonx
log "Ask Watsonx via MCP (SSE)"
if ! command -v matrix >/dev/null 2>&1; then err "matrix CLI not found"; exit 2; fi
ARGS_JSON="${ARGS_JSON:-}"
if command -v jq >/dev/null 2>&1; then
  ARGS_JSON="$(jq -n --arg q "${QUESTION}" '{query:$q}')"
else
  ARGS_JSON="{\"query\":\"${QUESTION}\"}"
fi
step "Q: ${QUESTION}"
cmd matrix mcp call chat --url "${URL}" --args "${ARGS_JSON}" || true

# 6) Stop & optionally uninstall
log "Stop"
cmd matrix stop "${ALIAS}" || true

if [[ "${KEEP}" = "1" ]]; then
  ok "Keeping installation (requested with --keep)."
else
  log "Uninstall"
  cmd matrix uninstall "${ALIAS}" -y || true
fi

ok "WOW demo complete. ✨"
