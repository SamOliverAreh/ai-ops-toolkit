"""tests/python/test_sla_monitor.py"""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "python"))

from sla_monitor import SLAMonitor, Ticket, SLAViolation, demo_tickets


class TestSLAMonitor:
    def setup_method(self):
        self.monitor = SLAMonitor()

    def _make_ticket(self, priority="High", hours_old=30, resolved=False):
        now = datetime.now(timezone.utc)
        t = Ticket(
            key="TEST-001",
            summary="Test ticket",
            priority=priority,
            status="Resolved" if resolved else "Open",
            created_at=now - timedelta(hours=hours_old),
            resolved_at=(now - timedelta(hours=1)) if resolved else None,
            assignee="alice",
            sla_hours=SLAMonitor.SLA_TARGETS[priority],
        )
        return t

    def test_no_violations_on_track(self):
        ticket = self._make_ticket(priority="High", hours_old=10)  # < 24h SLA
        violations = self.monitor.check_tickets([ticket])
        assert violations == []

    def test_violation_detected(self):
        ticket = self._make_ticket(priority="High", hours_old=30)  # > 24h SLA
        violations = self.monitor.check_tickets([ticket])
        assert len(violations) == 1
        assert violations[0].overage_hours > 0

    def test_critical_violation(self):
        ticket = self._make_ticket(priority="High", hours_old=60)  # >150% of 24h
        violations = self.monitor.check_tickets([ticket])
        assert violations[0].severity == "critical"

    def test_warning_violation(self):
        ticket = self._make_ticket(priority="High", hours_old=28)  # just over, <150%
        violations = self.monitor.check_tickets([ticket])
        assert violations[0].severity == "warning"

    def test_resolved_tickets_skipped(self):
        ticket = self._make_ticket(priority="Critical", hours_old=100, resolved=True)
        violations = self.monitor.check_tickets([ticket])
        assert violations == []

    def test_demo_tickets(self):
        tickets = demo_tickets()
        assert len(tickets) > 0
        violations = self.monitor.check_tickets(tickets)
        # Some demo tickets are intentionally overdue
        assert any(v.severity in ("warning", "critical") for v in violations)

    def test_multiple_priorities(self, mocker):
        mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)
        tickets = [
            self._make_ticket("Critical", hours_old=6),   # breached: SLA=4h
            self._make_ticket("Medium",   hours_old=10),  # on track: SLA=72h
            self._make_ticket("High",     hours_old=30),  # breached: SLA=24h
        ]
        violations = self.monitor.check_tickets(tickets)
        assert len(violations) == 2

    def test_report_no_violations(self, mocker):
        mock_send = mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)
        result = self.monitor.report([])
        assert result == "no_violations"
        mock_send.assert_called_once()

    def test_report_with_violations(self, mocker):
        mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)
        ticket = self._make_ticket(priority="Critical", hours_old=10)
        violation = SLAViolation(ticket=ticket, elapsed_hours=10, overage_hours=6, severity="critical")
        result = self.monitor.report([violation])
        assert "violations" in result
