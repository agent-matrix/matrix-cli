#!/usr/bin/env bash
# scripts/bash/debuger_matrixhub.sh
# Comprehensive diagnostics for Matrix Hub / Matrix CLI / MCP SSE connectivity.
# - Collects environment, versions, hub/gateway health, runner/lock files, ports
# - Probes SSE endpoint and tries MCP probe/call with matrix CLI (if present)
# - (Optional) uses a tiny Python snippet (if 'mcp' is installed) to list tools & call
# - Captures docker container state/logs if Hub/Gateway run in Docker
#
# Produces a timestamped report under ./debug_reports/ and a .tar.gz bundle.

set -Eeuo pipefail

# -----------------------------
# Pretty output helpers
# -----------------------------
GREEN="\033[0;32m"; YELLOW="\033[1;33m"; BLUE="\033[1;34m"; CYAN="\033[1;36m"; RED="\033[0;31m"; NC="\033[0m"
step(){ printf "\n${CYAN}▶ %s${NC}\n" "$*"; }
info(){ printf "ℹ %s\n" "$*"; }
ok(){ printf "✅ %s\n" "$*"; }
warn(){ printf "${YELLOW}⚠ %s${NC}\n" "$*"; }
err(){ printf "${RED}✖ %s${NC}\n" "$*" >&2; }
show(){ printf "${GREEN}$ %s${NC}\n" "$*"; }
MASK(){ local s="${1:-}"; [[ -z "$s" ]] && { echo "(empty)"; return; }; local n=${#s}; ((n<=6)) && { echo "******"; return; }; printf "%s\n" "${s:0:3}***${s:n-3:3}"; }

# -----------------------------
# Defaults & args
# -----------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Try to load nearest .env (optional)
find_env_up() {
  local d="$1"
  while [[ -n "$d" && "$d" != "/" && "$d" != "." ]]; do
    [[ -f "$d/.env" ]] && { echo "$d/.env"; return 0; }
    d="$(dirname "$d")"
  done
  return 1
}
ENV_FILE="${ENV_FILE:-"$(find_env_up "$SCRIPT_DIR" || true)"}"
if [[ -n "${ENV_FILE:-}" && -f "$ENV_FILE" ]]; then
  info "Loading .env from $ENV_FILE"
  # shellcheck disable=SC1090
  set +u; set -a; source "$ENV_FILE"; set +a; set -u
fi

# User tunables (safe defaults)
ALIAS="${ALIAS:-watsonx-chat}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
URL="${URL:-http://127.0.0.1:6288/sse}"           # target SSE URL to test
HUB="${HUB:-http://127.0.0.1:443}"
HUB_TOKEN="${HUB_TOKEN:-${MATRIX_HUB_TOKEN:-}}"
GW_BASE="${GW_BASE:-http://127.0.0.1:4444}"
GW_TOKEN="${GW_TOKEN:-${MCP_GATEWAY_TOKEN:-}}"

Q1="${Q1:-What is the capital of Italy?}"
Q2="${Q2:-Tell me about Genoa.}"

OUT_PARENT="${OUT_PARENT:-${ROOT_DIR}/debug_reports}"
TS="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="${OUT_DIR:-${OUT_PARENT}/matrixhub_${TS}}"
BUNDLE="${OUT_BUNDLE:-${OUT_PARENT}/matrixhub_${TS}.tar.gz}"

# Feature toggles
NO_DOCKER=0
NO_PY=0
NO_MATRIX=0

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]
  --alias NAME           Alias to inspect (default: ${ALIAS})
  --fqid ID              FQID for reference (default: ${FQID})
  --url URL              SSE URL to probe (default: ${URL})
  --hub URL              Hub base (default: ${HUB})
  --hub-token TOKEN      Hub API token (default: env HUB_TOKEN/MATRIX_HUB_TOKEN)
  --gw URL               Gateway base (default: ${GW_BASE})
  --gw-token TOKEN       Gateway token (default: env GW_TOKEN/MCP_GATEWAY_TOKEN)
  --outdir DIR           Output directory (default: ${OUT_DIR})
  --no-docker            Skip docker checks
  --no-python            Skip Python/mcp client checks
  --no-matrix            Skip matrix CLI checks
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --alias) ALIAS="$2"; shift 2;;
    --fqid) FQID="$2"; shift 2;;
    --url) URL="$2"; shift 2;;
    --hub) HUB="$2"; shift 2;;
    --hub-token) HUB_TOKEN="$2"; shift 2;;
    --gw|--gw-base) GW_BASE="$2"; shift 2;;
    --gw-token) GW_TOKEN="$2"; shift 2;;
    --outdir) OUT_DIR="$2"; shift 2;;
    --no-docker) NO_DOCKER=1; shift;;
    --no-python) NO_PY=1; shift;;
    --no-matrix) NO_MATRIX=1; shift;;
    -h|--help) usage; exit 0;;
    *) err "Unknown arg: $1"; usage; exit 2;;
  esac
