"""
Unit tests for tracker.py — SQLite prediction logging, bias, and Brier scoring.
Uses an in-memory database so tests don't touch production data.
"""

# Patch the DB path to an in-memory database before importing tracker
import sqlite3
import unittest
from datetime import date
from pathlib import Path

import tracker


def _in_memory_conn():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    return con


class TestTracker(unittest.TestCase):
    def setUp(self):
        """Redirect tracker DB to a temp file for each test."""
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_predictions.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _fake_analysis(self, our_prob=0.70, mkt_prob=0.50, edge=0.20):
        return {
            "condition": {"type": "above", "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": mkt_prob,
            "edge": edge,
            "method": "ensemble",
            "n_members": 82,
        }

    def test_log_and_retrieve(self):
        """Logged prediction should appear in get_history()."""
        tracker.log_prediction(
            "KXTEST-26APR09-T70",
            "NYC",
            date(2026, 4, 9),
            self._fake_analysis(),
        )
        history = tracker.get_history()
        self.assertEqual(len(history), 1)
        row = history[0]
        self.assertEqual(row["ticker"], "KXTEST-26APR09-T70")
        self.assertAlmostEqual(row["our_prob"], 0.70)

    def test_no_duplicate_same_day(self):
        """Logging the same ticker twice on the same day should update, not insert."""
        tracker.log_prediction(
            "TKDUP", "NYC", date(2026, 4, 9), self._fake_analysis(0.70)
        )
        tracker.log_prediction(
            "TKDUP", "NYC", date(2026, 4, 9), self._fake_analysis(0.75)
        )
        history = tracker.get_history()
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["our_prob"], 0.75)

    def test_brier_score(self):
        """Brier score should be computed correctly from outcomes."""
        ticker = "KXBRIER-TEST"
        tracker.log_prediction(
            ticker, "NYC", date(2026, 4, 1), self._fake_analysis(0.80)
        )
        tracker.log_outcome(ticker, settled_yes=True)
        bs = tracker.brier_score()
        # (0.80 - 1)^2 = 0.04
        self.assertIsNotNone(bs)
        assert bs is not None
        self.assertAlmostEqual(bs, 0.04, places=4)

    def test_brier_returns_none_when_empty(self):
        """brier_score() should return None with no settled outcomes."""
        self.assertIsNone(tracker.brier_score())

    def test_bias_insufficient_data(self):
        """get_bias() should return 0.0 with fewer samples than min_samples."""
        for i in range(5):
            t = f"TKTST-{i}"
            tracker.log_prediction(
                t, "NYC", date(2026, 4, i + 1), self._fake_analysis(0.70)
            )
            tracker.log_outcome(t, True)
        bias = tracker.get_bias("NYC", 4, min_samples=20)
        self.assertEqual(bias, 0.0)

    def test_log_outcome_replace(self):
        """Logging outcome twice replaces the first."""
        tracker.log_outcome("TK1", True)
        tracker.log_outcome("TK1", False)
        # No crash; most recent value should be False (0)
        tracker.get_history()
        # Outcome is stored independently; just verify it doesn't raise

    def test_sync_outcomes_records_finalized(self):
        """sync_outcomes should record YES outcome for a finalized market."""
        from unittest.mock import MagicMock

        tracker.log_prediction(
            "TKSYNC",
            "NYC",
            date(2026, 4, 9),
            self._fake_analysis(0.70),
        )

        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
        }

        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 1)

        history = tracker.get_history()
        self.assertEqual(history[0]["settled_yes"], 1)

    def test_sync_outcomes_skips_open_markets(self):
        """sync_outcomes should not record outcomes for markets still open."""
        from unittest.mock import MagicMock

        tracker.log_prediction(
            "TKOPEN",
            "NYC",
            date(2026, 4, 9),
            self._fake_analysis(0.70),
        )

        mock_client = MagicMock()
        mock_client.get_market.return_value = {"status": "open", "result": ""}

        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 0)

    def test_sync_outcomes_skips_already_settled(self):
        """sync_outcomes should not double-count already-settled markets."""
        from unittest.mock import MagicMock

        tracker.log_prediction(
            "TKALREADY",
            "NYC",
            date(2026, 4, 9),
            self._fake_analysis(0.70),
        )
        tracker.log_outcome("TKALREADY", True)  # already settled

        mock_client = MagicMock()
        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 0)
        mock_client.get_market.assert_not_called()

    def test_calibration_trend_empty(self):
        """get_calibration_trend returns empty list with no settled data."""
        trend = tracker.get_calibration_trend()
        self.assertEqual(trend, [])

    def test_calibration_by_city_empty(self):
        """get_calibration_by_city returns empty dict with no data."""
        result = tracker.get_calibration_by_city()
        self.assertEqual(result, {})

    def test_calibration_by_city_with_data(self):
        """get_calibration_by_city returns correct Brier + bias per city."""
        ticker = "TKCAL"
        tracker.log_prediction(
            ticker, "NYC", date(2026, 4, 9), self._fake_analysis(0.80)
        )
        tracker.log_outcome(ticker, True)  # settled YES, our_prob=0.80

        result = tracker.get_calibration_by_city()
        self.assertIn("NYC", result)
        # Brier = (0.80 - 1)^2 = 0.04
        self.assertAlmostEqual(result["NYC"]["brier"], 0.04, places=4)
        # Bias = 0.80 - 1 = -0.20 (we under-predicted)
        self.assertAlmostEqual(result["NYC"]["bias"], -0.20, places=4)
        self.assertEqual(result["NYC"]["n"], 1)

    def test_calibration_by_type_empty(self):
        """get_calibration_by_type returns empty dict with no data."""
        result = tracker.get_calibration_by_type()
        self.assertEqual(result, {})

    def test_calibration_by_type_with_data(self):
        """get_calibration_by_type returns correct Brier + bias per condition type."""
        # Log one 'above' prediction
        ticker_a = "TKTYPE-A"
        tracker.log_prediction(
            ticker_a, "NYC", date(2026, 4, 9), self._fake_analysis(0.80)
        )
        tracker.log_outcome(ticker_a, True)  # our_prob=0.80, settled YES

        # Log one 'below' prediction using a different analysis
        ticker_b = "TKTYPE-B"
        analysis_b = {
            "condition": {"type": "below", "threshold": 50.0},
            "forecast_prob": 0.60,
            "market_prob": 0.50,
            "edge": 0.10,
            "method": "ensemble",
            "n_members": 50,
        }
        tracker.log_prediction(ticker_b, "CHI", date(2026, 4, 9), analysis_b)
        tracker.log_outcome(ticker_b, False)  # our_prob=0.60, settled NO (0)

        result = tracker.get_calibration_by_type()
        self.assertIn("above", result)
        self.assertIn("below", result)
        # above: (0.80 - 1)^2 = 0.04
        self.assertAlmostEqual(result["above"]["brier"], 0.04, places=4)
        # below: (0.60 - 0)^2 = 0.36
        self.assertAlmostEqual(result["below"]["brier"], 0.36, places=4)
        self.assertEqual(result["above"]["n"], 1)
        self.assertEqual(result["below"]["n"], 1)

    def test_export_predictions_csv(self):
        import csv
        import tempfile

        ticker = "TKEXPORT-CSV"
        tracker.log_prediction(
            ticker, "NYC", date(2026, 4, 9), self._fake_analysis(0.75)
        )
        tracker.log_outcome(ticker, True)

        tmp = tempfile.mktemp(suffix=".csv")
        n = tracker.export_predictions_csv(tmp)
        self.assertEqual(n, 1)

        with open(tmp, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], ticker)
        self.assertAlmostEqual(float(rows[0]["our_prob"]), 0.75)

        import os

        os.unlink(tmp)

    def test_export_predictions_csv_empty(self):
        import tempfile

        tmp = tempfile.mktemp(suffix=".csv")
        n = tracker.export_predictions_csv(tmp)
        self.assertEqual(n, 0)


