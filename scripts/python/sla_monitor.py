"""
scripts/python/sla_monitor.py
SLA breach detection and alerting from Jira or CSV data sources.

Usage:
  python sla_monitor.py --source jira
  python sla_monitor.py --source csv --file tickets.csv
  python sla_monitor.py --demo
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from slack_notifier import get_notifier

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@dataclass
class Ticket:
    key: str
    summary: str
    priority: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    assignee: str
    sla_hours: float   # target resolution time


@dataclass
class SLAViolation:
    ticket: Ticket
    elapsed_hours: float
    overage_hours: float
    severity: str   # "critical" | "warning"


class SLAMonitor:
    """Detect SLA breaches and send actionable alerts."""

    # SLA targets by priority (hours)
    SLA_TARGETS = {
        "Critical":  4.0,
        "High":     24.0,
        "Medium":   72.0,
        "Low":     168.0,   # 7 days
    }

    CRITICAL_MULTIPLIER = 1.5   # breach by >50% = critical

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.notifier = get_notifier()
        self.now = datetime.now(timezone.utc)

    def calculate_elapsed(self, ticket: Ticket) -> float:
        """Business-aware elapsed hours (placeholder: calendar hours)."""
        end = ticket.resolved_at or self.now
        # Ensure timezone-aware comparison
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        created = ticket.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (end - created).total_seconds() / 3600

    def check_tickets(self, tickets: list[Ticket]) -> list[SLAViolation]:
        violations = []
        for t in tickets:
            if t.status.lower() in ("closed", "resolved", "done"):
                continue   # skip resolved tickets

            elapsed = self.calculate_elapsed(t)
            target = self.SLA_TARGETS.get(t.priority, 72.0)

            if elapsed > target:
                overage = elapsed - target
                severity = "critical" if elapsed > target * self.CRITICAL_MULTIPLIER else "warning"
                violations.append(SLAViolation(
                    ticket=t,
                    elapsed_hours=round(elapsed, 1),
                    overage_hours=round(overage, 1),
                    severity=severity,
                ))
                logger.warning(
                    "[%s] %s | %s | elapsed=%.1fh target=%.1fh overage=%.1fh",
                    severity.upper(), t.key, t.priority, elapsed, target, overage,
                )
            else:
                remaining = target - elapsed
                logger.info("[OK] %s | %s | %.1fh remaining", t.key, t.priority, remaining)

        return violations

    def report(self, violations: list[SLAViolation]) -> str:
        if not violations:
            logger.info("✅ No SLA violations detected.")
            self.notifier.info(
                "✅ SLA Check Passed",
                "All active tickets are within SLA targets.",
            )
            return "no_violations"

        critical = [v for v in violations if v.severity == "critical"]
        warnings = [v for v in violations if v.severity == "warning"]

        lines = [f"*{len(violations)} SLA Violation(s)* detected:\n"]
        if critical:
            lines.append(f"🚨 *Critical ({len(critical)}):*")
            for v in critical:
                lines.append(
                    f"  • <{self._jira_url(v.ticket.key)}|{v.ticket.key}> — "
                    f"{v.ticket.summary[:60]} | "
                    f"Overdue by *{v.overage_hours:.1f}h* ({v.ticket.priority})"
                )
        if warnings:
            lines.append(f"\n⚠️ *Warning ({len(warnings)}):*")
            for v in warnings:
                lines.append(
                    f"  • <{self._jira_url(v.ticket.key)}|{v.ticket.key}> — "
                    f"{v.ticket.summary[:60]} | "
                    f"Overdue by {v.overage_hours:.1f}h"
                )

        text = "\n".join(lines)

        if critical:
            self.notifier.critical("🚨 SLA Critical Violations", text)
        else:
            self.notifier.warning("⚠️ SLA Warnings", text)

        logger.info("Sent SLA alert: %d critical, %d warning", len(critical), len(warnings))
        return f"violations:{len(violations)}"

    def _jira_url(self, key: str) -> str:
        server = os.environ.get("JIRA_SERVER", "https://yourorg.atlassian.net")
        return f"{server}/browse/{key}"


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_from_jira() -> list[Ticket]:
    """Load open tickets from Jira REST API."""
    try:
        from jira import JIRA
    except ImportError:
        raise ImportError("Install jira: pip install jira")

    server = os.environ["JIRA_SERVER"]
    user = os.environ["JIRA_USER"]
    token = os.environ["JIRA_API_TOKEN"]
    project = os.environ.get("JIRA_PROJECT_KEY", "OPS")

    j = JIRA(server=server, basic_auth=(user, token))
    issues = j.search_issues(
        f'project={project} AND status not in (Closed, Resolved, Done) ORDER BY created ASC',
        maxResults=200,
    )

    tickets = []
    for issue in issues:
        created = datetime.fromisoformat(issue.fields.timecreated.replace("Z", "+00:00"))
        tickets.append(Ticket(
            key=issue.key,
            summary=str(issue.fields.summary),
            priority=str(issue.fields.priority),
            status=str(issue.fields.status),
            created_at=created,
            resolved_at=None,
            assignee=str(getattr(issue.fields.assignee, "displayName", "Unassigned")),
            sla_hours=SLAMonitor.SLA_TARGETS.get(str(issue.fields.priority), 72),
        ))
    return tickets


def load_from_csv(filepath: str) -> list[Ticket]:
    """Load tickets from a CSV file with columns: key, summary, priority, status, created_at."""
    tickets = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tickets.append(Ticket(
                key=row["key"],
                summary=row["summary"],
                priority=row.get("priority", "Medium"),
                status=row.get("status", "Open"),
                created_at=datetime.fromisoformat(row["created_at"]),
                resolved_at=(
                    datetime.fromisoformat(row["resolved_at"])
                    if row.get("resolved_at") else None
                ),
                assignee=row.get("assignee", "Unassigned"),
                sla_hours=float(row.get("sla_hours", 72)),
            ))
    return tickets


def demo_tickets() -> list[Ticket]:
    """Generate synthetic tickets for testing."""
    now = datetime.now(timezone.utc)
    return [
        Ticket("OPS-001", "Production API latency spike", "Critical",  "In Progress", now - timedelta(hours=6),   None, "alice", 4),
        Ticket("OPS-002", "Database backup failure",      "High",      "Open",        now - timedelta(hours=30),  None, "bob",   24),
        Ticket("OPS-003", "Model serving OOM error",      "High",      "In Progress", now - timedelta(hours=20),  None, "carol", 24),
        Ticket("OPS-004", "Log rotation not running",     "Medium",    "Open",        now - timedelta(hours=50),  None, "dave",  72),
        Ticket("OPS-005", "Dashboard data stale",         "Low",       "Open",        now - timedelta(hours=10),  None, "eve",   168),
    ]


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SLA breach monitor")
    parser.add_argument("--source", choices=["jira", "csv", "demo"], default="demo")
    parser.add_argument("--file", help="CSV file path (required if --source csv)")
    parser.add_argument("--config", default="configs/config.yaml")
    args = parser.parse_args()

    config = {}
    if Path(args.config).exists():
        with open(args.config) as f:
            config = yaml.safe_load(f)

    monitor = SLAMonitor(config)

    if args.source == "jira":
        tickets = load_from_jira()
    elif args.source == "csv":
        if not args.file:
            parser.error("--file is required with --source csv")
        tickets = load_from_csv(args.file)
    else:
        tickets = demo_tickets()

    logger.info("Checking %d tickets...", len(tickets))
    violations = monitor.check_tickets(tickets)
    result = monitor.report(violations)
    print(f"Result: {result} | Violations: {len(violations)}")


if __name__ == "__main__":
    main()