done

mkdir -p "${OUT_DIR}"
LOG="${OUT_DIR}/debug.log"
touch "${LOG}"

logwrap(){ tee -a "${LOG}"; }

hdr(){ echo "==== $* ====" | logwrap; }

# -----------------------------
# Quick summary
# -----------------------------
step "Parameters"
{
  echo "Alias:           ${ALIAS}"
  echo "FQID:            ${FQID}"
  echo "SSE URL:         ${URL}"
  echo "Hub:             ${HUB}"
  echo "Hub Token:       $(MASK "${HUB_TOKEN}")"
  echo "Gateway:         ${GW_BASE}"
  echo "GW Token:        $(MASK "${GW_TOKEN}")"
  echo "Output dir:      ${OUT_DIR}"
  echo "Bundle target:   ${BUNDLE}"
} | logwrap

# -----------------------------
# 1) System & env snapshot
# -----------------------------
step "System & environment"
{
  hdr "uname -a"; uname -a || true
  hdr "/etc/os-release"; (command -v cat >/dev/null && cat /etc/os-release) 2>/dev/null || true
  hdr "whoami / pwd"; whoami; pwd

  hdr "Python versions"; (python3 --version || true); (python --version || true)
  hdr "Pip key packages"
  python3 - <<'PY' || true
import importlib, sys
mods = ["matrix_sdk","mcp","mcp.client.sse","anyio","uvicorn","starlette","ibm_watsonx_ai"]
for m in mods:
    try:
        mod = importlib.import_module(m)
        ver = getattr(mod, "__version__", None)
        print(f"{m} = {ver or '(no __version__)'}")
    except Exception as e:
        print(f"{m} = (not installed) [{e}]")
PY

  hdr "Env (masked)"
  for k in MATRIX_HUB_TOKEN MCP_GATEWAY_TOKEN WATSONX_API_KEY WATSONX_URL WATSONX_PROJECT_ID REQUESTS_CA_BUNDLE SSL_CERT_FILE PORT WATSONX_AGENT_PORT; do
    v="${!k-}"; echo "$k=$(MASK "$v")"
  done
} | logwrap

# -----------------------------
# 2) Matrix CLI snapshot
# -----------------------------
if (( NO_MATRIX == 0 )); then
  step "Matrix CLI"
  {
    hdr "matrix --version"; (matrix --version 2>&1 || true)
    hdr "matrix version"; (matrix version 2>&1 || true)
    hdr "matrix help (top)"; (matrix help 2>&1 | head -n 30 || true)
    hdr "matrix connection --json"; (matrix connection --json 2>&1 || true)
    hdr "matrix ps --json"; (matrix ps --json 2>&1 || true)
    hdr "matrix doctor '${ALIAS}'"; (matrix doctor "${ALIAS}" 2>&1 || true)
  } | logwrap
else
  warn "Skipping matrix CLI checks (--no-matrix)"
fi

