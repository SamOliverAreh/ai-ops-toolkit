# Incident Runbooks

## RB-001: Model Performance Degraded

**Alert**: `ModelPerformanceDegraded` (accuracy < 0.80)

**Steps**:
1. Check recent prediction volume: `python scripts/python/model_monitor.py --demo`
2. Look for data distribution shifts in `logs/monitoring/`
3. Check if training data pipeline ran recently
4. If drift confirmed → trigger retrain: `bash scripts/bash/retrain_scheduler.sh --force`
5. Monitor post-retrain metrics for 1 hour

**Escalate if**: accuracy stays below 0.75 after retrain

---

## RB-002: Disk Space Critical

**Alert**: `DiskSpaceCritical` (>90%)

**Steps**:
1. Run cleanup: `bash scripts/bash/log_cleanup.sh`
2. Check model backup dir: `du -sh $BACKUP_DEST`
3. Remove backups older than retention: `bash scripts/bash/model_backup.sh` (prunes automatically)
4. Identify large files: `du -sh /* 2>/dev/null | sort -rh | head -20`

---

## RB-003: SLA Breach

**Alert**: Slack `#ops-alerts` — SLA Critical

**Steps**:
1. Run SLA report: `python scripts/python/sla_monitor.py --source jira`
2. Check `output/jira_analysis.csv` for breached tickets
3. Escalate critical tickets to assignee directly
4. Update Jira ticket with breach timestamp

---

## RB-004: Health Check Failing in CI

**Alert**: GitHub Actions CI failure on `demo-runs` job

**Steps**:
1. Check Actions logs for which script failed
2. Run locally: `make demo`
3. Check `.env` — missing vars cause silent failures
4. Run with verbose: `bash -x scripts/bash/health_check.sh`

---

## RB-005: Docker Stack Not Starting

**Steps**:
1. `docker-compose logs prometheus` — check config errors
2. Validate `monitoring/prometheus.yml`: `promtool check config monitoring/prometheus.yml`
3. Free port conflicts: `lsof -i :9090,3000,9093`
4. Reset volumes: `docker-compose down -v && docker-compose up -d`
