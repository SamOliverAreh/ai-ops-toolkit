#!/usr/bin/env bash
# =============================================================================
# health_check.sh — System + API endpoint health monitoring
#
# Usage:  ./health_check.sh [--json] [--config path/to/config.yaml]
# Exit:   0 = all healthy, 1 = degraded, 2 = critical failure
# =============================================================================
set -euo pipefail

: "${SLACK_WEBHOOK_URL:=}"
: "${LOG_DIR:=./logs}"
: "${METRICS_PORT:=8000}"
: "${JSON_OUTPUT:=false}"

TIMESTAMP=$(date +"%Y-%m-%dT%H:%M:%S")
STATUS=0   # 0=ok, 1=warn, 2=critical
declare -a ISSUES=()
declare -a METRICS=()

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/health_check.log"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[${TIMESTAMP}] [$1] $2" | tee -a "${LOG_FILE}"; }
info() { log "INFO " "$1"; }
warn() { log "WARN " "$1"; STATUS=$(( STATUS < 1 ? 1 : STATUS )); ISSUES+=("$1"); }
crit() { log "CRIT " "$1"; STATUS=2; ISSUES+=("$1"); }
ok()   { log "OK   " "$1"; }

# ── 1. CPU Check ──────────────────────────────────────────────────────────────
check_cpu() {
  local threshold="${CPU_THRESHOLD_PCT:-95}"
  local cpu_idle
  cpu_idle=$(top -bn1 | grep "Cpu(s)" | awk '{print $8}' | tr -d '%id,' 2>/dev/null \
           || vmstat 1 1 | tail -1 | awk '{print $15}')
  local cpu_used=$(( 100 - ${cpu_idle%.*} ))

  METRICS+=("cpu_usage_pct=${cpu_used}")
  if (( cpu_used >= threshold )); then
    crit "CPU usage ${cpu_used}% exceeds threshold ${threshold}%"
  else
    ok "CPU: ${cpu_used}% used"
  fi
}

# ── 2. Memory Check ───────────────────────────────────────────────────────────
check_memory() {
  local threshold="${MEMORY_THRESHOLD_PCT:-90}"
  local mem_total mem_available mem_used_pct

  if [[ -f /proc/meminfo ]]; then
    mem_total=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    mem_available=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
    mem_used_pct=$(( 100 - (mem_available * 100 / mem_total) ))
  else
    # macOS fallback
    mem_total=$(sysctl hw.memsize | awk '{print $2}')
    mem_free=$(vm_stat | awk '/free/ {print $3}' | tr -d '.')
    mem_used_pct=$(( 100 - (mem_free * 4096 * 100 / mem_total) ))
  fi

  METRICS+=("memory_usage_pct=${mem_used_pct}")
  if (( mem_used_pct >= threshold )); then
    crit "Memory usage ${mem_used_pct}% exceeds threshold ${threshold}%"
  else
    ok "Memory: ${mem_used_pct}% used"
  fi
}

# ── 3. Disk Check ─────────────────────────────────────────────────────────────
check_disk() {
  local threshold="${DISK_THRESHOLD_PCT:-85}"
  while IFS= read -r line; do
    local use_pct mount
    use_pct=$(echo "${line}" | awk '{print $5}' | tr -d '%')
    mount=$(echo "${line}" | awk '{print $6}')
    METRICS+=("disk_usage_pct{mount=\"${mount}\"}=${use_pct}")
    if (( use_pct >= threshold )); then
      crit "Disk ${mount} at ${use_pct}% (threshold: ${threshold}%)"
    else
      ok "Disk ${mount}: ${use_pct}%"
    fi
  done < <(df -h | awk 'NR>1 && /^\// {print}')
}