# -----------------------------
# 3) Runner/lock/alias files
# -----------------------------
step "Local runner & lock"
{
  RUN_BASE="${HOME}/.matrix/runners/${ALIAS}"
  STATE_BASE="${HOME}/.matrix/state/${ALIAS}"

  hdr "Runner tree (if exists)"
  if [[ -d "$RUN_BASE" ]]; then
    (cd "${RUN_BASE}" && find . -maxdepth 3 -type f | sort)
  else
    echo "No directory: ${RUN_BASE}"
  fi

  hdr "runner.json candidates"
  if ls "${RUN_BASE}"/**/runner.json 1>/dev/null 2>&1; then
    for f in "${RUN_BASE}"/**/runner.json; do
      echo "--- ${f} ---"
      sed -n '1,200p' "$f"
    done
  else
    echo "No runner.json found under ${RUN_BASE}"
  fi

  hdr "Lock file (if any)"
  if [[ -f "${STATE_BASE}/runner.lock.json" ]]; then
    sed -n '1,200p' "${STATE_BASE}/runner.lock.json"
  else
    echo "No lock file: ${STATE_BASE}/runner.lock.json"
  fi
} | logwrap

# -----------------------------
# 4) Ports & processes
# -----------------------------
step "Ports & processes"
{
  PORT_FROM_URL="$(echo "${URL}" | sed -E 's#^https?://[^:]+:([0-9]+).*$#\1#' || true)"
  echo "Derived port from URL: ${PORT_FROM_URL:-N/A}"

  hdr "ss -ltnp (if available)"
  (ss -ltnp 2>/dev/null || true) | (grep -E ":${PORT_FROM_URL}\b" || true)

  hdr "lsof -i (if available)"
  (lsof -i 2>/dev/null || true) | (grep -E ":${PORT_FROM_URL}\b" || true)

  hdr "ps aux | grep (uvicorn|python|watsonx)"
  ps aux | egrep -i 'uvicorn|watsonx|mcp|fastmcp' | grep -v grep || true
} | logwrap

# -----------------------------
# 5) Hub & Gateway health
# -----------------------------
step "Hub & Gateway health"
{
  AUTH_H=()
  [[ -n "${HUB_TOKEN}" ]] && AUTH_H=(-H "Authorization: Bearer ${HUB_TOKEN}")

  hdr "Hub /health"
  curl -sS "${HUB}/health" "${AUTH_H[@]}" -i | sed -n '1,20p'

  hdr "Hub /config"
  curl -sS "${HUB}/config" "${AUTH_H[@]}" -i | sed -n '1,60p'

  hdr "Hub search (q=watsonx, include_pending=true)"
  curl -sS "${HUB}/catalog/search?q=watsonx&include_pending=true&limit=5" "${AUTH_H[@]}" | jq . 2>/dev/null || true

  AUTH_G=()
  [[ -n "${GW_TOKEN}" ]] && AUTH_G=(-H "Authorization: Bearer ${GW_TOKEN}")

  hdr "Gateway /health"
  curl -sS "${GW_BASE}/health" -i | sed -n '1,30p'
} | logwrap

# -----------------------------
# 6) Docker snapshot (if used)
# -----------------------------
if (( NO_DOCKER == 0 )) && command -v docker >/dev/null 2>&1; then
  step "Docker state"
  {
    hdr "docker ps"
    docker ps

    for name in matrixhub matrixhub-db mcpgateway; do
      if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
        hdr "docker logs --tail=300 $name"
        docker logs --tail=300 "$name" 2>&1 || true
      fi
    done
  } | logwrap
else
  warn "Skipping docker checks (--no-docker or docker not found)"
fi

# -----------------------------
# 7) SSE quick probe
# -----------------------------
step "SSE endpoint probe"
{
  hdr "HEAD (may 405; OK to ignore)"
  curl -sS -I --max-time 4 "${URL}" | sed -n '1,20p' || true

  hdr "GET (first lines)"
  # Don't block—read a few lines then abort.
  (curl -sS -N --max-time 4 "${URL}" | head -n 5) || true

  # Common health endpoints next to SSE
  BASE="${URL%/sse}"
  for hp in /health /healthz /readyz /livez; do
    hdr "Health check ${BASE}${hp}"
    curl -sS -i --max-time 3 "${BASE}${hp}" | sed -n '1,30p' || true
  done
} | logwrap

