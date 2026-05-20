#!/usr/bin/env bash
# =============================================================================
# model_backup.sh — Automated ML model artifact backup with versioning
#
# Usage:  ./model_backup.sh [--dry-run] [--dest s3://bucket/path]
# Cron:   0 2 * * * /opt/ai-ops/scripts/bash/model_backup.sh >> /var/log/ai-ops/backup.log 2>&1
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

# ── Config (override via environment) ────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
: "${MODEL_ARTIFACT_DIR:=/opt/models}"
: "${BACKUP_DEST:=./backups/models}"
: "${RETENTION_DAYS:=30}"
: "${SLACK_WEBHOOK_URL:=}"
: "${LOG_DIR:=${ROOT_DIR}/logs}"
: "${DRY_RUN:=false}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="model_backup_${TIMESTAMP}.tar.gz"
LOG_FILE="${LOG_DIR}/backup.log"
EXIT_CODE=0

# ── Helpers ───────────────────────────────────────────────────────────────────
log() { echo "[$(date +"%Y-%m-%dT%H:%M:%S")] [$1] $2" | tee -a "${LOG_FILE}"; }
info()    { log "INFO " "$1"; }
warn()    { log "WARN " "$1"; }
error()   { log "ERROR" "$1" >&2; }
success() { log "OK   " "$1"; }

notify_slack() {
  local msg="$1" color="${2:-good}"
  [[ -z "${SLACK_WEBHOOK_URL}" ]] && return 0
  curl -s -X POST "${SLACK_WEBHOOK_URL}" \
    -H 'Content-type: application/json' \
    --data "{\"attachments\":[{\"color\":\"${color}\",\"text\":\"${msg}\"}]}" \
    > /dev/null
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) DRY_RUN=true; shift ;;
      --dest)    BACKUP_DEST="$2"; shift 2 ;;
      --help)
        echo "Usage: $0 [--dry-run] [--dest <path|s3://...|gs://...>]"
        exit 0 ;;
      *) error "Unknown option: $1"; exit 1 ;;
    esac
  done
}