# ── #111: Focused pytest-style tests for brier_score and get_bias ─────────────


class TestBrierScore(unittest.TestCase):
    """Focused tests for tracker.brier_score() (#111)."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_brier.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _insert_prediction_and_outcome(self, ticker, our_prob, settled_yes):
        """Helper: log a prediction and its outcome."""
        analysis = {
            "condition": {"type": "above", "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": 0.50,
            "edge": our_prob - 0.50,
            "method": "ensemble",
            "n_members": 20,
        }
        tracker.log_prediction(ticker, "NYC", date(2026, 4, 1), analysis)
        tracker.log_outcome(ticker, settled_yes)

    def test_perfect_prediction_brier_zero(self):
        """forecast_prob=1.0, outcome=YES → Brier score = 0."""
        self._insert_prediction_and_outcome("TKPERF-YES", 1.0, True)
        bs = tracker.brier_score()
        self.assertIsNotNone(bs)
        assert bs is not None
        self.assertAlmostEqual(bs, 0.0, places=6)

    def test_worst_prediction_brier_one(self):
        """forecast_prob=0.0, outcome=YES → Brier score = 1."""
        self._insert_prediction_and_outcome("TKWORST-YES", 0.0, True)
        bs = tracker.brier_score()
        self.assertIsNotNone(bs)
        assert bs is not None
        self.assertAlmostEqual(bs, 1.0, places=6)

    def test_no_data_returns_none(self):
        """brier_score() returns None when there are no settled predictions."""
        result = tracker.brier_score()
        self.assertIsNone(result)

    def test_midpoint_prediction(self):
        """forecast_prob=0.5, outcome=NO → Brier = (0.5-0)^2 = 0.25."""
        self._insert_prediction_and_outcome("TKMID-NO", 0.5, False)
        bs = tracker.brier_score()
        self.assertIsNotNone(bs)
        assert bs is not None
        self.assertAlmostEqual(bs, 0.25, places=6)


class TestGetBias(unittest.TestCase):
    """Focused tests for tracker.get_bias() (#111)."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_bias.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_returns_zero_when_no_data(self):
        """get_bias() returns 0.0 (not None) when there is no data."""
        result = tracker.get_bias("NYC", 4)
        # With no data, fewer than min_samples=5 → returns 0.0
        self.assertEqual(result, 0.0)

    def test_returns_zero_below_min_samples(self):
        """get_bias() returns 0.0 with fewer samples than min_samples threshold."""
        analysis = {
            "condition": {"type": "above", "threshold": 70.0},
            "forecast_prob": 0.80,
            "market_prob": 0.50,
            "edge": 0.30,
            "method": "ensemble",
            "n_members": 20,
        }
        # Insert 3 predictions (below default min_samples=5)
        for i in range(3):
            ticker = f"TKBIAS-{i}"
            tracker.log_prediction(ticker, "NYC", date(2026, 4, i + 1), analysis)
            tracker.log_outcome(ticker, True)
        result = tracker.get_bias("NYC", 4, min_samples=5)
        self.assertEqual(result, 0.0)

    def test_returns_float_type(self):
        """get_bias() always returns a float (0.0 for insufficient data)."""
        result = tracker.get_bias("NYC", 4)
        self.assertIsInstance(result, float)

    def test_returns_float_or_zero_with_no_data_for_none_city(self):
        """get_bias(None, None) returns float."""
        result = tracker.get_bias(None, None)
        self.assertIsInstance(result, float)


if __name__ == "__main__":
    unittest.main(verbosity=2)
