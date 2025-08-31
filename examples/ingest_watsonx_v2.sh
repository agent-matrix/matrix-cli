#!/usr/bin/env bash
# ingest_watsonx_v2.sh — PoC: ingest a v2 MCP server manifest into MatrixHub (multiple methods)
# -----------------------------------------------------------------------------
# Modes (pick via MODE env or --mode flag):
#   remote-add      : Register MANIFEST_URL as a remote on the Hub and trigger ingest
#   inline-publish  : Admin publish: POST full manifest JSON into the Hub catalog
#   inline-install  : Per-user install *inline* manifest to verify plan generation (no catalog required)
#   verify-install  : Client local install via matrix CLI; retries with manifest/runner if runner missing
#
# Defaults target: https://api.matrixhub.io   (override with HUB_BASE)
#
# Endpoints are conventional and can be overridden via:
#   REMOTES_PATH=/remotes
#   INGEST_PATH=/remotes/ingest
#   PUBLISH_PATH=/admin/catalog/publish
#   INSTALL_MANIFEST_PATH=/install/manifest
#
# Requirements:
#   - curl (always)
#   - matrix CLI only for verify-install mode
#
# Exit codes:
#   0  success
#   2  missing dependency
#   3  bad args
#   10 HTTP/ingest error
#   20 verify failed
# -----------------------------------------------------------------------------

set -Eeuo pipefail

# ------------------------ Pretty logging ------------------------
C_CYAN="\033[1;36m"; C_GREEN="\033[1;32m"; C_YELLOW="\033[1;33m"; C_RED="\033[1;31m"; C_RESET="\033[0m"
log()  { printf "\n${C_CYAN}▶ %s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✓ %s${C_RESET}\n" "$*"; }
warn() { printf "${C_YELLOW}! %s${C_RESET}\n" "$*"; }
err()  { printf "${C_RED}✗ %s${C_RESET}\n" "$*" >&2; }

print_cmd() {
  # Redact tokens in printed curl commands
  local redacted="$*"
  redacted="${redacted//-H Authorization:*Bearer * /-H 'Authorization: Bearer ***' }"
  printf "${C_GREEN}$ %s${C_RESET}\n" "$redacted" >&2
}

run_or_echo() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    print_cmd "$*"
  else
    print_cmd "$*"
    eval "$@"
  fi
}

# ------------------------ Defaults & args ------------------------
MODE="${MODE:-remote-add}"    # remote-add | inline-publish | inline-install | verify-install

HUB_BASE="${HUB_BASE:-https://api.matrixhub.io}"
FQID="${FQID:-mcp_server:watsonx-agent@0.1.0}"
ALIAS="${ALIAS:-watsonx-agent}"

# v2 manifest with embedded runner:
MANIFEST_URL="${MANIFEST_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/manifests/watsonx.manifest-v2.json}"
# optional: used for verify fallback or when you want to pin a runner explicitly
RUNNER_URL="${RUNNER_URL:-https://raw.githubusercontent.com/ruslanmv/watsonx-mcp/refs/heads/master/runner.json}"
REPO_URL="${REPO_URL:-https://github.com/ruslanmv/watsonx-mcp.git}"

# Admin token for protected endpoints (remote-add, inline-publish typically need it)
HUB_TOKEN="${HUB_TOKEN:-}"

# Conventional endpoints (override if your Hub differs)
REMOTES_PATH="${REMOTES_PATH:-/remotes}"
INGEST_PATH="${INGEST_PATH:-/remotes/ingest}"
PUBLISH_PATH="${PUBLISH_PATH:-/admin/catalog/publish}"
INSTALL_MANIFEST_PATH="${INSTALL_MANIFEST_PATH:-/install/manifest}"

# Optional: normalize /sse on the manifest’s mcp_registration.server.url before sending inline publish
NORMALIZE_SSE="${NORMALIZE_SSE:-1}"

# verify-install tweaks
DEMO_PORT="${DEMO_PORT:-6288}"
READY_MAX_WAIT="${READY_MAX_WAIT:-60}"

usage() {
cat <<USAGE
Usage: $0 [--mode MODE] [--dry-run] [--help]

Modes:
  remote-add       Register MANIFEST_URL as a remote on the Hub and trigger ingest
  inline-publish   Admin publish: POST full manifest JSON into the catalog
  inline-install   POST inline manifest to /install/manifest (plan proof)
  verify-install   matrix install FQID (fallback to --manifest/--runner/repo if runner missing)

Environment (overridable):
  HUB_BASE=${HUB_BASE}
  HUB_TOKEN=<required for admin endpoints>   # NOT printed in logs
  FQID=${FQID}
  ALIAS=${ALIAS}
  MANIFEST_URL=${MANIFEST_URL}
  RUNNER_URL=${RUNNER_URL}
  REPO_URL=${REPO_URL}

Paths (override to match your server):
  REMOTES_PATH=${REMOTES_PATH}
  INGEST_PATH=${INGEST_PATH}
  PUBLISH_PATH=${PUBLISH_PATH}
  INSTALL_MANIFEST_PATH=${INSTALL_MANIFEST_PATH}

Flags:
  --mode <MODE>    See above (or set MODE env)
  --dry-run        Print curl commands without executing
  --help           Show help

Examples:
  MODE=remote-add $0
  MODE=inline-publish HUB_TOKEN=... $0
  MODE=inline-install $0
  MODE=verify-install $0
USAGE
}

