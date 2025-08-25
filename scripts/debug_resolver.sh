#!/usr/bin/env bash
# debug_resolver.sh — quick local sanity checks for Matrix resolver behavior
# Usage:
#   ./debug_resolver.sh                         # default: RAW_ID=hello-sse-server
#   RAW_ID=gateway ./debug_resolver.sh
#   DO_INSTALL=1 ./debug_resolver.sh            # also run install checks (uses temp alias/target)
#   CLEAR_CACHE=1 ./debug_resolver.sh           # clear resolver cache before tests
#   HUB=http://api.matrixhub.io ./debug_resolver.sh  # explicit hub for install checks
#
# Env vars (with defaults):
#   RAW_ID=hello-sse-server
#   BROAD_QUERY=hello
#   ALT_QUERY="hello sse server"
#   DO_INSTALL=0
#   CLEAR_CACHE=0
#   HUB=""  # leave empty to use default hub from config

set -uo pipefail

RAW_ID="${RAW_ID:-hello-sse-server}"
BROAD_QUERY="${BROAD_QUERY:-hello}"
ALT_QUERY="${ALT_QUERY:-hello sse server}"
DO_INSTALL="${DO_INSTALL:-0}"
CLEAR_CACHE="${CLEAR_CACHE:-0}"
HUB_OVERRIDE="${HUB:-}"

# A bogus hub that will trigger DNS failure → local fallback to http://localhost:443
BOGUS_HUB="http://does-not-resolve.invalid"

CACHE_FILE="${HOME}/.matrix/cache/resolve.json"
TS="$(date +%s)"
TMPROOT="$(mktemp -d -t matrix-debug-XXXXXX)"
trap 'rm -rf "$TMPROOT" >/dev/null 2>&1 || true' EXIT

# ---- helpers ---------------------------------------------------------------

_bold() { printf "\033[1m%s\033[0m\n" "$*"; }
_dim() { printf "\033[2m%s\033[0m\n" "$*"; }
_hr() { printf "\n%s\n" "----------------------------------------------------------------"; }
section() { _hr; _bold "$*"; }
note() { printf "  - %s\n" "$*"; }
warn() { printf "\033[33m! %s\033[0m\n" "$*"; }
ok() { printf "\033[32m✓ %s\033[0m\n" "$*"; }
fail() { printf "\033[31m✗ %s\033[0m\n" "$*"; }

run() {
  # run "cmd ..." [--ok-exit N] [--label "text"]
  local ok_exit=0 label=""
  local args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ok-exit) ok_exit="$2"; shift 2 ;;
      --label) label="$2"; shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  local cmd="${args[*]}"
  [[ -n "$label" ]] && _bold "$label"
  _dim "$ $cmd"
  # shellcheck disable=SC2086
  bash -c "$cmd"
  local rc=$?
  if [[ $rc -eq $ok_exit ]]; then ok "exit=$rc"; else fail "exit=$rc"; fi
  return $rc
}

cache_show_hit() {
  local key="$1"
  if [[ -f "$CACHE_FILE" ]]; then
    note "Cache file: $CACHE_FILE"
    if grep -q -E "\"${key}\"" "$CACHE_FILE"; then
      warn "Found cache entry for '${key}' (could be positive or negative)."
      # show small context without jq
      grep --color=never -n -C2 -E "\"${key}\"|\"fqid\"|\"neg\"" "$CACHE_FILE" || true
    else
      ok "No cache entry found for '${key}'."
    fi
  else
    note "Cache file not present yet."
  fi
}

cache_backup_and_clear() {
  if [[ -f "$CACHE_FILE" ]]; then
    local backup="${CACHE_FILE}.${TS}.bak"
    cp -f "$CACHE_FILE" "$backup" && ok "Backed up cache → $backup"
  fi
  mkdir -p "$(dirname "$CACHE_FILE")"
  echo '{"hub":"","entries":{},"neg":{}}' > "$CACHE_FILE"
  ok "Cleared resolver cache."
}

# ---- preflight -------------------------------------------------------------

section "Environment"
run "matrix --version" --ok-exit 0 --label "Matrix CLI version"
run "python --version" --ok-exit 0 --label "Python version"
note "Raw ID:        ${RAW_ID}"
note "Broad query:   ${BROAD_QUERY}"
note "Alt query:     ${ALT_QUERY}"
[[ -n "$HUB_OVERRIDE" ]] && note "Hub (override): ${HUB_OVERRIDE}" || note "Hub: (default from config)"

section "Resolver Cache State (BEFORE)"
cache_show_hit "$RAW_ID"
if [[ $CLEAR_CACHE -eq 1 ]]; then
  warn "CLEAR_CACHE=1 → wiping cache to avoid negative-cache masking."
  cache_backup_and_clear
fi

# ---- search variants -------------------------------------------------------

section "Search Variants — default hub"
# FIXED: Removed the invalid --hub flag from all search commands.
# The search command always uses the hub from the default config.
run "matrix search \"$BROAD_QUERY\" --limit 10" --ok-exit 0 --label "1) Broad search"
run "matrix search \"$RAW_ID\" --limit 10"      --ok-exit 0 --label "2) Literal slug search"
run "matrix search \"$ALT_QUERY\" --limit 10"   --ok-exit 0 --label "3) Tokenized search"

# ---- optional install checks ----------------------------------------------

if [[ "$DO_INSTALL" -eq 1 ]]; then
  section "Install Checks (safe: temp alias/target)"
  TMP_TARGET="${TMPROOT}/target"
  mkdir -p "$TMP_TARGET"
  TMP_ALIAS="debug-${RAW_ID//[^a-zA-Z0-9_-]/}-$(date +%s)"
  HUB_ARG=""
  [[ -n "$HUB_OVERRIDE" ]] && HUB_ARG="--hub \"$HUB_OVERRIDE\""

  note "Temp alias:  $TMP_ALIAS"
  note "Temp target: $TMP_TARGET"

  # 7) Attempt install with RAW_ID (default hub). This exercises the resolver.
  # This command is expected to FAIL until the resolver is fixed.
  run "matrix install \"$RAW_ID\" --alias \"$TMP_ALIAS\" --target \"$TMP_TARGET\" --no-prompt $HUB_ARG" --ok-exit 10 --label "7) Install by raw id (default hub)"

  # 8) Install by raw id with forced fallback (bogus hub) — should show offline note and try localhost:443
  # This command is also expected to FAIL until the resolver is fixed.
  run "matrix install \"$RAW_ID\" --alias \"${TMP_ALIAS}-fb\" --target \"$TMP_TARGET\" --no-prompt --hub \"$BOGUS_HUB\"" --ok-exit 10 --label "8) Install by raw id (forced fallback)"

else
  section "Install Checks"
  note "Skipped (set DO_INSTALL=1 to run safe install attempts with temp alias/target)."
fi

# ---- cache after -----------------------------------------------------------

section "Resolver Cache State (AFTER)"
cache_show_hit "$RAW_ID"

section "Next steps / Hints"
note "If (2) fails but (1) or (3) succeed, the resolver likely needs a tokenized fallback for hyphenated slugs."
note "If install checks fail with exit=10, the resolver logic is not finding the package. This is expected until fixed."
note "If AFTER state shows a negative cache for '${RAW_ID}', clear it with CLEAR_CACHE=1 before re-testing."
ok "Done."