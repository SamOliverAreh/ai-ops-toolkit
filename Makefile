# =============================================================================
# AI Ops Toolkit — Makefile
# =============================================================================
.DEFAULT_GOAL := help
.PHONY: help install test test-python test-bash lint format clean \
        docker-build docker-up docker-down demo health backup monitor

PYTHON      := python3
PIP         := pip3
PYTEST      := pytest
RUFF        := ruff
BLACK       := black
SCRIPTS_PY  := scripts/python
TESTS_PY    := tests/python
TESTS_BASH  := tests/bash

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  AI Ops Automation Toolkit"
	@echo "  ────────────────────────────────────────────────"
	@echo "  Setup"
	@echo "    make install        Install Python dependencies"
	@echo "    make setup-dirs     Create required directories"
	@echo ""
	@echo "  Development"
	@echo "    make lint           Run ruff + shellcheck"
	@echo "    make format         Auto-format with black + ruff --fix"
	@echo "    make test           Run all tests"
	@echo "    make test-python    Run Python tests only"
	@echo "    make test-bash      Run Bash tests only (requires bats-core)"
	@echo "    make coverage       Run tests with HTML coverage report"
	@echo ""
	@echo "  Docker"
	@echo "    make docker-build   Build the Docker image"
	@echo "    make docker-up      Start full monitoring stack"
	@echo "    make docker-down    Stop and remove containers"
	@echo ""
	@echo "  Run Scripts"
	@echo "    make health         Run health check"
	@echo "    make backup         Run model backup (dry-run)"
	@echo "    make monitor        Run model monitor (demo mode)"
	@echo "    make sla            Run SLA monitor (demo mode)"
	@echo "    make pipeline       Run data pipeline (demo mode)"
	@echo "    make report         Generate ops report (demo mode)"
	@echo "    make demo           Run all demo scripts"
	@echo ""
	@echo "  Maintenance"
	@echo "    make clean          Remove build artifacts and caches"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	$(PIP) install -r requirements.txt

setup-dirs:
	mkdir -p logs output logs/monitoring

# ── Linting ───────────────────────────────────────────────────────────────────
lint:
	@echo "→ ruff check..."
	$(RUFF) check $(SCRIPTS_PY)/ $(TESTS_PY)/
	@echo "→ black check..."
	$(BLACK) --check $(SCRIPTS_PY)/ $(TESTS_PY)/
	@echo "→ shellcheck..."
	@which shellcheck > /dev/null && find scripts/bash -name "*.sh" -exec shellcheck {} + || echo "shellcheck not installed — skipping"
	@echo "✅ Lint passed"

format:
	$(RUFF) check --fix $(SCRIPTS_PY)/ $(TESTS_PY)/ || true
	$(BLACK) $(SCRIPTS_PY)/ $(TESTS_PY)/

# ── Testing ───────────────────────────────────────────────────────────────────
test: test-python test-bash

test-python: setup-dirs
	$(PYTEST) $(TESTS_PY)/ -v --tb=short

test-bash:
	@which bats > /dev/null || (echo "bats-core not found. Install: https://bats-core.readthedocs.io" && exit 1)
	bats $(TESTS_BASH)/

coverage: setup-dirs
	$(PYTEST) $(TESTS_PY)/ \
		--cov=$(SCRIPTS_PY) \
		--cov-report=html:coverage_html \
		--cov-report=term-missing \
		-v
	@echo "Coverage report: coverage_html/index.html"

# ── Docker ────────────────────────────────────────────────────────────────────
docker-build:
	docker build -f github-actions/docker/Dockerfile -t ai-ops-toolkit:local .

docker-up:
	docker-compose up -d
	@echo "Grafana:    http://localhost:3000  (admin/admin)"
	@echo "Prometheus: http://localhost:9090"

docker-down:
	docker-compose down

# ── Demo runs ─────────────────────────────────────────────────────────────────
health: setup-dirs
	bash scripts/bash/health_check.sh || true

backup: setup-dirs
	bash scripts/bash/model_backup.sh --dry-run || true

monitor: setup-dirs
	SLACK_WEBHOOK_URL="" $(PYTHON) $(SCRIPTS_PY)/model_monitor.py --demo

sla: setup-dirs
	SLACK_WEBHOOK_URL="" $(PYTHON) $(SCRIPTS_PY)/sla_monitor.py --source demo

pipeline: setup-dirs
	SLACK_WEBHOOK_URL="" $(PYTHON) $(SCRIPTS_PY)/data_pipeline.py --demo

report: setup-dirs
	SLACK_WEBHOOK_URL="" $(PYTHON) $(SCRIPTS_PY)/report_emailer.py --demo --save output/report.html
	@echo "Report saved: output/report.html"

jira: setup-dirs
	SLACK_WEBHOOK_URL="" $(PYTHON) $(SCRIPTS_PY)/jira_analyzer.py --source demo

demo: setup-dirs monitor sla pipeline report jira
	@echo ""
	@echo "✅ All demo scripts completed."
	@echo "   Check: output/ and logs/monitoring/ for outputs."

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache"   -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "coverage_html" -exec rm -rf {} + 2>/dev/null || true
	rm -f coverage.xml .coverage
	@echo "✅ Clean complete."
