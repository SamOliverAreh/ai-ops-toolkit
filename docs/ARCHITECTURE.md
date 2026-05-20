# Architecture Overview

## System Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     AI Ops Toolkit                           │
│                                                              │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐  │
│  │  Bash Layer │   │ Python Layer │   │  Monitoring Stack│  │
│  │             │   │              │   │                  │  │
│  │ health_check│   │model_monitor │   │   Prometheus     │  │
│  │ model_backup│──▶│sla_monitor   │──▶│   Grafana        │  │
│  │ log_cleanup │   │data_pipeline │   │   Alertmanager   │  │
│  │ retrain_sch │   │report_emailer│   │   Node Exporter  │  │
│  └──────┬──────┘   └──────┬───────┘   └──────────────────┘  │
│         │                 │                                  │
│         └────────┬────────┘                                  │
│                  ▼                                           │
│          ┌───────────────┐                                   │
│          │ Notifications │                                   │
│          │  Slack + Email│                                   │
│          └───────────────┘                                   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │               GitHub Actions CI/CD                    │   │
│  │  ci.yml ▸ lint ▸ test ▸ demo   docker.yml ▸ build   │   │
│  │  retrain.yml ▸ drift check ▸ retrain ▸ validate      │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Data Flow

```
External Sources           Processing               Outputs
─────────────────          ──────────              ──────────
Postgres / CSV ────────▶ data_pipeline.py ────────▶ CSV / DB
Jira API       ────────▶ jira_analyzer.py ────────▶ CSV + Slack
Model API      ────────▶ model_monitor.py ────────▶ JSON + Slack
System metrics ────────▶ health_check.sh  ────────▶ Prometheus
All above      ────────▶ report_emailer   ────────▶ HTML Email
```

## Key Design Decisions

**1. No framework lock-in**
Each script is independently runnable. No shared state between modules except the config YAML and env vars.

**2. Retry everywhere**
All external I/O (API calls, DB connections, Slack webhooks) uses `tenacity` or bash retry loops with exponential backoff.

**3. Dry-run mode on all bash scripts**
Every destructive bash script (`model_backup.sh`, `log_cleanup.sh`) supports `--dry-run` for safe testing.

**4. Observability first**
Every script writes structured logs and exports Prometheus metrics where applicable.

**5. Config hierarchy**
`configs/config.yaml` → overridden by `.env` → overridden by CLI flags. Predictable and auditable.
