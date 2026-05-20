"""tests/python/test_model_monitor.py"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "python"))

from model_monitor import DriftDetector, PerformanceMonitor, ModelMonitor, MonitoringReport


# ── DriftDetector ─────────────────────────────────────────────────────────────

class TestDriftDetector:
    def setup_method(self):
        self.detector = DriftDetector(drift_threshold=0.15, alpha=0.05)
        self.rng = np.random.default_rng(42)

    def test_ks_no_drift(self):
        ref = self.rng.normal(0, 1, 500)
        cur = self.rng.normal(0, 1, 500)
        result = self.detector.ks_test(ref, cur, "test_feature")
        assert not result.is_drifted
        assert result.method == "KS"
        assert 0 <= result.statistic <= 1

    def test_ks_drift_detected(self):
        ref = self.rng.normal(0, 1, 500)
        cur = self.rng.normal(5, 1, 500)   # clear shift
        result = self.detector.ks_test(ref, cur, "shifted_feature")
        assert result.is_drifted
        assert result.p_value < 0.05

    def test_psi_no_drift(self):
        ref = self.rng.uniform(0, 1, 500)
        cur = self.rng.uniform(0, 1, 500)
        result = self.detector.psi(ref, cur, "stable_feature")
        assert not result.is_drifted

    def test_check_dataframe(self):
        n = 300
        ref_df = pd.DataFrame({
            "a": self.rng.normal(0, 1, n),
            "b": self.rng.normal(5, 2, n),
        })
        cur_df = pd.DataFrame({
            "a": self.rng.normal(3, 1, n),   # drifted
            "b": self.rng.normal(5, 2, n),   # stable
        })
        results = self.detector.check_dataframe(ref_df, cur_df)
        assert len(results) == 2
        drifted = [r for r in results if r.is_drifted]
        assert any(r.feature == "a" for r in drifted)

    def test_small_sample_skipped(self):
        ref_df = pd.DataFrame({"a": [1, 2, 3]})   # < 30 samples
        cur_df = pd.DataFrame({"a": [4, 5, 6]})
        results = self.detector.check_dataframe(ref_df, cur_df)
        assert results == []


# ── PerformanceMonitor ────────────────────────────────────────────────────────

class TestPerformanceMonitor:
    def setup_method(self):
        self.monitor = PerformanceMonitor(accuracy_threshold=0.80, f1_threshold=0.75)
        self.rng = np.random.default_rng(42)

    def test_good_performance(self):
        y_true = self.rng.integers(0, 2, 200)
        y_pred = y_true.copy()   # 100% accuracy
        results = self.monitor.evaluate(y_true, y_pred)
        assert all(not r.is_degraded for r in results)

    def test_degraded_performance(self):
        y_true = self.rng.integers(0, 2, 200)
        y_pred = self.rng.integers(0, 2, 200)   # random ≈ 50% acc
        results = self.monitor.evaluate(y_true, y_pred)
        degraded = [r for r in results if r.is_degraded]
        assert len(degraded) > 0

    def test_result_fields(self):
        y_true = np.array([0, 1, 0, 1, 1])
        y_pred = np.array([0, 1, 0, 0, 1])
        results = self.monitor.evaluate(y_true, y_pred)
        metrics = {r.metric for r in results}
        assert "accuracy" in metrics
        assert "f1_score" in metrics


# ── ModelMonitor orchestrator ─────────────────────────────────────────────────

class TestModelMonitor:
    def setup_method(self):
        self.config = {
            "model_monitoring": {
                "drift_threshold": 0.15,
                "performance_threshold": 0.80,
            }
        }

    def test_run_with_no_drift(self, mocker):
        mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)
        monitor = ModelMonitor(self.config)
        rng = np.random.default_rng(42)
        n = 500
        ref = pd.DataFrame({"x": rng.normal(0, 1, n)})
        cur = pd.DataFrame({"x": rng.normal(0, 1, n)})
        y_true = rng.integers(0, 2, 100)
        y_pred = y_true.copy()

        report = monitor.run(ref, cur, y_true, y_pred)
        assert isinstance(report, MonitoringReport)
        assert report.overall_status == "healthy"

    def test_run_with_drift(self, mocker):
        mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)
        monitor = ModelMonitor(self.config)
        rng = np.random.default_rng(42)
        n = 500
        ref = pd.DataFrame({"x": rng.normal(0, 1, n)})
        cur = pd.DataFrame({"x": rng.normal(5, 1, n)})   # large drift

        report = monitor.run(ref, cur)
        assert report.overall_status in ("degraded", "critical")

    def test_report_serialization(self, mocker):
        mocker.patch("slack_notifier.SlackNotifier.send", return_value=True)
        monitor = ModelMonitor(self.config)
        report = monitor.run()
        json_str = report.to_json()
        import json
        data = json.loads(json_str)
        assert "timestamp" in data
        assert "overall_status" in data