# Parse args
for arg in "$@"; do
  case "$arg" in
    --mode) shift; MODE="${1:-}"; shift || true ;;
    --dry-run) DRY_RUN=1; shift || true ;;
    --help|-h) usage; exit 0 ;;
    *) err "Unknown arg: $arg"; usage; exit 3 ;;
  esac
done

# ------------------------ Deps ------------------------
need() { command -v "$1" >/dev/null 2>&1 || { err "Missing dependency: $1"; exit 2; }; }
need curl

# For verify-install only
if [[ "$MODE" == "verify-install" ]]; then
  need matrix
fi

# ------------------------ Helpers ------------------------
tmpfile() { mktemp -t ingest.XXXXXX.json; }

fetch_manifest() {
  local out="$1"
  curl -fsSL --max-time 20 "$MANIFEST_URL" -o "$out"
}

normalize_manifest_sse() {
  # crude, jq-less normalization: ensure server.url ends with /sse (does not reformat JSON nicely)
  # this is optional and best-effort; if you need perfect JSON surgery, swap in jq.
  local in="$1"; local out="$2"
  if [[ "${NORMALIZE_SSE}" != "1" ]]; then
    cp -f "$in" "$out"
    return 0
  fi
  # This preserves most JSON but forces /sse suffix on the first "server":{"url": "..."} we find.
  # Works for your provided v2 manifest.
  local s="$(cat "$in")"
  # try to locate "server"..."url":"...".
  # ensure single /sse (strip trailing slashes, then append /sse)
  local url="$(printf "%s" "$s" | sed -n 's/.*"server"[^{]*{[^}]*"url"[[:space:]]*:[[:space:]]*"\([^"]\+\)".*/\1/p' | head -n1)"
  if [[ -n "$url" ]]; then
    local trimmed="$url"
    while [[ "$trimmed" == */ ]]; do trimmed="${trimmed%/}"; done
    [[ "$trimmed" != */sse ]] && trimmed="${trimmed}/sse"
    s="${s/$url/$trimmed}"
  fi
  printf "%s" "$s" > "$out"
}

json_escape() {
  # Escape string for JSON value context (very basic)
  printf '%s' "$1" | sed \
    -e 's/\\/\\\\/g' \
    -e 's/"/\\"/g'
}

label_from_fqid_alias() {
  # target label used by the server; avoids leaking local paths
  local ver="${FQID##*@}"
  printf "%s/%s" "$ALIAS" "$ver"
}

# ------------------------ Modes ------------------------

do_remote_add() {
#  [[ -n "${HUB_TOKEN}" ]] || { err "HUB_TOKEN required for remote-add"; exit 3; }

  local NAME="${ALIAS}-remote"
  local url="${HUB_BASE%/}${REMOTES_PATH}"
  local ingest="${HUB_BASE%/}${INGEST_PATH}"

  log "Registering remote (URL → ${MANIFEST_URL})"
  local payload
  payload=$(cat <<EOF
{"url":"$(json_escape "$MANIFEST_URL")","name":"$(json_escape "$NAME")","trust_policy":"verify"}
EOF
)
  run_or_echo "curl -fsS -X POST \"$url\" \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer $HUB_TOKEN' \
    -d '$payload'"

  ok "Remote registered (or already exists)."

  log "Triggering ingest now"
  local p2
  p2=$(cat <<EOF
{"url":"$(json_escape "$MANIFEST_URL")"}
EOF
)
  run_or_echo "curl -fsS -X POST \"$ingest\" \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer $HUB_TOKEN' \
    -d '$p2'"

  ok "Ingest triggered."
}

do_inline_publish() {
  [[ -n "${HUB_TOKEN}" ]] || { err "HUB_TOKEN required for inline-publish"; exit 3; }

  local pub="${HUB_BASE%/}${PUBLISH_PATH}"
  local mf_raw mf_norm
  mf_raw="$(tmpfile)"; mf_norm="$(tmpfile)"
  trap 'rm -f "$mf_raw" "$mf_norm"' EXIT

  log "Fetching manifest from MANIFEST_URL"
  fetch_manifest "$mf_raw" || { err "Failed to fetch manifest"; exit 10; }

  log "Normalizing /sse (optional NORMALIZE_SSE=${NORMALIZE_SSE})"
  normalize_manifest_sse "$mf_raw" "$mf_norm"

  log "Publishing manifest into catalog (fqid=${FQID})"
  # Embed manifest JSON directly; also include provenance.source_url and repo_url when available
  # No jq: we read manifest as a raw string and escape it for JSON context.
  local mf_body
  mf_body="$(cat "$mf_norm")"
  local body
  body=$(cat <<EOF
{"fqid":"$(json_escape "$FQID")",
 "manifest": $mf_body,
 "provenance":{"source_url":"$(json_escape "$MANIFEST_URL")"},
 "repo_url":"$(json_escape "$REPO_URL")"}
EOF
)
  run_or_echo "curl -fsS -X POST \"$pub\" \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer $HUB_TOKEN' \
    -d '$body'"

  ok "Published to catalog."
}

do_inline_install() {
  local inst="${HUB_BASE%/}${INSTALL_MANIFEST_PATH}"
  local mf_raw
  mf_raw="$(tmpfile)"
  trap 'rm -f "$mf_raw"' EXIT

  log "Fetching manifest from MANIFEST_URL"
  fetch_manifest "$mf_raw" || { err "Failed to fetch manifest"; exit 10; }
  local mf_body; mf_body="$(cat "$mf_raw")"
  local target_label; target_label="$(label_from_fqid_alias)"

  log "Requesting inline install plan (no catalog needed)"
  local body
  body=$(cat <<EOF
{"id":"$(json_escape "$FQID")",
 "target":"$(json_escape "$target_label")",
 "manifest": $mf_body,
 "provenance":{"source_url":"$(json_escape "$MANIFEST_URL")"}}
EOF
)
  run_or_echo "curl -fsS -X POST \"$inst\" \
    -H 'Content-Type: application/json' \
    ${HUB_TOKEN:+-H 'Authorization: Bearer '"$HUB_TOKEN"} \
    -d '$body'"

  ok "Inline install plan retrieved (inspect output above for runner_b64/runner_url)."
}

do_verify_install() {
  need matrix

  export MATRIX_BASE_URL="${HUB_BASE}"
  export MATRIX_SDK_ALLOW_MANIFEST_FETCH=1
  export MATRIX_SDK_RUNNER_SEARCH_DEPTH=3

  log "Client install via matrix CLI (catalog path): ${FQID} → alias ${ALIAS}"
  local cmd1="matrix install \"$FQID\" --alias \"$ALIAS\" --hub \"$HUB_BASE\" --force --no-prompt"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    print_cmd $cmd1
    ok "Dry-run only."
    return 0
  fi

  set +e
  eval "$cmd1"
  local rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    err "matrix install returned non-zero ($rc)"
    exit 20
  fi

  # Inspect recent install output for runner.json hints (best-effort; some CLIs print to stdout)
  # If runner not found, retry with manifest flags that guarantee runner presence.
  log "Checking if runner.json likely exists…"
  # Quick heuristic: try a dry run start; if it fails, we retry with manifest flags
  if ! matrix run "$ALIAS" --port "$DEMO_PORT" >/dev/null 2>&1; then
    warn "Initial start failed; retrying install with --manifest/--runner-url/--repo-url"
    local cmd2="matrix install \"$FQID\" --alias \"$ALIAS\" --hub \"$HUB_BASE\" \
      --manifest \"$MANIFEST_URL\" --runner-url \"$RUNNER_URL\" --repo-url \"$REPO_URL\" \
      --force --no-prompt"
    print_cmd $cmd2
    eval "$cmd2"
  else
    # If it started, stop it; we will start again cleanly.
    matrix stop "$ALIAS" >/dev/null 2>&1 || true
  fi

  log "Starting '${ALIAS}' on port ${DEMO_PORT}"
  matrix run "$ALIAS" --port "$DEMO_PORT"

  # Minimal readiness check via /health
  local base="http://127.0.0.1:${DEMO_PORT}"
  local deadline=$(( $(date +%s) + READY_MAX_WAIT ))
  local okready=0
  while (( $(date +%s) < deadline )); do
    if curl -fsS --max-time 2 "$base/health" >/dev/null 2>&1; then
      okready=1; break
    fi
    sleep 2
  done
  if (( ! okready )); then
    err "Timed out waiting for readiness (checked ${base}/health)."
    matrix logs "$ALIAS" 2>/dev/null | tail -n 120 || true
    exit 20
  fi
  ok "Local server ready: $base/sse/"
}

# ------------------------ Main ------------------------
printf "\n${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
printf   "${C_CYAN}  MatrixHub Ingestion PoC — ${MODE}${C_RESET}\n"
printf   "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}\n"
echo "  Hub:         ${HUB_BASE}"
echo "  FQID:        ${FQID}"
echo "  Alias:       ${ALIAS}"
echo "  Manifest:    ${MANIFEST_URL}"
echo "  Runner URL:  ${RUNNER_URL}"
echo "  Repo URL:    ${REPO_URL}"
[[ -n "${HUB_TOKEN}" ]] && echo "  Auth:        (token present)" || echo "  Auth:        (no token; only public endpoints usable)"

case "$MODE" in
  remote-add)      do_remote_add ;;
  inline-publish)  do_inline_publish ;;
  inline-install)  do_inline_install ;;
  verify-install)  do_verify_install ;;
  *) err "Unknown MODE: $MODE"; usage; exit 3 ;;
esac

ok "Done."
exit 0
