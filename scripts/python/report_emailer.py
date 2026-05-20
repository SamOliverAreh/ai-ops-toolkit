"""
scripts/python/report_emailer.py
Automated HTML ops report generation and emailing via SendGrid.

Usage:
  python report_emailer.py --demo
  python report_emailer.py --config configs/config.yaml
"""
from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, BaseLoader

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Ops Weekly Report — {{ report_date }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; margin: 0; padding: 0; }
  .container { max-width: 700px; margin: 0 auto; padding: 24px; }
  .header { background: linear-gradient(135deg, #1e40af, #7c3aed);
            border-radius: 12px; padding: 32px; margin-bottom: 24px; text-align: center; }
  .header h1 { margin: 0; font-size: 26px; color: #fff; }
  .header p  { margin: 8px 0 0; color: #c7d2fe; }
  .section   { background: #1e293b; border-radius: 10px; padding: 20px; margin-bottom: 16px; }
  .section h2 { margin-top: 0; font-size: 16px; text-transform: uppercase;
                letter-spacing: 0.1em; color: #94a3b8; }
  .metric-row { display: flex; gap: 12px; margin-bottom: 12px; }
  .metric-box { flex: 1; background: #0f172a; border-radius: 8px; padding: 14px; text-align: center; }
  .metric-box .val  { font-size: 28px; font-weight: 700; }
  .metric-box .lbl  { font-size: 11px; color: #94a3b8; text-transform: uppercase; margin-top: 4px; }
  .green { color: #22c55e; } .yellow { color: #f59e0b; } .red { color: #ef4444; }
  table  { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #334155; }
  th     { color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 11px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 600; }
  .badge-green  { background: #14532d; color: #4ade80; }
  .badge-yellow { background: #422006; color: #fbbf24; }
  .badge-red    { background: #450a0a; color: #f87171; }
  .footer { text-align: center; color: #475569; font-size: 12px; margin-top: 24px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🤖 AI Ops Weekly Report</h1>
    <p>{{ report_date }} · Generated automatically</p>
  </div>

  <!-- System Health -->
  <div class="section">
    <h2>🖥 System Health</h2>
    <div class="metric-row">
      <div class="metric-box">
        <div class="val {{ 'green' if health.cpu_pct < 80 else 'red' }}">{{ health.cpu_pct }}%</div>
        <div class="lbl">CPU Usage</div>
      </div>
      <div class="metric-box">
        <div class="val {{ 'green' if health.memory_pct < 80 else 'red' }}">{{ health.memory_pct }}%</div>
        <div class="lbl">Memory</div>
      </div>
      <div class="metric-box">
        <div class="val {{ 'green' if health.disk_pct < 80 else 'yellow' }}">{{ health.disk_pct }}%</div>
        <div class="lbl">Disk</div>
      </div>
      <div class="metric-box">
        <div class="val {{ 'green' if health.uptime_pct >= 99.9 else 'yellow' }}">{{ health.uptime_pct }}%</div>
        <div class="lbl">Uptime</div>
      </div>
    </div>
  </div>

  <!-- Model Performance -->
  <div class="section">
    <h2>🧠 Model Performance</h2>
    <div class="metric-row">
      <div class="metric-box">
        <div class="val {{ 'green' if model.accuracy >= 0.85 else 'yellow' }}">{{ "%.1f"|format(model.accuracy * 100) }}%</div>
        <div class="lbl">Accuracy</div>
      </div>
      <div class="metric-box">
        <div class="val {{ 'green' if model.f1 >= 0.80 else 'yellow' }}">{{ "%.3f"|format(model.f1) }}</div>
        <div class="lbl">F1 Score</div>
      </div>
      <div class="metric-box">
        <div class="val {{ 'green' if model.drift_score < 0.10 else ('yellow' if model.drift_score < 0.20 else 'red') }}">{{ "%.3f"|format(model.drift_score) }}</div>
        <div class="lbl">Drift Score</div>
      </div>
      <div class="metric-box">
        <div class="val">{{ model.predictions_total }}</div>
        <div class="lbl">Predictions</div>
      </div>
    </div>
  </div>

  <!-- SLA Summary -->
  <div class="section">
    <h2>📋 SLA Summary</h2>
    <div class="metric-row">
      <div class="metric-box">
        <div class="val green">{{ sla.compliant }}</div>
        <div class="lbl">Compliant</div>
      </div>
      <div class="metric-box">
        <div class="val {{ 'yellow' if sla.warnings > 0 else 'green' }}">{{ sla.warnings }}</div>
        <div class="lbl">Warnings</div>
      </div>
      <div class="metric-box">
        <div class="val {{ 'red' if sla.breaches > 0 else 'green' }}">{{ sla.breaches }}</div>
        <div class="lbl">Breaches</div>
      </div>
    </div>
    {% if tickets %}
    <table>
      <tr><th>Ticket</th><th>Priority</th><th>Status</th><th>Age (h)</th></tr>
      {% for t in tickets %}
      <tr>
        <td>{{ t.key }} — {{ t.summary[:40] }}</td>
        <td>{{ t.priority }}</td>
        <td><span class="badge {{ t.badge }}">{{ t.status }}</span></td>
        <td>{{ t.age_hours }}</td>
      </tr>
      {% endfor %}
    </table>
    {% endif %}
  </div>

  <div class="footer">
    AI Ops Automation Toolkit · Report generated at {{ generated_at }}
  </div>
</div>
</body>
</html>
"""


@dataclass
class HealthSnapshot:
    cpu_pct: int = 45
    memory_pct: int = 62
    disk_pct: int = 71
    uptime_pct: float = 99.95


@dataclass
class ModelSnapshot:
    accuracy: float = 0.913
    f1: float = 0.887
    drift_score: float = 0.042
    predictions_total: int = 14_832


@dataclass
class SLASnapshot:
    compliant: int = 18
    warnings: int = 2
    breaches: int = 1


def render_report(
    health: HealthSnapshot,
    model: ModelSnapshot,
    sla: SLASnapshot,
    tickets: list[dict] | None = None,
) -> str:
    env = Environment(loader=BaseLoader())
    template = env.from_string(REPORT_TEMPLATE)
    return template.render(
        report_date=datetime.now().strftime("%B %d, %Y"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        health=health,
        model=model,
        sla=sla,
        tickets=tickets or [],
    )


def send_report(html: str, config: dict[str, Any]) -> bool:
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Content
    except ImportError:
        logger.error("Install sendgrid: pip install sendgrid")
        return False

    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        logger.warning("SENDGRID_API_KEY not set — report not emailed.")
        return False

    subject = f"AI Ops Weekly Report — {datetime.now().strftime('%b %d, %Y')}"
    msg = Mail(
        from_email=os.environ.get("ALERT_EMAIL_FROM", "ops@example.com"),
        to_emails=os.environ.get("ALERT_EMAIL_TO", "team@example.com"),
        subject=subject,
        html_content=Content("text/html", html),
    )

    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    response = sg.send(msg)
    logger.info("Report emailed | status=%s", response.status_code)
    return response.status_code in (200, 202)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and email ops report")
    parser.add_argument("--demo",    action="store_true", help="Use demo data")
    parser.add_argument("--save",    default="output/report.html", help="Save HTML to file")
    parser.add_argument("--email",   action="store_true", help="Send via email")
    parser.add_argument("--config",  default="configs/config.yaml")
    args = parser.parse_args()

    config: dict[str, Any] = {}
    if Path(args.config).exists():
        with open(args.config) as f:
            config = yaml.safe_load(f)

    health = HealthSnapshot()
    model  = ModelSnapshot()
    sla    = SLASnapshot()
    tickets = [
        {"key": "OPS-001", "summary": "Production API latency spike", "priority": "Critical", "status": "Breached",  "age_hours": 6,  "badge": "badge-red"},
        {"key": "OPS-003", "summary": "Model serving OOM error",      "priority": "High",     "status": "Warning",   "age_hours": 20, "badge": "badge-yellow"},
    ]

    html = render_report(health, model, sla, tickets)

    out = Path(args.save)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    logger.info("Report saved to %s", out)

    if args.email:
        success = send_report(html, config)
        print("Email sent:", success)


if __name__ == "__main__":
    main()
