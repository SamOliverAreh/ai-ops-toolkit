"""
scripts/python/jira_analyzer.py
Jira ticket SLA analysis with pandas — pulls data, computes metrics, exports report.

Usage:
  python jira_analyzer.py --demo
  python jira_analyzer.py --source jira --output output/jira_analysis.csv
"""
from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np
import yaml

from slack_notifier import get_notifier

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# SLA targets by priority (hours)
SLA_TARGETS = {"Critical": 4, "High": 24, "Medium": 72, "Low": 168}


def fetch_jira_issues() -> pd.DataFrame:
    """Fetch issues from Jira REST API into a DataFrame."""
    from jira import JIRA
    j = JIRA(
        server=os.environ["JIRA_SERVER"],
        basic_auth=(os.environ["JIRA_USER"], os.environ["JIRA_API_TOKEN"]),
    )
    project = os.environ.get("JIRA_PROJECT_KEY", "OPS")
    issues = j.search_issues(
        f'project={project} ORDER BY created DESC',
        maxResults=500,
    )
    rows = []
    for i in issues:
        rows.append({
            "key":         i.key,
            "summary":     str(i.fields.summary),
            "priority":    str(i.fields.priority),
            "status":      str(i.fields.status),
            "assignee":    str(getattr(i.fields.assignee, "displayName", "Unassigned")),
            "created_at":  i.fields.timecreated,
            "resolved_at": getattr(i.fields, "resolutiondate", None),
        })
    return pd.DataFrame(rows)


def generate_demo_data(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    now = datetime.now(timezone.utc)
    priorities = rng.choice(["Critical", "High", "Medium", "Low"], n, p=[0.05, 0.20, 0.50, 0.25])
    statuses   = rng.choice(["Open", "In Progress", "Resolved", "Closed"], n, p=[0.25, 0.30, 0.25, 0.20])
    created_offsets = rng.uniform(1, 200, n)  # hours ago

    rows = []
    for i in range(n):
        created = now - timedelta(hours=float(created_offsets[i]))
        resolved = None
        if statuses[i] in ("Resolved", "Closed"):
            resolution_hours = rng.uniform(0.5, created_offsets[i])
            resolved = created + timedelta(hours=float(resolution_hours))
        rows.append({
            "key":         f"OPS-{i+1:03d}",
            "summary":     f"Ticket {i+1}: {rng.choice(['API error', 'DB slow', 'Model drift', 'Alert noise', 'Deploy fail'])}",
            "priority":    priorities[i],
            "status":      statuses[i],
            "assignee":    rng.choice(["alice", "bob", "carol", "dave"]),
            "created_at":  created,
            "resolved_at": resolved,
        })
    return pd.DataFrame(rows)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add computed columns for SLA analysis."""
    now = datetime.now(timezone.utc)

    # Normalize datetimes
    for col in ("created_at", "resolved_at"):
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    df["sla_target_hours"] = df["priority"].map(SLA_TARGETS).fillna(72)

    # Elapsed hours: resolved_at if closed, else now
    def elapsed(row: pd.Series) -> float:
        end = row["resolved_at"] if pd.notna(row["resolved_at"]) else now
        return (end - row["created_at"]).total_seconds() / 3600

    df["elapsed_hours"] = df.apply(elapsed, axis=1).round(1)
    df["overage_hours"]  = (df["elapsed_hours"] - df["sla_target_hours"]).clip(lower=0).round(1)
    df["sla_status"] = df.apply(
        lambda r: (
            "closed" if r["status"] in ("Resolved", "Closed")
            else ("breached" if r["elapsed_hours"] > r["sla_target_hours"] else "on_track")
        ),
        axis=1,
    )
    return df


def compute_metrics(df: pd.DataFrame) -> dict[str, Any]:
    total   = len(df)
    open_df = df[~df["status"].isin(["Resolved", "Closed"])]

    return {
        "total_tickets":       total,
        "open_tickets":        len(open_df),
        "breached_open":       int((open_df["sla_status"] == "breached").sum()),
        "on_track_open":       int((open_df["sla_status"] == "on_track").sum()),
        "sla_compliance_pct":  round(
            100 * (1 - (open_df["sla_status"] == "breached").sum() / max(len(open_df), 1)), 1
        ),
        "avg_elapsed_hours":   round(float(df["elapsed_hours"].mean()), 1),
        "by_priority":         df.groupby("priority")["sla_status"].value_counts().to_dict(),
    }


def print_summary(metrics: dict[str, Any]) -> None:
    print("\n" + "="*50)
    print("  JIRA SLA ANALYSIS SUMMARY")
    print("="*50)
    print(f"  Total tickets:      {metrics['total_tickets']}")
    print(f"  Open tickets:       {metrics['open_tickets']}")
    print(f"  SLA compliance:     {metrics['sla_compliance_pct']}%")
    print(f"  Breached (open):    {metrics['breached_open']}")
    print(f"  On track (open):    {metrics['on_track_open']}")
    print(f"  Avg elapsed hours:  {metrics['avg_elapsed_hours']}h")
    print("="*50 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Jira SLA analysis")
    parser.add_argument("--source",  choices=["jira", "csv", "demo"], default="demo")
    parser.add_argument("--input",   help="CSV file (if --source csv)")
    parser.add_argument("--output",  default="output/jira_analysis.csv")
    parser.add_argument("--config",  default="configs/config.yaml")
    parser.add_argument("--notify",  action="store_true", help="Send Slack summary")
    args = parser.parse_args()

    if args.source == "jira":
        df = fetch_jira_issues()
    elif args.source == "csv":
        df = pd.read_csv(args.input)
    else:
        df = generate_demo_data()

    df = enrich(df)
    metrics = compute_metrics(df)
    print_summary(metrics)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    logger.info("Analysis saved: %s", out)

    if args.notify:
        notifier = get_notifier()
        m = metrics
        notifier.info(
            "📊 Jira SLA Weekly Summary",
            f"Tickets: {m['total_tickets']} total | {m['open_tickets']} open\n"
            f"SLA Compliance: *{m['sla_compliance_pct']}%*\n"
            f"Breached: {m['breached_open']} | On track: {m['on_track_open']}",
        )


if __name__ == "__main__":
    main()
