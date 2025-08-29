#!/usr/bin/env bash
# scripts/bash/debuger_matrix_run.sh
# Collect deep diagnostics for Matrix Hub / Matrix CLI / MCP Gateway / Watsonx MCP SSE server.
set -Eeuo pipefail

# ---------- pretty ----------
GREEN="\033[0;32m"; CYAN="\033[1;36m"; YELLOW="\033[1;33m"; RED="\033[1;31m"; RESET="\033[0m"
step(){ printf "\n${CYAN}▶ %s${RESET}\n" "$*"; }
info(){ printf "ℹ %s\n" "$*"; }
ok(){ printf "${GREEN}✓ %s${RESET}\n" "$*"; }
warn(){ printf "${YELLOW}⚠ %s${RESET}\n" "$*"; }
err(){ printf "${RED}✖ %s${RESET}\n" "$*"; }

MASK(){ local s="${1:-}"; [[ -z "$s" ]]&&{ echo "(empty)";return; }; local n=${#s}; ((n<=6))&&{ echo "******";return; }; printf "%s\n" "${s:0:3}***${s:n-3:3}"; }

usage() {
  cat <<EOF
Usage: $0 [opts]
  --sse-url URL         SSE URL of MCP server   (default: http://127.0.0.1:6288/sse)
  --hub URL             MatrixHub base          (default: http://127.0.0.1:443)
  --hub-token TOKEN     Hub API token (Bearer)  (default: \$HUB_TOKEN/\$MATRIX_HUB_TOKEN)
  --gw URL              MCP Gateway base        (default: http://127.0.0.1:4444)
  --gw-token TOKEN      Gateway token (Bearer)  (default: \$GW_TOKEN/\$MCP_GATEWAY_TOKEN)
  --alias NAME          Local alias to inspect  (default: watsonx-chat)
  --tool TOOL           Expected tool id        (default: chat)
  --manifest URL        Manifest to snapshot    (optional)
  --out DIR             Output dir for logs     (default: /tmp/matrix-debug-YYYYmmdd-HHMMSS)
  -h, --help
EOF
}

# ---------- defaults ----------
SSE_URL="${SSE_URL:-http://127.0.0.1:6288/sse}"
HUB="${HUB:-http://127.0.0.1:443}"
HUB_TOKEN="${HUB_TOKEN:-${MATRIX_HUB_TOKEN:-}}"
GW_BASE="${GW_BASE:-http://127.0.0.1:4444}"
GW_TOKEN="${GW_TOKEN:-${MCP_GATEWAY_TOKEN:-}}"
ALIAS="${ALIAS:-watsonx-chat}"
TOOL_ID="${TOOL_ID:-chat}"
MANIFEST_URL="${MANIFEST_URL:-}"
OUTDIR="${OUTDIR:-/tmp/matrix-debug-$(date +%Y%m%d-%H%M%S)}"

# ---------- parse flags ----------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sse-url) SSE_URL="$2"; shift 2;;
    --hub) HUB="$2"; shift 2;;
    --hub-token) HUB_TOKEN="$2"; shift 2;;
    --gw|--gw-url) GW_BASE="$2"; shift 2;;
    --gw-token) GW_TOKEN="$2"; shift 2;;
    --alias) ALIAS="$2"; shift 2;;
    --tool) TOOL_ID="$2"; shift 2;;
    --manifest) MANIFEST_URL="$2"; shift 2;;
    --out) OUTDIR="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) err "Unknown arg: $1"; usage; exit 2;;
  esac
done

# ---------- env ----------
if [[ -f ".env" ]]; then
  step "Loading .env"
  set +u; set -a; source .env; set +a; set -u
fi

mkdir -p "$OUTDIR"
REPORT="$OUTDIR/REPORT.md"
LOG(){ printf "%s\n" "$*" >>"$REPORT"; }

trap 'echo; ok "Diagnostics saved under: $OUTDIR"; echo; ' EXIT

# ---------- reqs ----------
command -v jq >/dev/null 2>&1 || { err "jq not found"; exit 1; }
command -v curl >/dev/null 2>&1 || { err "curl not found"; exit 1; }
command -v matrix >/dev/null 2>&1 || warn "matrix CLI not found (some steps will be skipped)"

