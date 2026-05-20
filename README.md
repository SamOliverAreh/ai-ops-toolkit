# 🤖 AI Ops Automation Toolkit

[![CI/CD Pipeline](https://github.com/YOUR_USERNAME/ai-ops-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/ai-ops-toolkit/actions)
[![Lint](https://github.com/YOUR_USERNAME/ai-ops-toolkit/actions/workflows/lint.yml/badge.svg)](https://github.com/YOUR_USERNAME/ai-ops-toolkit/actions)
[![Docker Build](https://github.com/YOUR_USERNAME/ai-ops-toolkit/actions/workflows/docker.yml/badge.svg)](https://github.com/YOUR_USERNAME/ai-ops-toolkit/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> A production-grade DevOps + AI automation toolkit bridging **data science**, **AI engineering**, and **production operations** — built to demonstrate operational maturity for DS/MLE/Data Engineering roles.

---

## 📁 Project Structure

```
ai-ops-toolkit/
├── scripts/
│   ├── bash/                  # Linux automation scripts
│   │   ├── model_backup.sh        # Auto model artifact backup to S3/GCS
│   │   ├── log_cleanup.sh         # Log rotation & cleanup
│   │   ├── retrain_scheduler.sh   # Scheduled model retraining trigger
│   │   └── health_check.sh        # System + API health monitoring
│   ├── powershell/            # Windows / enterprise scripts
│   │   ├── server_monitor.ps1     # Windows server monitoring
│   │   ├── file_automation.ps1    # File management automation
│   │   └── scheduled_report.ps1   # Automated reporting
│   └── python/                # Python automation modules
│       ├── report_emailer.py      # Automated HTML report emailer
│       ├── jira_analyzer.py       # Jira ticket SLA analysis
│       ├── sla_monitor.py         # SLA breach detection & alerting
│       ├── data_pipeline.py       # Generic ETL extraction pipeline
│       ├── model_monitor.py       # ML model drift & performance monitor
│       └── slack_notifier.py      # Slack webhook notification helper
├── monitoring/
│   ├── prometheus.yml         # Prometheus scrape config
│   ├── grafana_dashboard.json # Grafana dashboard export
│   └── alerts.yml             # Alertmanager rules
├── github-actions/
│   ├── workflows/
│   │   ├── ci.yml             # Main CI pipeline
│   │   ├── lint.yml           # Linting & code quality
│   │   ├── docker.yml         # Docker build & push
│   │   └── retrain.yml        # Scheduled model retraining workflow
│   └── docker/
│       ├── Dockerfile         # Base image for pipeline jobs
│       └── docker-compose.yml # Local dev stack
├── configs/
│   ├── config.yaml            # Central config (overridable via env)
│   └── logging.yaml           # Python logging configuration
├── tests/
│   ├── bash/
│   │   └── test_health_check.bats  # Bash unit tests (bats-core)
│   └── python/
│       ├── test_sla_monitor.py
│       ├── test_data_pipeline.py
│       └── test_model_monitor.py
├── notebooks/
│   └── ops_analysis.ipynb     # Exploratory ops analysis notebook
├── docs/
│   ├── SETUP.md               # Environment setup guide
│   ├── RUNBOOKS.md            # Incident runbooks
│   └── ARCHITECTURE.md        # System architecture overview
├── docker-compose.yml         # Root compose (monitoring stack)
├── Makefile                   # Developer convenience commands
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
├── .gitignore
└── LICENSE
```

---

## 🚀 Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/ai-ops-toolkit.git
cd ai-ops-toolkit

# 2. Copy and configure environment
cp .env.example .env
# Edit .env with your credentials

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Spin up the full monitoring stack
docker-compose up -d

# 5. Run a health check
bash scripts/bash/health_check.sh

# 6. Run all Python tests
make test
```

---

## 🧩 Modules

| Module | Language | Purpose |
|--------|----------|---------|
| `model_backup.sh` | Bash | Backs up ML model artifacts with versioning |
| `health_check.sh` | Bash | System + API endpoint health monitoring |
| `retrain_scheduler.sh` | Bash | Triggers model retraining via cron |
| `log_cleanup.sh` | Bash | Log rotation with configurable retention |
| `server_monitor.ps1` | PowerShell | Windows server CPU/memory/disk alerts |
| `report_emailer.py` | Python | Generates + emails HTML ops reports |
| `jira_analyzer.py` | Python | Pulls Jira data, calculates SLA metrics |
| `sla_monitor.py` | Python | Detects & alerts on SLA breaches |
| `data_pipeline.py` | Python | Modular ETL pipeline with retry logic |
| `model_monitor.py` | Python | ML drift detection + performance tracking |
| `slack_notifier.py` | Python | Slack webhook helper for all alerts |

---

## ⚙️ Configuration

All configuration lives in `configs/config.yaml` and can be overridden with environment variables (`.env`). See `.env.example` for all available options.

---

## 📊 Monitoring Stack

The `docker-compose.yml` spins up:
- **Prometheus** — metrics collection
- **Grafana** — dashboards (preconfigured at `localhost:3000`)
- **Alertmanager** — alert routing

---

## 🧪 Testing

```bash
make test          # Run all tests
make test-python   # Python tests only (pytest)
make test-bash     # Bash tests only (bats-core)
make lint          # Run ruff + shellcheck
```

---

## 📄 License

MIT — see [LICENSE](LICENSE)
