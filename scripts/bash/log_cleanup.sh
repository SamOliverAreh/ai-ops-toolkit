#!/usr/bin/env bash
# =============================================================================
# log_cleanup.sh — Log rotation, compression & cleanup
#
# Usage:  ./log_cleanup.sh [--dry-run] [--dir /path/to/logs]
# Cron:   0 1 * * * /opt/ai-ops/scripts/bash/log_cleanup.sh >> /var/log/ai-ops/cleanup.log 2>&1
# =============================================================================
set -euo pipefail

: "${LOG_DIR:=./logs}"
: "${RETENTION_DAYS:=14}"
: "${MAX_SIZE_MB:=500}"
: "${DRY_RUN:=false}"
: "${SLACK_WEBHOOK_URL:=}"

TIMESTAMP=$(date +"%Y-%m-%dT%H:%M:%S")
FILES_DELETED=0
BYTES_FREED=0

log()  { echo "[${TIMESTAMP}] [$1] $2"; }
info() { log "INFO " "$1"; }
warn() { log "WARN " "$1"; }
ok()   { log "OK   " "$1"; }

run_or_dry() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY-RUN] Would run: $*"
  else
    "$@"
  fi
}

compress_large_logs() {
  info "Compressing uncompressed logs larger than ${MAX_SIZE_MB}MB..."
  find "${LOG_DIR}" -name "*.log" -not -name "*.gz" \
    -size "+${MAX_SIZE_MB}M" | while read -r f; do
    local size
    size=$(du -sh "${f}" | cut -f1)
    info "Compressing ${f} (${size})"
    run_or_dry gzip -9 "${f}"
    (( FILES_DELETED++ )) || true
  done
}

delete_old_logs() {
  info "Deleting logs older than ${RETENTION_DAYS} days..."
  while IFS= read -r f; do
    local bytes
    bytes=$(stat -c%s "${f}" 2>/dev/null || stat -f%z "${f}" 2>/dev/null || echo 0)
    info "Removing: ${f}"
    run_or_dry rm -f "${f}"
    (( FILES_DELETED++ )) || true
    (( BYTES_FREED += bytes )) || true
  done < <(find "${LOG_DIR}" \
    \( -name "*.log" -o -name "*.log.gz" -o -name "*.log.*.gz" \) \
    -mtime "+${RETENTION_DAYS}" 2>/dev/null)
}

report() {
  local freed_mb=$(( BYTES_FREED / 1048576 ))
  ok "Cleanup complete: ${FILES_DELETED} files removed, ~${freed_mb}MB freed."

  [[ -z "${SLACK_WEBHOOK_URL}" ]] && return 0
  curl -s -X POST "${SLACK_WEBHOOK_URL}" \
    -H 'Content-type: application/json' \
    --data "{\"text\":\"🧹 Log cleanup: ${FILES_DELETED} files removed (~${freed_mb}MB freed)\"}" \
    > /dev/null
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) DRY_RUN=true; shift ;;
      --dir)     LOG_DIR="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  info "=== Log Cleanup | dir=${LOG_DIR} | retain=${RETENTION_DAYS}d | dry=${DRY_RUN} ==="

  [[ -d "${LOG_DIR}" ]] || { warn "Log dir '${LOG_DIR}' not found. Skipping."; exit 0; }

  compress_large_logs
  delete_old_logs
  report
}

main "$@"
