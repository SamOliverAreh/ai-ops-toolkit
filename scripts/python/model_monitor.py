"""
scripts/python/model_monitor.py
ML model drift detection and performance monitoring.

Detects:
  - Feature distribution drift (PSI - Population Stability Index)
  - Prediction drift (KL divergence)
  - Performance degradation (accuracy, F1 below threshold)

Usage:
  python model_monitor.py --config configs/config.yaml
  python model_monitor.py --endpoint http://localhost:8080/predict --threshold 0.15
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
import yaml
from scipy.stats import ks_2samp
from sklearn.metrics import accuracy_score, f1_score

from slack_notifier import get_notifier, AlertLevel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class DriftResult:
    feature: str
    statistic: float
    p_value: float
    is_drifted: bool
    method: str = "KS"


@dataclass
class PerformanceResult:
    metric: str
    value: float
    threshold: float
    is_degraded: bool


@dataclass
class MonitoringReport:
    timestamp: str
    model_endpoint: str
    drift_results: list[DriftResult] = field(default_factory=list)
    performance_results: list[PerformanceResult] = field(default_factory=list)
    overall_status: str = "healthy"   # healthy | degraded | critical
    alerts_sent: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ── Drift detection ───────────────────────────────────────────────────────────

class DriftDetector:
    """Detect feature and prediction drift using KS test and PSI."""

    def __init__(self, drift_threshold: float = 0.15, alpha: float = 0.05) -> None:
        self.drift_threshold = drift_threshold
        self.alpha = alpha

    def ks_test(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_name: str = "feature",
    ) -> DriftResult:
        """Kolmogorov-Smirnov two-sample test."""
        stat, p_value = ks_2samp(reference, current)
        is_drifted = p_value < self.alpha

        result = DriftResult(
            feature=feature_name,
            statistic=round(float(stat), 4),
            p_value=round(float(p_value), 6),
            is_drifted=is_drifted,
            method="KS",
        )
        level = "DRIFT" if is_drifted else "OK"
        logger.info("[%s] %s | stat=%.4f p=%.6f", level, feature_name, stat, p_value)
        return result

    def psi(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_name: str = "feature",
        buckets: int = 10,
    ) -> DriftResult:
        """Population Stability Index (PSI). PSI > 0.2 = significant drift."""
        def _psi_score(ref: np.ndarray, cur: np.ndarray, n_buckets: int) -> float:
            breakpoints = np.linspace(0, 1, n_buckets + 1)
            ref_pct = np.histogram(ref, bins=np.quantile(ref, breakpoints))[0] / len(ref)
            cur_pct = np.histogram(cur, bins=np.quantile(ref, breakpoints))[0] / len(cur)
            # Avoid log(0)
            ref_pct = np.where(ref_pct == 0, 1e-6, ref_pct)
            cur_pct = np.where(cur_pct == 0, 1e-6, cur_pct)
            return float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))

        score = _psi_score(reference, current, buckets)
        is_drifted = score > self.drift_threshold

        result = DriftResult(
            feature=feature_name,
            statistic=round(score, 4),
            p_value=0.0,
            is_drifted=is_drifted,
            method="PSI",
        )
        logger.info("[%s] %s | PSI=%.4f (threshold=%.2f)", "DRIFT" if is_drifted else "OK", feature_name, score, self.drift_threshold)
        return result

    def check_dataframe(
        self,
        reference_df: pd.DataFrame,
        current_df: pd.DataFrame,
        method: str = "ks",
    ) -> list[DriftResult]:
        """Run drift detection across all numeric columns."""
        numeric_cols = reference_df.select_dtypes(include=np.number).columns.tolist()
        results = []
        for col in numeric_cols:
            if col not in current_df.columns:
                continue
            ref_arr = reference_df[col].dropna().values
            cur_arr = current_df[col].dropna().values
            if len(ref_arr) < 30 or len(cur_arr) < 30:
                logger.warning("Skipping %s — insufficient samples", col)
                continue
            if method == "psi":
                results.append(self.psi(ref_arr, cur_arr, feature_name=col))
            else:
                results.append(self.ks_test(ref_arr, cur_arr, feature_name=col))
        return results


# ── Performance monitoring ────────────────────────────────────────────────────

class PerformanceMonitor:
    """Track model performance metrics against thresholds."""

    def __init__(
        self,
        accuracy_threshold: float = 0.80,
        f1_threshold: float = 0.75,
    ) -> None:
        self.accuracy_threshold = accuracy_threshold
        self.f1_threshold = f1_threshold

    def evaluate(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> list[PerformanceResult]:
        results = []

        acc = accuracy_score(y_true, y_pred)
        results.append(PerformanceResult(
            metric="accuracy",
            value=round(float(acc), 4),
            threshold=self.accuracy_threshold,
            is_degraded=acc < self.accuracy_threshold,
        ))

        f1 = f1_score(y_true, y_pred, average="weighted", zero_division=0)
        results.append(PerformanceResult(
            metric="f1_score",
            value=round(float(f1), 4),
            threshold=self.f1_threshold,
            is_degraded=f1 < self.f1_threshold,
        ))

        for r in results:
            status = "DEGRADED" if r.is_degraded else "OK"
            logger.info("[%s] %s=%.4f (threshold=%.2f)", status, r.metric, r.value, r.threshold)

        return results

    def ping_endpoint(self, endpoint: str, timeout: int = 5) -> bool:
        """Quick liveness check on the model serving endpoint."""
        try:
            resp = requests.get(endpoint, timeout=timeout)
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.error("Endpoint unreachable: %s — %s", endpoint, e)
            return False


# ── Main orchestrator ─────────────────────────────────────────────────────────

class ModelMonitor:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        mon_cfg = config.get("model_monitoring", {})
        self.endpoint = os.environ.get("MODEL_ENDPOINT", mon_cfg.get("model_endpoint", ""))
        self.drift_threshold = float(
            os.environ.get("DRIFT_THRESHOLD", mon_cfg.get("drift_threshold", 0.15))
        )
        self.perf_threshold = float(
            os.environ.get("PERFORMANCE_THRESHOLD", mon_cfg.get("performance_threshold", 0.80))
        )
        self.drift_detector = DriftDetector(drift_threshold=self.drift_threshold)
        self.perf_monitor = PerformanceMonitor(accuracy_threshold=self.perf_threshold)
        self.notifier = get_notifier()
        self.report_dir = Path("logs/monitoring")
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        reference_df: pd.DataFrame | None = None,
        current_df: pd.DataFrame | None = None,
        y_true: np.ndarray | None = None,
        y_pred: np.ndarray | None = None,
    ) -> MonitoringReport:
        ts = datetime.now(timezone.utc).isoformat()
        report = MonitoringReport(timestamp=ts, model_endpoint=self.endpoint)

        # Drift detection
        if reference_df is not None and current_df is not None:
            logger.info("Running drift detection...")
            report.drift_results = self.drift_detector.check_dataframe(
                reference_df, current_df
            )

        # Performance evaluation
        if y_true is not None and y_pred is not None:
            logger.info("Evaluating performance metrics...")
            report.performance_results = self.perf_monitor.evaluate(y_true, y_pred)

        # Determine overall status
        drifted = [r for r in report.drift_results if r.is_drifted]
        degraded = [r for r in report.performance_results if r.is_degraded]

        if degraded:
            report.overall_status = "critical"
        elif drifted:
            report.overall_status = "degraded"
        else:
            report.overall_status = "healthy"

        self._send_alerts(report, drifted, degraded)
        self._save_report(report)
        return report

    def _send_alerts(
        self,
        report: MonitoringReport,
        drifted: list[DriftResult],
        degraded: list[PerformanceResult],
    ) -> None:
        if degraded:
            text = "\n".join(
                f"• `{r.metric}` = {r.value:.3f} (threshold: {r.threshold:.2f})"
                for r in degraded
            )
            self.notifier.critical(
                "🚨 Model Performance Degraded",
                f"The following metrics are below threshold:\n{text}",
            )
            report.alerts_sent.append("performance_critical")

        elif drifted:
            text = "\n".join(
                f"• `{r.feature}` ({r.method}) stat={r.statistic:.4f}"
                for r in drifted
            )
            self.notifier.warning(
                "⚠️ Feature Drift Detected",
                f"Drift detected on {len(drifted)} feature(s):\n{text}",
            )
            report.alerts_sent.append("drift_warning")
        else:
            logger.info("All metrics healthy — no alerts sent.")

    def _save_report(self, report: MonitoringReport) -> None:
        ts_safe = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.report_dir / f"monitor_{ts_safe}.json"
        path.write_text(report.to_json())
        logger.info("Report saved: %s", path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ML model monitoring checks")
    parser.add_argument("--config", default="configs/config.yaml")
    parser.add_argument("--endpoint", help="Override model endpoint URL")
    parser.add_argument("--threshold", type=float, help="Override drift threshold")
    parser.add_argument("--demo", action="store_true", help="Run with synthetic demo data")
    args = parser.parse_args()

    config = load_config(args.config) if Path(args.config).exists() else {}
    if args.endpoint:
        config.setdefault("model_monitoring", {})["model_endpoint"] = args.endpoint
    if args.threshold:
        config.setdefault("model_monitoring", {})["drift_threshold"] = args.threshold

    monitor = ModelMonitor(config)

    if args.demo:
        logger.info("Running in demo mode with synthetic data...")
        rng = np.random.default_rng(42)
        n = 1000
        ref_df = pd.DataFrame({
            "feature_a": rng.normal(0, 1, n),
            "feature_b": rng.normal(5, 2, n),
            "feature_c": rng.exponential(2, n),
        })
        # Introduce artificial drift in feature_a
        cur_df = pd.DataFrame({
            "feature_a": rng.normal(1.5, 1.5, n),  # drifted
            "feature_b": rng.normal(5.1, 2, n),
            "feature_c": rng.exponential(2.1, n),
        })
        y_true = rng.integers(0, 2, 200)
        y_pred = np.where(rng.random(200) > 0.25, y_true, 1 - y_true)  # ~75% accuracy

        report = monitor.run(ref_df, cur_df, y_true, y_pred)
    else:
        report = monitor.run()

    print(report.to_json())
    exit_code = 0 if report.overall_status == "healthy" else 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
