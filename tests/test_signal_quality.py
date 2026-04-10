"""Tests for Group 2 signal quality improvements."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import tracker


class TestGetMemberAccuracyDaysBack:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tracker.DB_PATH = Path(self._tmp.name)
        tracker._initialized = False

    def teardown_method(self):
        import gc

        gc.collect()
        tracker._initialized = False
        self._tmp.close()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_get_member_accuracy_respects_days_back(self):
        """Old scores (90 days ago) are excluded; recent scores (10 days ago) are included."""
        tracker.init_db()
        now = datetime.now(UTC)
        old_ts = (now - timedelta(days=90)).isoformat()
        recent_ts = (now - timedelta(days=10)).isoformat()

        with tracker._conn() as con:
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("NYC", "model_a", 70.0, 80.0, "2025-01-01", old_ts),
            )
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("NYC", "model_a", 71.0, 72.0, "2025-01-02", recent_ts),
            )

        result = tracker.get_member_accuracy(days_back=60)
        assert "model_a" in result
        # Only the recent score (MAE=1.0) should be included, not the old one (MAE=10.0)
        assert result["model_a"]["mae"] == pytest.approx(1.0)
        assert result["model_a"]["n"] == 1


class TestEdgeConfidenceConditionType:
    def test_precip_snow_lower_than_temp(self):
        """Same horizon, snow produces lower confidence than temperature."""
        from weather_markets import edge_confidence

        snow = edge_confidence(5, condition_type="precip_snow")
        temp = edge_confidence(5, condition_type="above")
        assert snow < temp

    def test_condition_compounds_horizon(self):
        """days_out=10, precip_snow: horizon≈0.7143, × 0.80 ≈ 0.5714."""
        from weather_markets import edge_confidence

        result = edge_confidence(10, condition_type="precip_snow")
        # horizon = 0.80 - (10-7)/7.0 * 0.20 = 0.80 - 0.08571 ≈ 0.7143
        # × 0.80 ≈ 0.5714
        assert result == pytest.approx(0.5714, abs=0.001)

    def test_unknown_condition_defaults_to_one(self):
        """Unknown condition_type uses multiplier 1.0 — no change from no condition."""
        from weather_markets import edge_confidence

        without = edge_confidence(5)
        with_unknown = edge_confidence(5, condition_type="unknown_type")
        assert without == pytest.approx(with_unknown)