# ── 4. API Endpoint Checks ────────────────────────────────────────────────────
check_endpoints() {
  local endpoints=(
    "model-api|${MODEL_ENDPOINT:-http://localhost:8080/predict}|GET|200|5"
    "prometheus|http://localhost:9090/-/healthy|GET|200|3"
    "grafana|http://localhost:3000/api/health|GET|200|3"
  )

  for entry in "${endpoints[@]}"; do
    IFS='|' read -r name url method expected_status timeout <<< "${entry}"
    local http_code response_time

    start_ns=$(date +%s%N 2>/dev/null || echo 0)
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
      --max-time "${timeout}" \
      -X "${method}" \
      "${url}" 2>/dev/null || echo "000")
    end_ns=$(date +%s%N 2>/dev/null || echo 0)
    response_time=$(( (end_ns - start_ns) / 1000000 ))

    METRICS+=("endpoint_status{name=\"${name}\"}=$([ "${http_code}" = "${expected_status}" ] && echo 1 || echo 0)")
    METRICS+=("endpoint_response_ms{name=\"${name}\"}=${response_time}")

    if [[ "${http_code}" != "${expected_status}" ]]; then
      warn "Endpoint '${name}' returned ${http_code} (expected ${expected_status}) at ${url}"
    else
      ok "Endpoint '${name}': HTTP ${http_code} in ${response_time}ms"
    fi
  done
}

# ── 5. Process Checks ─────────────────────────────────────────────────────────
check_processes() {
  local critical_procs=("prometheus" "grafana-server" "node_exporter")

  for proc in "${critical_procs[@]}"; do
    if pgrep -x "${proc}" &>/dev/null; then
      ok "Process '${proc}' is running"
    else
      warn "Process '${proc}' is NOT running"
    fi
  done
}

# ── 6. Export Prometheus metrics ──────────────────────────────────────────────
export_metrics() {
  local metrics_file="/tmp/health_metrics.prom"
  {
    echo "# HELP ai_ops_health_check_timestamp Unix timestamp of last health check"
    echo "# TYPE ai_ops_health_check_timestamp gauge"
    echo "ai_ops_health_check_timestamp $(date +%s)"
    echo ""
    echo "# HELP ai_ops_health_status Overall health status (0=ok, 1=warn, 2=critical)"
    echo "# TYPE ai_ops_health_status gauge"
    echo "ai_ops_health_status ${STATUS}"
    echo ""
    for metric in "${METRICS[@]}"; do
      echo "ai_ops_${metric}"
    done
  } > "${metrics_file}"
  info "Prometheus metrics written to ${metrics_file}"
}

# ── Notify ────────────────────────────────────────────────────────────────────
notify() {
  [[ -z "${SLACK_WEBHOOK_URL}" ]] && return 0

  local emoji color msg
  case ${STATUS} in
    0) emoji="✅"; color="good";    msg="All systems healthy" ;;
    1) emoji="⚠️"; color="warning"; msg="Degraded: ${ISSUES[*]:-unknown}" ;;
    2) emoji="🚨"; color="danger";  msg="CRITICAL: ${ISSUES[*]:-unknown}" ;;
  esac

  curl -s -X POST "${SLACK_WEBHOOK_URL}" \
    -H 'Content-type: application/json' \
    --data "{\"attachments\":[{\"color\":\"${color}\",\"title\":\"${emoji} Health Check — ${TIMESTAMP}\",\"text\":\"${msg}\"}]}" \
    > /dev/null
}

# ── JSON output ───────────────────────────────────────────────────────────────
output_json() {
  local issues_json
  issues_json=$(printf '"%s",' "${ISSUES[@]:-}" | sed 's/,$//')
  cat <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "status": ${STATUS},
  "status_label": $([ ${STATUS} -eq 0 ] && echo '"ok"' || [ ${STATUS} -eq 1 ] && echo '"degraded"' || echo '"critical"'),
  "issues": [${issues_json}]
}
EOF
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)   JSON_OUTPUT=true; shift ;;
      --help)   echo "Usage: $0 [--json]"; exit 0 ;;
      *)        shift ;;
    esac
  done

  info "=== AI Ops Health Check ==="

  check_cpu
  check_memory
  check_disk
  check_endpoints
  check_processes
  export_metrics
  notify

  if [[ "${JSON_OUTPUT}" == "true" ]]; then
    output_json
  fi

  case ${STATUS} in
    0) info "Result: ALL HEALTHY"; exit 0 ;;
    1) warn "Result: DEGRADED — ${#ISSUES[@]} issue(s)"; exit 1 ;;
    2) crit "Result: CRITICAL — ${#ISSUES[@]} issue(s)"; exit 2 ;;
  esac
}

main "$@"