# -----------------------------
# 8) matrix mcp probe/call (if available)
# -----------------------------
if (( NO_MATRIX == 0 )) && command -v matrix >/dev/null 2>&1; then
  step "matrix mcp probe/call"
  {
    hdr "matrix mcp probe --url (JSON)"
    MATRIX_SDK_DEBUG=1 matrix mcp probe --url "${URL}" --json 2>&1 || true

    hdr "matrix mcp call (Q1)"
    MATRIX_SDK_DEBUG=1 matrix mcp call chat --url "${URL}" --args "$(jq -nc --arg q "${Q1}" '{query:$q}')" 2>&1 || true

    hdr "matrix mcp call (Q2)"
    MATRIX_SDK_DEBUG=1 matrix mcp call chat --url "${URL}" --args "$(jq -nc --arg q "${Q2}" '{query:$q}')" 2>&1 || true
  } | logwrap
else
  warn "Skipping matrix mcp probe/call (matrix not found or --no-matrix)"
fi

# -----------------------------
# 9) Optional Python micro-client (if mcp installed)
# -----------------------------
if (( NO_PY == 0 )); then
  step "Python micro-client (if 'mcp' present)"
  python3 - <<PY 2>&1 | logwrap || true
import sys, json
try:
    import anyio
    from mcp.client.sse import sse_client
    from mcp.client.session import ClientSession
except Exception as e:
    print(f"mcp client not available: {e}")
    sys.exit(0)

URL = "${URL}"
Q1 = ${Q1@Q}

async def main():
    print(f"[py] connecting to {URL} ...")
    try:
        async with sse_client(URL) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("[py] initialized")

                # list tools
                try:
                    tools = await session.list_tools()
                except Exception as e:
                    tools = None
                    print(f"[py] list_tools error: {e}")
                print("[py] tools =", tools)

                try:
                    res = await session.call_tool("chat", {"query": Q1})
                    # best-effort to extract text content
                    def extract_text(content):
                        out=[]
                        for it in (content or []):
                            if isinstance(it, dict):
                                if it.get("type")=="text" and it.get("text"):
                                    out.append(it["text"])
                        return "\\n".join(out)
                    text = extract_text(getattr(res,"content",None))
                    print("[py] call result text:", text[:400] or "(empty)")
                except Exception as e:
                    print(f"[py] call_tool error: {e}")
    except Exception as e:
        print(f"[py] connect/init error: {e}")

import anyio; anyio.run(main)
PY
else
  warn "Skipping python micro-client (--no-python)"
fi

# -----------------------------
# 10) Finalize bundle
# -----------------------------
step "Create bundle"
(
  cd "${OUT_PARENT}"
  tar -czf "${BUNDLE}" "$(basename "${OUT_DIR}")"
)
ok "Report ready: ${BUNDLE}"

# -----------------------------
# Tail a short summary
# -----------------------------
step "Quick hints"
cat <<'TIP' | logwrap
- If matrix mcp probe/call fails with ExceptionGroup:
  • Check 'SSE endpoint probe' section: did GET /sse stream data? Did /health return 200?
  • See 'matrix mcp probe --url' output for handshake errors.
  • Ensure your server advertises the 'chat' tool. (FastMCP @mcp.tool must be registered before sse_app()).
  • If the runner is a connector (pid=0 in lock), matrix run just records URL; make sure the remote server is actually running.
  • AnyIO/HTTPX TLS issues? Check REQUESTS_CA_BUNDLE/SSL_CERT_FILE in 'Env (masked)'.
  • For 401s from gateway/hub, verify tokens; we mask them in logs but show presence.

Open the bundle and start with debug.log; JSON responses are pretty-printed inside.
TIP
