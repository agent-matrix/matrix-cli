#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Ingest local Watsonx manifest into Matrix Hub via a "remote" catalog
#
# - Serves the repository over HTTP (default: 127.0.0.1:8000)
# - Adds a remote pointing to examples/index.json
# - Ingests that remote into the Hub
#
# Requirements: matrix (CLI), python3, curl
#
# Usage:
#   ./examples/ingest_watsonx_remote.sh          # default port 8000, name local-watsonx
#   PORT=9000 NAME=my-watsonx ./examples/ingest_watsonx_remote.sh
# ==============================================================================

log() { printf "\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()  { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
warn(){ printf "\033[1;33m! %s\033[0m\n" "$*"; }
die() { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || die "Missing dependency: $1"; }

need matrix
need python3
need curl

# Config (override via env)
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
NAME="${NAME:-local-watsonx}"

# Resolve repo root (script may be run from anywhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

INDEX_URL="http://${HOST}:${PORT}/examples/index.json"
MANIFEST_URL="http://${HOST}:${PORT}/examples/manifests/watsonx.manifest.json"

log "Repository root: ${REPO_ROOT}"
log "Will serve HTTP on: ${HOST}:${PORT}"
log "Remote name: ${NAME}"
log "Index URL: ${INDEX_URL}"

# Start a local HTTP server to expose examples/index.json + manifest
pushd "${REPO_ROOT}" >/dev/null
python3 -m http.server "${PORT}" --bind "${HOST}" >/dev/null 2>&1 &
SRV_PID=$!
popd >/dev/null

cleanup() {
  if ps -p "${SRV_PID}" >/dev/null 2>&1; then
    kill "${SRV_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# Wait for server
for _ in {1..30}; do
  if curl -fsS "${INDEX_URL}" >/dev/null 2>&1; then break; fi
  sleep 0.2
done

# Sanity checks
curl -fsS "${INDEX_URL}" >/dev/null || die "Cannot fetch ${INDEX_URL}"
ok "Catalog index reachable"

curl -fsS "${MANIFEST_URL}" >/dev/null || die "Cannot fetch ${MANIFEST_URL}"
ok "Manifest reachable"

# Register (remove if exists, ignore failure)
log "Registering remote '${NAME}'"
matrix remotes remove "${NAME}" >/dev/null 2>&1 || true
matrix remotes add "${INDEX_URL}" --name "${NAME}"

# Ingest
log "Ingesting remote '${NAME}'"
matrix remotes ingest "${NAME}"

ok "Ingest complete."

# Helpful next steps
cat <<EOF

Next steps (examples):

  # Verify it's discoverable
  matrix search "watsonx" --type mcp_server --limit 5

  # Install by name (or pin the fqid)
  matrix install watsonx-agent
  # or: matrix install mcp_server:watsonx-agent@0.1.0

  # Run & test
  matrix run watsonx-agent
  matrix ps
  matrix mcp probe --alias watsonx-agent
  matrix mcp call chat --alias watsonx-agent --args '{"query":"hello"}'

  # Cleanup (optional)
  matrix stop watsonx-agent
  matrix uninstall watsonx-agent --purge -y
  matrix remotes remove "${NAME}"
EOF
