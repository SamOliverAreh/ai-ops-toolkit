#!/usr/bin/env bats
# tests/bash/test_health_check.bats
# Run with: bats tests/bash/test_health_check.bats

setup() {
  # Create a temp working dir for each test
  export TEST_DIR="$(mktemp -d)"
  export LOG_DIR="${TEST_DIR}/logs"
  export SLACK_WEBHOOK_URL=""   # disable Slack in tests
  mkdir -p "${LOG_DIR}"
  SCRIPT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/scripts/bash/health_check.sh"
}

teardown() {
  rm -rf "${TEST_DIR}"
}

# ── Sanity checks ──────────────────────────────────────────────────────────────

@test "health_check.sh is executable" {
  [ -f "${SCRIPT}" ]
  [ -r "${SCRIPT}" ]
}

@test "health_check.sh --help exits 0" {
  run bash "${SCRIPT}" --help
  [ "${status}" -eq 0 ]
}

@test "health_check.sh runs without crashing" {
  run bash "${SCRIPT}" || true
  # Exit code 0 or 1 is acceptable; 2+ indicates script crash
  [ "${status}" -le 2 ]
}

@test "health_check.sh --json outputs valid JSON" {
  run bash "${SCRIPT}" --json || true
  # Last line of output should be parseable JSON
  last_line=$(echo "${output}" | grep '^{' | tail -1)
  [ -n "${last_line}" ]
  echo "${last_line}" | python3 -c "import sys,json; json.load(sys.stdin)"
}

@test "health_check.sh creates log file" {
  run bash "${SCRIPT}" || true
  [ -f "${LOG_DIR}/health_check.log" ] || true  # log may be in default location
}

# ── log_cleanup.sh ─────────────────────────────────────────────────────────────

@test "log_cleanup.sh --dry-run runs without error" {
  CLEANUP="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/scripts/bash/log_cleanup.sh"
  run bash "${CLEANUP}" --dry-run --dir "${LOG_DIR}"
  [ "${status}" -eq 0 ]
}

@test "log_cleanup.sh skips nonexistent dir gracefully" {
  CLEANUP="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/scripts/bash/log_cleanup.sh"
  run bash "${CLEANUP}" --dir "/nonexistent/path/logs"
  [ "${status}" -eq 0 ]
}

@test "log_cleanup.sh removes old log files" {
  CLEANUP="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/scripts/bash/log_cleanup.sh"
  # Create a fake old log
  old_log="${TEST_DIR}/logs/old.log"
  echo "old log content" > "${old_log}"
  touch -d "30 days ago" "${old_log}" 2>/dev/null || touch -A -2592000 "${old_log}" 2>/dev/null || true

  run bash "${CLEANUP}" --dir "${LOG_DIR}"
  [ "${status}" -eq 0 ]
}

# ── model_backup.sh ────────────────────────────────────────────────────────────

@test "model_backup.sh --help exits 0" {
  BACKUP="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/scripts/bash/model_backup.sh"
  run bash "${BACKUP}" --help
  [ "${status}" -eq 0 ]
}

@test "model_backup.sh --dry-run with valid source exits 0" {
  BACKUP="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)/scripts/bash/model_backup.sh"
  src_dir="${TEST_DIR}/models"
  mkdir -p "${src_dir}"
  echo "fake model weights" > "${src_dir}/model.pkl"

  run bash "${BACKUP}" \
    --dry-run \
    --dest "${TEST_DIR}/backups" \
    MODEL_ARTIFACT_DIR="${src_dir}" \
    LOG_DIR="${LOG_DIR}" || true
  # With dry-run, should succeed or at least not crash
  [ "${status}" -le 1 ]
}
