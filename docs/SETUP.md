# Setup Guide

## Prerequisites

| Tool | Min Version | Install |
|------|------------|---------|
| Python | 3.10+ | [python.org](https://python.org) |
| Docker | 24+ | [docs.docker.com](https://docs.docker.com) |
| Docker Compose | v2 | bundled with Docker Desktop |
| bash | 4.0+ | system |
| shellcheck | any | `apt install shellcheck` / `brew install shellcheck` |
| bats-core | 1.10+ | see below |

---

## 1. Clone & configure

```bash
git clone https://github.com/YOUR_USERNAME/ai-ops-toolkit.git
cd ai-ops-toolkit
cp .env.example .env
```

Edit `.env` with your real credentials. At minimum set:
- `SLACK_WEBHOOK_URL` — for alert notifications
- `MODEL_ARTIFACT_DIR` — path to your ML model files

---

## 2. Python environment

```bash
# Option A: system pip
pip install -r requirements.txt

# Option B: virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3. Verify installation

```bash
make demo    # runs all scripts in demo mode
make test    # runs test suite
```

---

## 4. Start monitoring stack

```bash
docker-compose up -d
```

- Grafana: http://localhost:3000 (login: admin/admin)
- Prometheus: http://localhost:9090
- Alertmanager: http://localhost:9093

---

## 5. Install bats-core (bash testing)

```bash
# Linux/macOS
git clone https://github.com/bats-core/bats-core.git /tmp/bats
sudo /tmp/bats/install.sh /usr/local

# macOS with Homebrew
brew install bats-core
```

---

## 6. Set up cron jobs (optional)

```bash
# Edit crontab
crontab -e

# Add these lines:
0 2 * * * /path/to/ai-ops-toolkit/scripts/bash/model_backup.sh >> /var/log/ai-ops/backup.log 2>&1
*/15 * * * * /path/to/ai-ops-toolkit/scripts/bash/health_check.sh >> /var/log/ai-ops/health.log 2>&1
0 1 * * * /path/to/ai-ops-toolkit/scripts/bash/log_cleanup.sh >> /var/log/ai-ops/cleanup.log 2>&1
0 3 * * 0 /path/to/ai-ops-toolkit/scripts/bash/retrain_scheduler.sh >> /var/log/ai-ops/retrain.log 2>&1
```

---

## 6. Configure GitHub Actions

Add these repository secrets (Settings → Secrets → Actions):

| Secret | Description |
|--------|-------------|
| `SLACK_WEBHOOK_URL` | Slack incoming webhook |
| `ALERT_EMAIL_TO` | Alert email recipient |
| `SENDGRID_API_KEY` | SendGrid API key for emails |
| `GITHUB_TOKEN` | Auto-provided by GitHub |

Then copy the workflows to the right place:

```bash
mkdir -p .github/workflows
cp github-actions/workflows/*.yml .github/workflows/
```