# ---------- helpers ----------
jwt_decode() {
  # decode JWT payload (base64url)
  local t="${1:-}"; [[ -z "$t" ]] && return 0
  local p; p="$(cut -d. -f2 <<<"$t" 2>/dev/null || true)"
  # pad base64
  local mod; mod=$(( ${#p} % 4 )); if (( mod==2 )); then p="${p}=="; elif (( mod==3 )); then p="${p}="; fi
  p="$(echo "$p" | tr '_-' '/+' )"
  echo "$p" | base64 -d 2>/dev/null || true
}

_curl_save() {
  # _curl_save URL OUTFILE [headers...]
  local url="$1"; shift
  local out="$1"; shift
  local code
  code="$(curl -sS -w '%{http_code}' -o "$out" "$url" "$@" || true)"
  echo "$code"
}

_curl_headers() {
  # _curl_headers URL OUTFILE [headers...]
  local url="$1"; shift
  local out="$1"; shift
  local code
  code="$(curl -sS -I -w '%{http_code}' -o "$out" "$url" "$@" || true)"
  echo "$code"
}

listening_on() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp | grep -E "[:.]${port}\b" || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP -sTCP:LISTEN -nP | grep -E ":${port}\b" || true
  else
    echo "(no ss/lsof available)"
  fi
}

# ---------- REPORT header ----------
{
  echo "# Matrix Debug Report"
  echo ""
  echo "- Date: $(date -Iseconds)"
  echo "- CWD:  $(pwd)"
  echo "- Host: $(uname -a)"
  echo "- OUT:  ${OUTDIR}"
  echo ""
} > "$REPORT"

# ================================================================
# 1) Versions & binaries
# ================================================================
step "Versions"
{
  echo "## Versions"
  echo '```'
  echo "matrix: $(command -v matrix || echo 'not found')"
  matrix --version 2>&1 || true
  echo ""
  echo "python: $(command -v python3 || command -v python || echo 'not found')"
  (python3 --version 2>&1 || python --version 2>&1 || true)
  echo ""
  echo "pip relevant:"
  (pip show fastmcp mcp ibm-watsonx-ai starlette uvicorn 2>/dev/null || true)
  echo '```'
} >> "$REPORT"

# ================================================================
# 2) Ports & listeners
# ================================================================
step "Ports / listeners snapshot"
{
  echo "## Listeners"
  echo '```'
  echo "# 443   (MatrixHub)"
  listening_on 443
  echo "# 4444  (MCP Gateway)"
  listening_on 4444
  echo "# SSE   ($(echo "$SSE_URL" | sed -E 's#.*:([0-9]+).*#\1#'))"
  listening_on "$(echo "$SSE_URL" | sed -E 's#.*:([0-9]+).*#\1#')"
  echo '```'
} >> "$REPORT"

# ================================================================
# 3) SSE endpoint checks
# ================================================================
step "SSE endpoint checks: $SSE_URL"
H_SSE="$OUTDIR/sse_headers.txt"
B_SSE="$OUTDIR/sse_stream_snippet.txt"

code=$(_curl_headers "$SSE_URL" "$H_SSE")
info "HEAD $SSE_URL → HTTP $code"
[[ -s "$H_SSE" ]] && sed -n '1,10p' "$H_SSE" | sed 's/^/   /'

# read a few bytes of the stream (will likely hang otherwise)
# use --max-time to bail out quickly
curl -sS -N --max-time 3 "$SSE_URL" 2>/dev/null | head -n 10 > "$B_SSE" || true
if [[ -s "$B_SSE" ]]; then
  ok "Captured SSE first lines → $B_SSE"
  sed -n '1,5p' "$B_SSE" | sed 's/^/   /'
else
  warn "No SSE lines captured (could still be fine)"
fi

# ================================================================
# 4) Health endpoints (if available on server)
# ================================================================
step "Server health endpoints (if implemented)"
for p in /health /healthz /readyz /livez; do
  out="$OUTDIR${p//\//_}.json"
  code=$(_curl_save "$(echo "$SSE_URL" | sed 's#/sse$##')$p" "$out")
  info "GET ${p} → HTTP $code"
  [[ -s "$out" ]] && head -c 200 "$out" | sed 's/^/   /'; echo
done

# ================================================================
# 5) Matrix Hub probe
# ================================================================
step "MatrixHub /health"
H_HDR=()
[[ "$HUB" == https:* ]] && H_HDR+=(-k)
if [[ -n "${HUB_TOKEN:-}" ]]; then H_HDR+=(-H "Authorization: Bearer ${HUB_TOKEN}"); fi

out="$OUTDIR/hub_health.json"
code=$(_curl_save "${HUB%/}/health" "$out" "${H_HDR[@]}")
info "GET $HUB/health → HTTP $code"
[[ -s "$out" ]] && head -c 200 "$out" | sed 's/^/   /'; echo

# ================================================================
# 6) MCP Gateway probe + token decode
# ================================================================
step "MCP Gateway /health + token sanity"
G_HDR=()
[[ "$GW_BASE" == https:* ]] && G_HDR+=(-k)
if [[ -n "${GW_TOKEN:-}" ]]; then G_HDR+=(-H "Authorization: Bearer ${GW_TOKEN}"); fi

if [[ -n "${GW_TOKEN:-}" ]]; then
  jwt_decode "$GW_TOKEN" > "$OUTDIR/gw_token_payload.json" || true
  if [[ -s "$OUTDIR/gw_token_payload.json" ]]; then
    ok "Decoded GW token payload → $OUTDIR/gw_token_payload.json"
    jq '.|{username,exp}' "$OUTDIR/gw_token_payload.json" 2>/dev/null | sed 's/^/   /' || true
    exp="$(jq -r '.exp // empty' "$OUTDIR/gw_token_payload.json" 2>/dev/null || true)"
    if [[ -n "$exp" ]]; then
      now="$(date +%s)"
      if (( now > exp )); then warn "GW token appears EXPIRED (now=$now > exp=$exp)"; fi
    fi
  else
    warn "Could not decode GW token (non-fatal)"
  fi
else
  warn "GW token not provided"
fi

out="$OUTDIR/gw_health.json"
code=$(_curl_save "${GW_BASE%/}/health" "$out" "${G_HDR[@]}")
info "GET $GW_BASE/health → HTTP $code"
[[ -s "$out" ]] && head -c 200 "$out" | sed 's/^/   /'; echo

# Also snapshot tools/gateways lists (may be 401)
for path in /tools /gateways; do
  out="$OUTDIR/gw${path//\//_}.json"
  code=$(_curl_save "${GW_BASE%/}$path" "$out" "${G_HDR[@]}")
  info "GET $GW_BASE$path → HTTP $code"
  [[ -s "$out" ]] && head -c 200 "$out" | sed 's/^/   /'; echo
done

# ================================================================
# 7) Manifest snapshot (optional)
# ================================================================
if [[ -n "$MANIFEST_URL" ]]; then
  step "Manifest snapshot"
  out="$OUTDIR/manifest.json"
  code=$(_curl_save "$MANIFEST_URL" "$out")
  info "GET $MANIFEST_URL → HTTP $code"
  [[ -s "$out" ]] && jq -r '.id?,.version?,.mcp_registration.server.url? // empty' "$out" | sed 's/^/   /' || true
fi

# ================================================================
# 8) Matrix CLI probe & calls against SSE
# ================================================================
if command -v matrix >/dev/null 2>&1; then
  step "matrix mcp probe (SSE direct)"
  PROBE_OUT="$OUTDIR/mcp_probe.json"
  set +e; matrix mcp probe --url "$SSE_URL" --json >"$PROBE_OUT" 2>&1; RC=$?; set -e
  info "probe rc=$RC → $PROBE_OUT"
  head -n 80 "$PROBE_OUT" | sed 's/^/   /' || true

  # Try to list tools if probe succeeded
  if jq -e '.tools? | length>=0' "$PROBE_OUT" >/dev/null 2>&1; then
    TOOLS_LIST="$OUTDIR/mcp_tools.txt"
    jq -r '.tools[]? | .name // .id // "<unknown>"' "$PROBE_OUT" > "$TOOLS_LIST" || true
    ok "Server advertises tools → $TOOLS_LIST"
    sed -n '1,20p' "$TOOLS_LIST" | sed 's/^/   /'
  else
    warn "Could not parse tools from probe (see file)"
  fi

  step "matrix mcp call (direct SSE) — tool=${TOOL_ID}"
  Q1='{"query":"What is the capital of Italy?"}'
  Q2='{"query":"Tell me about Genoa."}'

  C1="$OUTDIR/call_${TOOL_ID}_1.out"
  set +e; matrix mcp call "${TOOL_ID}" --url "$SSE_URL" --args "$Q1" >"$C1" 2>&1; RC1=$?; set -e
  info "call#1 rc=$RC1 → $C1"
  sed -n '1,120p' "$C1" | sed 's/^/   /' || true

  C2="$OUTDIR/call_${TOOL_ID}_2.out"
  set +e; matrix mcp call "${TOOL_ID}" --url "$SSE_URL" --args "$Q2" >"$C2" 2>&1; RC2=$?; set -e
  info "call#2 rc=$RC2 → $C2"
  sed -n '1,120p' "$C2" | sed 's/^/   /' || true

  # If calls failed, also try the manifest-tool id 'watsonx-chat' (common mismatch)
  if (( RC1 != 0 || RC2 != 0 )); then
    ALT="watsonx-chat"
    step "Retry with alternate tool id: ${ALT}"
    C3="$OUTDIR/call_${ALT}_1.out"
    set +e; matrix mcp call "${ALT}" --url "$SSE_URL" --args "$Q1" >"$C3" 2>&1; RC3=$?; set -e
    info "alt call rc=$RC3 → $C3"
    sed -n '1,80p' "$C3" | sed 's/^/   /' || true
  fi
else
  warn "matrix CLI not available; skipping probe/call"
fi

# ================================================================
# 9) Quick hub/gateway auth check (401 vs 200)
# ================================================================
step "Auth sanity"
{
  echo "## Auth sanity"
  echo '```'
  echo "Hub: ${HUB}"
  echo "Hub token: $(MASK "${HUB_TOKEN}")"
  echo "GW:  ${GW_BASE}"
  echo "GW token:  $(MASK "${GW_TOKEN}")"
  echo '```'
} >> "$REPORT"

ok "Done. Attach $OUTDIR as the debug bundle."
