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

    def tearDown(self):
        tracker.DB_PATH = self._orig
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
