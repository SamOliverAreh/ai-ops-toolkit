#!/usr/bin/env bash
# =============================================================================
# retrain_scheduler.sh — Triggers model retraining pipeline
#
# Checks data drift / schedule, then dispatches a GitHub Actions workflow
# or runs a local training script based on config.
#
# Usage:  ./retrain_scheduler.sh [--force] [--dry-run]
# Cron:   0 3 * * 0 /opt/ai-ops/scripts/bash/retrain_scheduler.sh   # weekly
# =============================================================================
set -euo pipefail

: "${GITHUB_TOKEN:=}"
: "${GITHUB_REPO:=YOUR_USERNAME/ai-ops-toolkit}"
: "${RETRAIN_SCRIPT:=./scripts/python/retrain.py}"
: "${DRIFT_SCORE_FILE:=./logs/drift_score.txt}"
: "${DRIFT_THRESHOLD:=0.15}"
: "${FORCE_RETRAIN:=false}"
: "${DRY_RUN:=false}"
: "${SLACK_WEBHOOK_URL:=}"

TIMESTAMP=$(date +"%Y-%m-%dT%H:%M:%S")

log()  { echo "[${TIMESTAMP}] [$1] $2"; }
info() { log "INFO " "$1"; }
warn() { log "WARN " "$1"; }

should_retrain() {
  [[ "${FORCE_RETRAIN}" == "true" ]] && { info "Force retrain flag set."; return 0; }

  if [[ -f "${DRIFT_SCORE_FILE}" ]]; then
    local score
    score=$(cat "${DRIFT_SCORE_FILE}" | tr -d '[:space:]')
    info "Current drift score: ${score} (threshold: ${DRIFT_THRESHOLD})"
    # Use awk for float comparison (bash doesn't do floats)
    if awk -v s="${score}" -v t="${DRIFT_THRESHOLD}" 'BEGIN{exit !(s > t)}'; then
      info "Drift score exceeds threshold — retraining required."
      return 0
    else
      info "Drift score within threshold — skipping retrain."
      return 1
    fi
  else
    warn "No drift score file found. Running retrain as precaution."
    return 0
  fi
}

dispatch_github_actions() {
  info "Dispatching GitHub Actions retraining workflow..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY-RUN] Would POST to GitHub Actions workflow dispatch API."
    return 0
  fi

  local response
  response=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/retrain.yml/dispatches" \
    -d '{"ref":"main","inputs":{"reason":"drift_detected"}}')

  local http_code
  http_code=$(echo "${response}" | tail -1)
  if [[ "${http_code}" == "204" ]]; then
    info "GitHub Actions workflow dispatched successfully."
  else
    warn "GitHub Actions dispatch returned HTTP ${http_code}."
    return 1
  fi
}

run_local_retrain() {
  info "Running local retraining script: ${RETRAIN_SCRIPT}"
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY-RUN] Would run: python ${RETRAIN_SCRIPT}"
    return 0
  fi

  if [[ -f "${RETRAIN_SCRIPT}" ]]; then
    python "${RETRAIN_SCRIPT}" --timestamp "${TIMESTAMP}"
  else
    warn "Retrain script not found: ${RETRAIN_SCRIPT}"
  fi
}

notify() {
  local msg="$1" color="${2:-good}"
  [[ -z "${SLACK_WEBHOOK_URL}" ]] && return 0
  curl -s -X POST "${SLACK_WEBHOOK_URL}" \
    -H 'Content-type: application/json' \
    --data "{\"attachments\":[{\"color\":\"${color}\",\"text\":\"${msg}\"}]}" \
    > /dev/null
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force)   FORCE_RETRAIN=true; shift ;;
      --dry-run) DRY_RUN=true; shift ;;
      *) shift ;;
    esac
  done

  info "=== Retrain Scheduler ==="

  if ! should_retrain; then
    info "No retraining needed. Exiting."
    exit 0
  fi

  notify "🔄 *Model Retraining Triggered* ($(date +%Y-%m-%d))\nReason: drift/schedule" "warning"

  if [[ -n "${GITHUB_TOKEN}" ]]; then
    dispatch_github_actions
  else
    run_local_retrain
  fi

  notify "✅ *Model Retraining Dispatched* successfully." "good"
  info "Done."
}

main "$@"