# ── Pre-flight checks ─────────────────────────────────────────────────────────
preflight() {
  info "Running pre-flight checks..."
  mkdir -p "${LOG_DIR}"

  if [[ ! -d "${MODEL_ARTIFACT_DIR}" ]]; then
    error "MODEL_ARTIFACT_DIR '${MODEL_ARTIFACT_DIR}' does not exist."
    exit 1
  fi

  # Check disk space — warn if < 2GB free
  local free_kb
  free_kb=$(df -k "${MODEL_ARTIFACT_DIR}" | awk 'NR==2 {print $4}')
  if (( free_kb < 2097152 )); then
    warn "Low disk space: $(( free_kb / 1024 ))MB free on source partition."
  fi

  # Detect destination type
  if [[ "${BACKUP_DEST}" == s3://* ]]; then
    command -v aws &>/dev/null || { error "aws CLI not found. Install it or use a local path."; exit 1; }
  elif [[ "${BACKUP_DEST}" == gs://* ]]; then
    command -v gsutil &>/dev/null || { error "gsutil not found."; exit 1; }
  else
    mkdir -p "${BACKUP_DEST}"
  fi

  success "Pre-flight checks passed."
}

# ── Create backup archive ─────────────────────────────────────────────────────
create_archive() {
  local tmp_dir
  tmp_dir=$(mktemp -d)
  local archive_path="${tmp_dir}/${BACKUP_NAME}"

  info "Compressing '${MODEL_ARTIFACT_DIR}' → '${BACKUP_NAME}'..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY-RUN] Would create: ${archive_path}"
    echo "${tmp_dir}"
    return
  fi

  tar -czf "${archive_path}" \
    --exclude="*.pyc" \
    --exclude="__pycache__" \
    --exclude=".git" \
    -C "$(dirname "${MODEL_ARTIFACT_DIR}")" \
    "$(basename "${MODEL_ARTIFACT_DIR}")"

  local size
  size=$(du -sh "${archive_path}" | cut -f1)
  success "Archive created: ${BACKUP_NAME} (${size})"

  # Generate SHA256 checksum
  sha256sum "${archive_path}" > "${archive_path}.sha256"
  info "Checksum: $(cat "${archive_path}.sha256")"

  echo "${tmp_dir}"
}

# ── Upload / copy to destination ──────────────────────────────────────────────
upload_backup() {
  local tmp_dir="$1"
  local archive_path="${tmp_dir}/${BACKUP_NAME}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY-RUN] Would upload to: ${BACKUP_DEST}/${BACKUP_NAME}"
    return
  fi

  info "Uploading to '${BACKUP_DEST}'..."

  if [[ "${BACKUP_DEST}" == s3://* ]]; then
    aws s3 cp "${archive_path}" "${BACKUP_DEST}/${BACKUP_NAME}" \
      --storage-class STANDARD_IA
    aws s3 cp "${archive_path}.sha256" "${BACKUP_DEST}/${BACKUP_NAME}.sha256"
  elif [[ "${BACKUP_DEST}" == gs://* ]]; then
    gsutil -m cp "${archive_path}" "${archive_path}.sha256" "${BACKUP_DEST}/"
  else
    cp "${archive_path}" "${archive_path}.sha256" "${BACKUP_DEST}/"
  fi

  success "Upload complete."
  rm -rf "${tmp_dir}"
}

# ── Prune old backups ─────────────────────────────────────────────────────────
prune_old_backups() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY-RUN] Would prune backups older than ${RETENTION_DAYS} days."
    return
  fi

  info "Pruning backups older than ${RETENTION_DAYS} days..."

  if [[ "${BACKUP_DEST}" == s3://* ]]; then
    local cutoff
    cutoff=$(date -d "-${RETENTION_DAYS} days" +%Y-%m-%dT%H:%M:%S 2>/dev/null \
             || date -v-${RETENTION_DAYS}d +%Y-%m-%dT%H:%M:%S)  # macOS fallback
    aws s3 ls "${BACKUP_DEST}/" | while read -r line; do
      local date_str obj_name
      date_str=$(echo "${line}" | awk '{print $1"T"$2}')
      obj_name=$(echo "${line}" | awk '{print $4}')
      if [[ "${date_str}" < "${cutoff}" && "${obj_name}" == model_backup_*.tar.gz ]]; then
        info "Removing old backup: ${obj_name}"
        aws s3 rm "${BACKUP_DEST}/${obj_name}"
      fi
    done
  else
    find "${BACKUP_DEST}" -name "model_backup_*.tar.gz" \
      -mtime "+${RETENTION_DAYS}" -exec rm -f {} \;
  fi

  success "Pruning complete."
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  parse_args "$@"

  info "========================================"
  info "AI Ops — Model Backup Started"
  info "Source:      ${MODEL_ARTIFACT_DIR}"
  info "Destination: ${BACKUP_DEST}"
  info "Dry run:     ${DRY_RUN}"
  info "========================================"

  preflight

  local tmp_dir
  tmp_dir=$(create_archive)
  upload_backup "${tmp_dir}"
  prune_old_backups

  success "Backup completed successfully: ${BACKUP_NAME}"
  notify_slack "✅ *Model Backup Succeeded*\nFile: \`${BACKUP_NAME}\`\nDest: \`${BACKUP_DEST}\`" "good"
}

# ── Error trap ────────────────────────────────────────────────────────────────
trap 'EXIT_CODE=$?; \
  error "Backup FAILED at line ${LINENO} (exit ${EXIT_CODE})"; \
  notify_slack "🚨 *Model Backup FAILED*\nScript: model_backup.sh\nExit: ${EXIT_CODE}" "danger"; \
  exit ${EXIT_CODE}' ERR

main "$@"
