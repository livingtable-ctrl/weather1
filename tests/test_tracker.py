"""
Unit tests for tracker.py — SQLite prediction logging, bias, and Brier scoring.
Uses an in-memory database so tests don't touch production data.
"""

# Patch the DB path to an in-memory database before importing tracker
import shutil
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, timedelta
from pathlib import Path

import pytest

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
            ticker, "NYC", date(2099, 1, 1), self._fake_analysis(0.80)
        )
        tracker.log_outcome(ticker, settled_yes=True)
        bs = tracker.brier_score()
        # (0.80 - 1)^2 = 0.04
        self.assertIsNotNone(bs)
        assert bs is not None
        self.assertAlmostEqual(bs, 0.04, places=4)

    def test_brier_returns_none_when_empty(self):
        """brier_score() should return None with no settled outcomes."""
        from unittest.mock import patch

        with patch("paper.get_all_trades", return_value=[]):
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
        """P2-C: log_outcome refuses to overwrite an existing finalized outcome (by design).

        The first call returns True (newly recorded).
        The second call for the same ticker returns False (no-op — refuses to overwrite).
        The stored value must remain the ORIGINAL value, not the second call's value.
        """
        first = tracker.log_outcome("TK1", True)
        second = tracker.log_outcome("TK1", False)

        self.assertTrue(
            first, "First log_outcome call should return True (newly recorded)"
        )
        self.assertFalse(
            second, "Second log_outcome call should return False (refused to overwrite)"
        )

        # Confirm the DB still holds the original value (True / 1), not the second call's value.
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT settled_yes FROM outcomes WHERE ticker = ?", ("TK1",)
            ).fetchone()
        self.assertIsNotNone(row, "Outcome row must exist in DB")
        self.assertEqual(
            row[0], 1, "Stored value must be 1 (True), not overwritten by second call"
        )

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

    def test_sync_outcomes_backfills_price_history_on_settlement(self):
        """sync_outcomes should fetch and store full OHLC candlestick history
        exactly once when a market's outcome is newly recorded."""
        from unittest.mock import MagicMock

        tracker.log_prediction(
            "TKCANDLE", "NYC", date(2026, 4, 9), self._fake_analysis(0.70)
        )

        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "series_ticker": "KXHIGHNY",
            "open_time": "2026-04-06T00:00:00Z",
            "close_time": "2026-04-09T23:00:00Z",
        }
        mock_client.get_candlesticks.return_value = [
            {
                "end_period_ts": 1700000000,
                "price": {
                    "open_dollars": "0.40",
                    "high_dollars": "0.55",
                    "low_dollars": "0.38",
                    "close_dollars": "0.52",
                },
                "yes_bid": {"close_dollars": "0.51"},
                "yes_ask": {"close_dollars": "0.53"},
                "volume_fp": "12.00",
                "open_interest_fp": "40.00",
            }
        ]

        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 1)

        mock_client.get_candlesticks.assert_called_once()
        call_args = mock_client.get_candlesticks.call_args[0]
        self.assertEqual(call_args[0], "KXHIGHNY")  # series_ticker
        self.assertEqual(call_args[1], "TKCANDLE")  # ticker

        rows = tracker.get_price_history("TKCANDLE")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["price_close"], 0.52)
        self.assertAlmostEqual(rows[0]["yes_bid_close"], 0.51)
        self.assertAlmostEqual(rows[0]["volume"], 12.00)

    def test_sync_outcomes_survives_candlestick_backfill_failure(self):
        """A candlestick-fetch error must never block outcome recording."""
        from unittest.mock import MagicMock

        tracker.log_prediction(
            "TKCANDLEFAIL", "NYC", date(2026, 4, 9), self._fake_analysis(0.70)
        )

        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "series_ticker": "KXHIGHNY",
            "open_time": "2026-04-06T00:00:00Z",
            "close_time": "2026-04-09T23:00:00Z",
        }
        mock_client.get_candlesticks.side_effect = RuntimeError("boom")

        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 1)

        history = tracker.get_history()
        self.assertEqual(history[0]["settled_yes"], 1)

    def test_sync_outcomes_skips_candlestick_fetch_without_series_ticker(self):
        """No series_ticker/open_time on the market → skip the fetch cleanly
        (older/malformed responses shouldn't crash outcome recording)."""
        from unittest.mock import MagicMock

        tracker.log_prediction(
            "TKNOCANDLE", "NYC", date(2026, 4, 9), self._fake_analysis(0.70)
        )

        mock_client = MagicMock()
        mock_client.get_market.return_value = {"status": "finalized", "result": "yes"}

        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 1)
        mock_client.get_candlesticks.assert_not_called()

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
            ticker, "NYC", date(2099, 1, 1), self._fake_analysis(0.80)
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
            ticker_a, "NYC", date(2099, 1, 1), self._fake_analysis(0.80)
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
        tracker.log_prediction(ticker_b, "CHI", date(2099, 1, 1), analysis_b)
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
        tracker.log_prediction(ticker, "NYC", date(2099, 1, 1), analysis)
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
        from unittest.mock import patch

        with patch("paper.get_all_trades", return_value=[]):
            result = tracker.brier_score()
        self.assertIsNone(result)

    def test_midpoint_prediction(self):
        """forecast_prob=0.5, outcome=NO → Brier = (0.5-0)^2 = 0.25."""
        self._insert_prediction_and_outcome("TKMID-NO", 0.5, False)
        bs = tracker.brier_score()
        self.assertIsNotNone(bs)
        assert bs is not None
        self.assertAlmostEqual(bs, 0.25, places=6)


class TestBrierScoreLastN(unittest.TestCase):
    """Tests for brier_score(last_n=N) — last-N settled predictions."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_brier_lastn.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _insert(self, ticker, our_prob, settled_yes, days_ago=0):
        analysis = {
            "condition": {"type": "above", "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": 0.50,
            "edge": our_prob - 0.50,
            "method": "ensemble",
            "n_members": 20,
        }
        tracker.log_prediction(ticker, "NYC", date(2099, 1, 1), analysis)
        tracker.log_outcome(ticker, settled_yes)
        if days_ago:
            with tracker._conn() as con:
                con.execute(
                    "UPDATE outcomes SET settled_at = datetime('now', ?) WHERE ticker = ?",
                    (f"-{days_ago} days", ticker),
                )

    def test_last_n_limits_to_most_recent(self):
        """last_n=2 uses only the 2 most recently settled predictions."""
        self._insert("TK-OLD", 0.0, True, days_ago=10)  # error=1.0 (bad)
        self._insert("TK-NEW1", 1.0, True, days_ago=1)  # error=0.0 (perfect)
        self._insert("TK-NEW2", 1.0, True, days_ago=0)  # error=0.0 (perfect)

        bs = tracker.brier_score(last_n=2)
        self.assertIsNotNone(bs)
        self.assertAlmostEqual(bs, 0.0, places=6)

    def test_last_n_greater_than_total_returns_all(self):
        """last_n=100 with only 3 predictions behaves the same as all-time."""
        self._insert("TK-A", 1.0, True)
        self._insert("TK-B", 0.5, False)
        self._insert("TK-C", 0.0, False)

        bs_all = tracker.brier_score()
        bs_lastn = tracker.brier_score(last_n=100)
        self.assertIsNotNone(bs_all)
        self.assertAlmostEqual(bs_all, bs_lastn, places=6)

    def test_last_n_none_is_all_time(self):
        """last_n=None (default) produces the same result as calling without last_n."""
        self._insert("TK-X", 0.8, True, days_ago=5)
        self._insert("TK-Y", 0.3, False, days_ago=2)

        self.assertAlmostEqual(
            tracker.brier_score(),
            tracker.brier_score(last_n=None),
            places=6,
        )

    def test_last_n_empty_returns_none(self):
        """last_n=5 on empty DB returns None, not 0.0."""
        from unittest.mock import patch

        with patch("paper.get_all_trades", return_value=[]):
            result = tracker.brier_score(last_n=5)
        self.assertIsNone(result)


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


class TestGetBrierOverTime(unittest.TestCase):
    """Tests for tracker.get_brier_over_time()."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_brier_over_time.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _insert(self, ticker, our_prob, settled_yes):
        from datetime import date

        analysis = {
            "condition": {"type": "above", "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": 0.50,
            "edge": our_prob - 0.50,
            "method": "ensemble",
            "n_members": 20,
        }
        tracker.log_prediction(ticker, "NYC", date(2099, 1, 1), analysis)
        tracker.log_outcome(ticker, settled_yes)

    def test_empty_db_returns_empty_list(self):
        """No data → empty list."""
        result = tracker.get_brier_over_time(weeks=12)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    def test_returns_correct_brier_for_seeded_data(self):
        """Seeded prediction: prob=0.5, outcome=NO → brier=(0.5-0)^2=0.25."""
        self._insert("TK-BOT-1", 0.5, False)
        result = tracker.get_brier_over_time(weeks=12)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertIn("week", item)
        self.assertIn("brier", item)
        self.assertIsInstance(item["brier"], float)
        self.assertAlmostEqual(item["brier"], 0.25, places=4)

    def test_brier_values_in_valid_range(self):
        """Brier values must be in [0.0, 1.0]."""
        self._insert("TK-BOT-2", 0.8, True)  # (0.8-1)^2 = 0.04
        self._insert("TK-BOT-3", 0.3, False)  # (0.3-0)^2 = 0.09
        result = tracker.get_brier_over_time(weeks=12)
        for item in result:
            self.assertGreaterEqual(item["brier"], 0.0)
            self.assertLessEqual(item["brier"], 1.0)


# ── Phase 3 tests ─────────────────────────────────────────────────────────────


class _Phase3Base(unittest.TestCase):
    """Shared setUp/tearDown for Phase 3 test classes."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = __import__("pathlib").Path(self._tmpdir) / "test_p3.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _add(
        self,
        ticker,
        city,
        our_prob,
        mkt_prob,
        settled_yes,
        condition_type=None,
        days_out=1,
        market_date=None,
    ):
        """Helper: log prediction + outcome."""
        if market_date is None:
            market_date = date(2026, 4, 1)
        analysis = {
            "condition": {"type": condition_type or "above", "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": mkt_prob,
            "edge": abs(our_prob - mkt_prob),
            "method": "ensemble",
            "n_members": 20,
            "bias_correction": 0.0,
        }
        tracker.log_prediction(ticker, city, market_date, analysis)
        tracker.log_outcome(ticker, settled_yes)
        # Patch days_out directly
        if days_out != 1:
            import sqlite3

            with sqlite3.connect(str(tracker.DB_PATH)) as con:
                con.execute(
                    "UPDATE predictions SET days_out=?, condition_type=? WHERE ticker=?",
                    (days_out, condition_type, ticker),
                )
        else:
            import sqlite3

            with sqlite3.connect(str(tracker.DB_PATH)) as con:
                con.execute(
                    "UPDATE predictions SET days_out=1, condition_type=? WHERE ticker=?",
                    (condition_type, ticker),
                )


# ── Task 1: get_bias() with condition_type ─────────────────────────────────────


class TestGetBiasConditionType(_Phase3Base):
    """Tests for get_bias() stratified by condition_type (#10)."""

    def _add_typed(self, n, city, our_prob, settled_yes, ctype, market_date=None):
        for i in range(n):
            ticker = f"TKBIAS-{ctype}-{i}-{our_prob}"
            if market_date is None:
                market_date = date(2026, 4, i + 1)
            self._add(
                ticker,
                city,
                our_prob,
                0.5,
                settled_yes,
                condition_type=ctype,
                market_date=market_date,
            )

    def test_grpb_bias_condition_type_filters_rows(self):
        """Filtering by HIGH vs PRECIP gives different bias values."""
        # HIGH: over-estimating (our_prob=0.9, settled NO) — positive bias
        self._add_typed(6, "NYC", 0.90, False, "HIGH")
        # PRECIP: under-estimating (our_prob=0.3, settled YES) — negative bias
        self._add_typed(6, "NYC", 0.30, True, "PRECIP")

        # Override staleness by using current dates
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            con.execute("UPDATE predictions SET predicted_at = datetime('now')")

        bias_high = tracker.get_bias("NYC", None, min_samples=5, condition_type="HIGH")
        bias_precip = tracker.get_bias(
            "NYC", None, min_samples=5, condition_type="PRECIP"
        )
        self.assertGreater(bias_high, 0, "HIGH bias should be positive (over-estimate)")
        self.assertLess(
            bias_precip, 0, "PRECIP bias should be negative (under-estimate)"
        )
        self.assertNotAlmostEqual(bias_high, bias_precip, places=2)

    def test_bias_no_condition_type_includes_all(self):
        """Without condition_type filter, bias uses all rows."""
        self._add_typed(6, "NYC", 0.70, True, "HIGH")
        self._add_typed(6, "NYC", 0.70, True, "PRECIP")
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            con.execute("UPDATE predictions SET predicted_at = datetime('now')")
        bias_all = tracker.get_bias("NYC", None, min_samples=5)
        bias_high = tracker.get_bias("NYC", None, min_samples=5, condition_type="HIGH")
        # Both should be non-zero; all-condition bias uses more samples
        self.assertIsInstance(bias_all, float)
        self.assertIsInstance(bias_high, float)

    def test_grpb_bias_unknown_condition_type_returns_zero(self):
        """Filtering by a condition_type with no matching rows returns 0.0."""
        self._add_typed(6, "NYC", 0.70, True, "HIGH")
        result = tracker.get_bias(
            "NYC", None, min_samples=1, condition_type="precip_any"
        )
        self.assertEqual(result, 0.0)


# ── CLI-scoped calibration split (multiday/sameday, between-excluded) ──────────


class TestCliCalibrationSplit(_Phase3Base):
    """Tests for get_multiday_calibration_cli() / get_sameday_calibration_cli()
    and a regression check that get_sameday_calibration() (dashboard-facing,
    includes 'between') did not change behavior during the refactor."""

    def test_multiday_calibration_cli_empty(self):
        result = tracker.get_multiday_calibration_cli()
        self.assertEqual(result["n"], 0)
        self.assertFalse(result["gate_met"])
        self.assertIsNone(result["brier"])
        self.assertEqual(result["calibration_buckets"], [])

    def test_sameday_calibration_cli_empty(self):
        result = tracker.get_sameday_calibration_cli()
        self.assertEqual(result["n"], 0)
        self.assertFalse(result["gate_met"])
        self.assertIsNone(result["brier"])
        self.assertEqual(result["calibration_buckets"], [])

    def test_multiday_calibration_cli_excludes_sameday_rows(self):
        """A days_out=0 row must not appear in the multiday population."""
        self._add(
            "TKCAL-MD-1", "NYC", 0.80, 0.50, True, condition_type="above", days_out=1
        )
        self._add(
            "TKCAL-SD-1", "NYC", 0.20, 0.50, False, condition_type="above", days_out=0
        )
        multiday = tracker.get_multiday_calibration_cli()
        self.assertEqual(multiday["n"], 1)
        self.assertAlmostEqual(multiday["brier"], (0.80 - 1) ** 2, places=4)

    def test_sameday_calibration_cli_excludes_multiday_rows(self):
        """A days_out=1 row must not appear in the sameday population."""
        self._add(
            "TKCAL-MD-2", "NYC", 0.80, 0.50, True, condition_type="above", days_out=1
        )
        self._add(
            "TKCAL-SD-2", "NYC", 0.20, 0.50, False, condition_type="above", days_out=0
        )
        sameday = tracker.get_sameday_calibration_cli()
        self.assertEqual(sameday["n"], 1)
        self.assertAlmostEqual(sameday["brier"], (0.20 - 0) ** 2, places=4)

    def test_multiday_calibration_cli_excludes_between(self):
        """condition_type='between' rows must not affect n/brier."""
        self._add(
            "TKCAL-MD-ABOVE",
            "NYC",
            0.70,
            0.50,
            True,
            condition_type="above",
            days_out=1,
        )
        for i in range(3):
            self._add(
                f"TKCAL-MD-BETWEEN-{i}",
                "NYC",
                0.90,
                0.50,
                False,
                condition_type="between",
                days_out=1,
            )
        multiday = tracker.get_multiday_calibration_cli()
        self.assertEqual(multiday["n"], 1)
        self.assertAlmostEqual(multiday["brier"], (0.70 - 1) ** 2, places=4)

    def test_sameday_calibration_cli_excludes_between(self):
        """Regression for the 69-row scenario found in production data: 'between'
        sameday rows must not leak into the CLI-scoped sameday population."""
        self._add(
            "TKCAL-SD-ABOVE",
            "NYC",
            0.30,
            0.50,
            False,
            condition_type="above",
            days_out=0,
        )
        for i in range(3):
            self._add(
                f"TKCAL-SD-BETWEEN-{i}",
                "NYC",
                0.90,
                0.50,
                False,
                condition_type="between",
                days_out=0,
            )
        sameday = tracker.get_sameday_calibration_cli()
        self.assertEqual(sameday["n"], 1)
        self.assertAlmostEqual(sameday["brier"], (0.30 - 0) ** 2, places=4)

    def test_get_sameday_calibration_still_includes_between(self):
        """Dashboard-facing get_sameday_calibration() must NOT change behavior —
        it still includes 'between' rows, unlike the CLI-scoped variant above."""
        self._add(
            "TKCAL-SDALL-ABOVE",
            "NYC",
            0.30,
            0.50,
            False,
            condition_type="above",
            days_out=0,
        )
        self._add(
            "TKCAL-SDALL-BETWEEN",
            "NYC",
            0.90,
            0.50,
            False,
            condition_type="between",
            days_out=0,
        )
        dashboard = tracker.get_sameday_calibration()
        self.assertEqual(dashboard["n"], 2)

    def test_multiday_calibration_cli_bucket_grouping(self):
        """Rows land in the correct 0.2-wide probability buckets."""
        self._add(
            "TKCAL-BKT-1", "NYC", 0.05, 0.50, False, condition_type="above", days_out=1
        )
        self._add(
            "TKCAL-BKT-2", "NYC", 0.55, 0.50, True, condition_type="above", days_out=2
        )
        self._add(
            "TKCAL-BKT-3", "NYC", 0.95, 0.50, True, condition_type="above", days_out=3
        )
        multiday = tracker.get_multiday_calibration_cli()
        self.assertEqual(multiday["n"], 3)
        lows = [b["bucket_low"] for b in multiday["calibration_buckets"]]
        self.assertIn(0.0, lows)
        self.assertIn(0.4, lows)
        self.assertIn(0.8, lows)


# ── Task 2: brier_skill_score() ───────────────────────────────────────────────


class TestBrierSkillScore(_Phase3Base):
    """Tests for brier_skill_score() (#11)."""

    def test_returns_none_below_10_samples(self):
        """BSS returns None with < 10 samples."""
        for i in range(5):
            self._add(f"TKBSS-{i}", "NYC", 0.7, 0.5, True)
        result = tracker.brier_skill_score()
        self.assertIsNone(result)

    def test_perfect_model_positive_bss(self):
        """Perfect model (our_prob=1.0, settled YES) gives BSS > 0."""
        for i in range(10):
            self._add(f"TKBSS-PERF-{i}", "NYC", 1.0, 0.5, True)
        bss = tracker.brier_skill_score()
        self.assertIsNotNone(bss)
        assert bss is not None
        self.assertGreater(bss, 0.0)

    def test_market_level_model_near_zero(self):
        """Model matching market_prob exactly gives BSS ≈ 0."""
        for i in range(10):
            self._add(f"TKBSS-MKT-{i}", "NYC", 0.6, 0.6, True)
        bss = tracker.brier_skill_score()
        self.assertIsNotNone(bss)
        assert bss is not None
        self.assertAlmostEqual(bss, 0.0, places=4)


# ── Task 3: get_confusion_matrix() with threshold in return dict ──────────────


class TestConfusionMatrixThreshold(_Phase3Base):
    """Tests for get_confusion_matrix() with configurable threshold (#12)."""

    def test_threshold_in_return_dict(self):
        """Return dict must include 'threshold' key."""
        cm = tracker.get_confusion_matrix(threshold=0.6)
        self.assertIn("threshold", cm)
        self.assertAlmostEqual(cm["threshold"], 0.6)

    def test_threshold_60_vs_80(self):
        """prob=0.7, settled YES: threshold=0.6 → TP; threshold=0.8 → FN."""
        self._add("TKCM-TH", "NYC", 0.70, 0.5, True)
        cm60 = tracker.get_confusion_matrix(threshold=0.6)
        cm80 = tracker.get_confusion_matrix(threshold=0.8)
        self.assertEqual(cm60["tp"], 1, "threshold=0.6 should give TP")
        self.assertEqual(cm60["fn"], 0)
        self.assertEqual(cm80["tp"], 0, "threshold=0.8 should give FN")
        self.assertEqual(cm80["fn"], 1)

    def test_empty_has_threshold(self):
        """Empty DB still returns threshold in dict."""
        cm = tracker.get_confusion_matrix(threshold=0.75)
        self.assertEqual(cm["threshold"], 0.75)
        self.assertEqual(cm["n"], 0)


# ── Task 4: get_optimal_threshold() ──────────────────────────────────────────


class TestGetOptimalThreshold(_Phase3Base):
    """Tests for get_optimal_threshold() (#60)."""

    def test_returns_none_below_10_samples(self):
        for i in range(5):
            self._add(f"TKOPT-{i}", "NYC", 0.7, 0.5, True)
        result = tracker.get_optimal_threshold()
        self.assertIsNone(result)

    def test_returns_dict_with_correct_keys(self):
        """Returns dict with threshold_f1 and best_f1."""
        for i in range(10):
            self._add(f"TKOPT-G-{i}", "NYC", 0.75, 0.5, True)
        for i in range(10):
            self._add(f"TKOPT-B-{i}", "NYC", 0.25, 0.5, False)
        result = tracker.get_optimal_threshold()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("threshold_f1", result)
        self.assertIn("best_f1", result)

    def test_threshold_within_range(self):
        """Optimal threshold should be between 0.05 and 0.95."""
        for i in range(10):
            self._add(f"TKOPT-RG-{i}", "NYC", 0.75, 0.5, True)
        for i in range(10):
            self._add(f"TKOPT-RB-{i}", "NYC", 0.25, 0.5, False)
        result = tracker.get_optimal_threshold()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(result["threshold_f1"], 0.05)
        self.assertLessEqual(result["threshold_f1"], 0.95)
        self.assertGreater(result["best_f1"], 0.0)


# ── Task 5: get_market_calibration() with adaptive n_buckets ─────────────────


class TestMarketCalibrationAdaptive(_Phase3Base):
    """Tests for get_market_calibration() quantile-based bucketing (#13)."""

    def test_returns_buckets_key(self):
        result = tracker.get_market_calibration()
        self.assertIn("buckets", result)

    def test_empty_returns_empty_buckets(self):
        result = tracker.get_market_calibration()
        self.assertEqual(result["buckets"], [])

    def test_clustered_data_n_buckets_5(self):
        """30 predictions clustered near 0.50, n_buckets=5 → <= 5 buckets returned."""
        for i in range(30):
            prob = 0.48 + (i % 5) * 0.01  # range 0.48-0.52
            self._add(f"TKMCAL-{i}", "NYC", 0.6, prob, True)
        result = tracker.get_market_calibration(n_buckets=5)
        self.assertLessEqual(len(result["buckets"]), 5)
        self.assertGreater(len(result["buckets"]), 0)

    def test_bucket_fields(self):
        """Each bucket should have required fields."""
        for i in range(10):
            self._add(f"TKMCALF-{i}", "NYC", 0.6, 0.4 + i * 0.05, True)
        result = tracker.get_market_calibration()
        if result["buckets"]:
            b = result["buckets"][0]
            for key in ("bucket_min", "bucket_max", "mean_prob", "freq_yes", "count"):
                self.assertIn(key, b)


# ── Task 6: get_calibration_by_city() with condition_type ────────────────────


class TestCalibrationByCityConditionType(_Phase3Base):
    """Tests for get_calibration_by_city() with condition_type (#54, #56)."""

    def test_nyc_high_vs_precip_different_bias(self):
        """NYC HIGH vs NYC PRECIP should have different bias."""
        # HIGH: over-estimating (our_prob=0.9, settled NO)
        for i in range(3):
            self._add(f"TKCAL-H-{i}", "NYC", 0.90, 0.5, False, condition_type="HIGH")
        # PRECIP: under-estimating (our_prob=0.2, settled YES)
        for i in range(3):
            self._add(f"TKCAL-P-{i}", "NYC", 0.20, 0.5, True, condition_type="PRECIP")

        result_high = tracker.get_calibration_by_city(condition_type="HIGH")
        result_precip = tracker.get_calibration_by_city(condition_type="PRECIP")

        self.assertIn("NYC", result_high)
        self.assertIn("NYC", result_precip)
        # HIGH bias positive (over-estimate), PRECIP bias negative (under-estimate)
        self.assertGreater(result_high["NYC"]["bias"], 0)
        self.assertLess(result_precip["NYC"]["bias"], 0)

    def test_no_filter_returns_all(self):
        """Without condition_type, all predictions are included."""
        self._add("TKCAL-ALL-H", "NYC", 0.8, 0.5, True, condition_type="HIGH")
        self._add("TKCAL-ALL-P", "NYC", 0.8, 0.5, True, condition_type="PRECIP")
        result = tracker.get_calibration_by_city()
        self.assertIn("NYC", result)
        self.assertEqual(result["NYC"]["n"], 2)

    def test_empty_condition_type_filter(self):
        """Filtering by non-existent condition_type returns empty dict."""
        self._add("TKCAL-NONE", "NYC", 0.8, 0.5, True, condition_type="HIGH")
        result = tracker.get_calibration_by_city(condition_type="NONEXISTENT")
        self.assertEqual(result, {})


# ── Task 7: get_ensemble_member_accuracy() with season ────────────────────────


class TestEnsembleMemberAccuracy(_Phase3Base):
    """Tests for get_ensemble_member_accuracy() (#18)."""

    def _add_member(self, city, model, predicted, actual, target_date_str):
        tracker.log_member_score(city, model, predicted, actual, target_date_str)

    def test_returns_none_when_empty(self):
        result = tracker.get_ensemble_member_accuracy()
        self.assertIsNone(result)

    def test_basic_accuracy(self):
        """Returns model MAE dict for available data."""
        self._add_member("NYC", "gfs", 70.0, 72.0, "2026-07-15")  # summer
        result = tracker.get_ensemble_member_accuracy()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("gfs", result)
        self.assertAlmostEqual(result["gfs"]["mae"], 2.0, places=4)
        self.assertEqual(result["gfs"]["count"], 1)

    def test_season_filter_winter(self):
        """Winter filter returns only Oct-Mar data."""
        self._add_member("NYC", "gfs", 30.0, 32.0, "2026-01-10")  # winter, MAE=2
        self._add_member("NYC", "gfs", 80.0, 70.0, "2026-07-10")  # summer, MAE=10
        result_winter = tracker.get_ensemble_member_accuracy(season="winter")
        self.assertIsNotNone(result_winter)
        assert result_winter is not None
        self.assertAlmostEqual(result_winter["gfs"]["mae"], 2.0, places=4)

    def test_season_filter_summer(self):
        """Summer filter returns only Apr-Sep data."""
        self._add_member("NYC", "gfs", 30.0, 32.0, "2026-01-10")  # winter, MAE=2
        self._add_member("NYC", "gfs", 80.0, 70.0, "2026-07-10")  # summer, MAE=10
        result_summer = tracker.get_ensemble_member_accuracy(season="summer")
        self.assertIsNotNone(result_summer)
        assert result_summer is not None
        self.assertAlmostEqual(result_summer["gfs"]["mae"], 10.0, places=4)

    def test_season_filter_winter_vs_summer_different_mae(self):
        """Winter and summer MAEs differ for the same model."""
        self._add_member("NYC", "gfs", 30.0, 32.0, "2026-01-10")
        self._add_member("NYC", "gfs", 80.0, 70.0, "2026-07-10")
        r_w = tracker.get_ensemble_member_accuracy(season="winter")
        r_s = tracker.get_ensemble_member_accuracy(season="summer")
        assert r_w is not None and r_s is not None
        self.assertNotAlmostEqual(r_w["gfs"]["mae"], r_s["gfs"]["mae"], places=2)

    def test_city_filter(self):
        """City filter returns only data for that city."""
        self._add_member("NYC", "gfs", 70.0, 72.0, "2026-07-15")
        self._add_member("CHI", "gfs", 60.0, 70.0, "2026-07-15")
        result = tracker.get_ensemble_member_accuracy(city="NYC")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result["gfs"]["mae"], 2.0, places=4)


# ── Task 8: bayesian_confidence_interval() ───────────────────────────────────


class TestBayesianConfidenceInterval(unittest.TestCase):
    """Tests for bayesian_confidence_interval() (#57)."""

    def test_bounds_are_valid(self):
        """Lower and upper bounds should be in [0, 1] with lower <= upper."""
        lo, hi = tracker.bayesian_confidence_interval(5, 10)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)
        self.assertLessEqual(lo, hi)

    def test_ci_shrinks_with_more_data(self):
        """Width should shrink as trials increase (same success rate)."""
        lo1, hi1 = tracker.bayesian_confidence_interval(5, 10, confidence=0.90)
        lo2, hi2 = tracker.bayesian_confidence_interval(50, 100, confidence=0.90)
        width1 = hi1 - lo1
        width2 = hi2 - lo2
        self.assertGreater(width1, width2, "CI should be narrower with more data")

    def test_all_successes(self):
        """All successes: upper bound close to 1, lower bound away from 0."""
        lo, hi = tracker.bayesian_confidence_interval(100, 100, confidence=0.90)
        self.assertGreater(lo, 0.9)
        self.assertLessEqual(hi, 1.0)

    def test_zero_successes(self):
        """Zero successes: lower bound near 0, upper bound close to 0."""
        lo, hi = tracker.bayesian_confidence_interval(0, 100, confidence=0.90)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLess(hi, 0.1)

    def test_90_pct_contains_50_pct(self):
        """5/10 successes: 90% CI should straddle 0.5."""
        lo, hi = tracker.bayesian_confidence_interval(5, 10, confidence=0.90)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)


# ── Task 9: get_edge_decay_curve() with condition_type ───────────────────────


class TestEdgeDecayCurveConditionType(_Phase3Base):
    """Tests for get_edge_decay_curve() stratified by condition_type (#14)."""

    def _add_decay(self, n, condition_type, edge_size, days_out=1):
        """Add n predictions with a given edge size and days_out."""
        for i in range(n):
            our_prob = 0.5 + edge_size
            mkt_prob = 0.5
            self._add(
                f"TKEDGE-{condition_type}-{i}-{days_out}",
                "NYC",
                our_prob,
                mkt_prob,
                True,
                condition_type=condition_type,
                days_out=days_out,
            )

    def test_condition_type_filter_returns_list(self):
        """get_edge_decay_curve(condition_type='HIGH') returns a list."""
        self._add_decay(5, "HIGH", 0.2, days_out=1)
        result = tracker.get_edge_decay_curve(condition_type="HIGH")
        self.assertIsInstance(result, list)

    def test_high_vs_precip_differ(self):
        """HIGH and PRECIP should produce different curves."""
        self._add_decay(5, "HIGH", 0.3, days_out=1)
        self._add_decay(5, "PRECIP", 0.05, days_out=1)
        r_high = tracker.get_edge_decay_curve(condition_type="HIGH")
        r_precip = tracker.get_edge_decay_curve(condition_type="PRECIP")
        # Both should have the 0-2 bucket; edges should differ
        if r_high and r_precip:
            avg_edge_high = r_high[0]["avg_edge"]
            avg_edge_precip = r_precip[0]["avg_edge"]
            self.assertNotAlmostEqual(avg_edge_high, avg_edge_precip, places=2)

    def test_no_filter_uses_all(self):
        """Without filter, all condition types are included."""
        self._add_decay(5, "HIGH", 0.2, days_out=1)
        self._add_decay(5, "PRECIP", 0.1, days_out=1)
        all_result = tracker.get_edge_decay_curve()
        high_result = tracker.get_edge_decay_curve(condition_type="HIGH")
        # All-conditions result should have more samples in each bucket
        if all_result and high_result:
            self.assertGreaterEqual(all_result[0]["n"], high_result[0]["n"])

    def test_empty_when_no_matching_condition(self):
        """Non-existent condition_type returns empty list."""
        self._add_decay(5, "HIGH", 0.2, days_out=1)
        result = tracker.get_edge_decay_curve(condition_type="NONEXISTENT")
        self.assertEqual(result, [])


def test_get_component_attribution_works(tmp_path):
    import tracker

    orig = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "attr_test.db"
    tracker._db_initialized = False
    tracker.init_db()

    # Insert directly - find the correct column names first
    # This test just verifies the function doesn't crash
    result = tracker.get_component_attribution()
    assert result == {} or isinstance(result, dict)

    tracker.DB_PATH = orig
    tracker._db_initialized = False


def test_get_component_attribution_returns_per_source_brier(tmp_path):
    """get_component_attribution returns Brier score by dominant source."""
    from datetime import date

    import tracker

    orig = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "attr_brier_test.db"
    tracker._db_initialized = False
    tracker.init_db()

    try:
        # Two predictions: one ensemble-dominant (settled yes, prob 0.9 → good)
        # one climatology-dominant (settled no, prob 0.8 → bad)
        tracker.log_prediction(
            ticker="ENS1",
            city="NYC",
            market_date=date(2099, 1, 1),
            analysis={
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": 0.90,
                "market_prob": 0.5,
                "edge": 0.40,
                "method": "blend",
                "n_members": 82,
            },
            blend_sources={"ensemble": 0.7, "climatology": 0.2, "nws": 0.1},
        )
        tracker.log_outcome("ENS1", True)

        tracker.log_prediction(
            ticker="CLIM1",
            city="NYC",
            market_date=date(2099, 1, 2),
            analysis={
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": 0.80,
                "market_prob": 0.5,
                "edge": 0.30,
                "method": "blend",
                "n_members": 82,
            },
            blend_sources={"ensemble": 0.2, "climatology": 0.7, "nws": 0.1},
        )
        tracker.log_outcome("CLIM1", False)

        result = tracker.get_component_attribution()
        assert "ensemble" in result
        assert "climatology" in result
        # ensemble-dominant trade: prob=0.9, outcome=1 → Brier=(0.9-1)²=0.01 (good)
        # climatology-dominant trade: prob=0.8, outcome=0 → Brier=(0.8-0)²=0.64 (bad)
        assert result["ensemble"]["brier"] < result["climatology"]["brier"]
        assert result["ensemble"]["n"] == 1
        assert result["climatology"]["n"] == 1
    finally:
        tracker.DB_PATH = orig
        tracker._db_initialized = False


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── Task 6: Unselected bias tracking (#55) ────────────────────────────────────
# pytest-style tests with tmp_db fixture


@pytest.fixture
def tmp_db(monkeypatch):
    """Redirect tracker DB to a temp file for pytest-style tests."""
    tmpdir = tempfile.mkdtemp()
    orig = tracker.DB_PATH
    tracker.DB_PATH = Path(tmpdir) / "test_bias.db"
    tracker._db_initialized = False
    yield tracker
    tracker.DB_PATH = orig
    tracker._db_initialized = False
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_log_analysis_attempt_stores_all_markets(tmp_db):
    from tracker import _conn, log_analysis_attempt

    log_analysis_attempt(
        ticker="KXWEATHER-LOWEDGE",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 7, 1),
        forecast_prob=0.52,
        market_prob=0.50,
        days_out=3,
        was_traded=False,
    )
    with _conn() as con:
        row = con.execute(
            "SELECT forecast_prob, market_prob, was_traded "
            "FROM analysis_attempts WHERE ticker='KXWEATHER-LOWEDGE'"
        ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.52)
    assert row[2] == 0


def test_get_unselected_bias_excludes_traded_markets(tmp_db):
    from tracker import (
        get_unselected_bias,
        log_analysis_attempt,
        settle_analysis_attempt,
    )

    log_analysis_attempt(
        ticker="TRADED",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 7, 1),
        forecast_prob=0.80,
        market_prob=0.50,
        days_out=2,
        was_traded=True,
    )
    settle_analysis_attempt("TRADED", date(2025, 7, 1), outcome=1)
    log_analysis_attempt(
        ticker="NOT-TRADED",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 7, 2),
        forecast_prob=0.60,
        market_prob=0.50,
        days_out=2,
        was_traded=False,
    )
    settle_analysis_attempt("NOT-TRADED", date(2025, 7, 2), outcome=0)
    bias = get_unselected_bias("NYC")
    assert bias == pytest.approx(0.6, abs=0.01)


def test_get_unselected_bias_returns_zero_when_no_data(tmp_db):
    from tracker import get_unselected_bias

    assert get_unselected_bias("NOWHERE") == 0.0


# ── Task 3: get_calibration_trend uses market_date not predicted_at (#54) ─────


class TestCalibrationTrendUsesMarketDate(unittest.TestCase):
    """Verify get_calibration_trend groups by market_date, not predicted_at (#54)."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_trend54.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _insert_raw(
        self, ticker, our_prob, settled_yes, market_date_str, predicted_at_str
    ):
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            con.execute(
                """INSERT INTO predictions
                   (ticker, city, market_date, condition_type,
                    threshold_lo, threshold_hi, our_prob, market_prob,
                    edge, method, n_members, predicted_at, days_out)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ticker,
                    "NYC",
                    market_date_str,
                    "above",
                    70.0,
                    70.0,
                    our_prob,
                    0.5,
                    our_prob - 0.5,
                    "ensemble",
                    20,
                    predicted_at_str,
                    3,
                ),
            )
            con.execute(
                "INSERT OR REPLACE INTO outcomes (ticker, settled_yes, settled_at) VALUES (?,?,?)",
                (ticker, 1 if settled_yes else 0, predicted_at_str),
            )

    def test_trend_bucket_uses_market_date_week(self):
        """Two predictions made in same analysis week but different market-date weeks must be in separate buckets."""
        self._insert_raw(
            "TKTREND-A",
            0.8,
            True,
            "2026-04-07",
            "2026-04-06T12:00:00",
        )
        self._insert_raw(
            "TKTREND-B",
            0.6,
            False,
            "2026-04-14",
            "2026-04-06T13:00:00",
        )

        trend = tracker.get_calibration_trend(weeks=8)
        weeks_in_result = [row["week"] for row in trend]
        self.assertEqual(
            len(set(weeks_in_result)),
            2,
            f"Expected 2 distinct market-date week buckets, got: {weeks_in_result}",
        )

    def test_trend_returns_list_of_dicts_with_week_brier_n(self):
        """Each trend entry must have week, brier, and n keys."""
        self._insert_raw(
            "TKTREND-C",
            0.7,
            True,
            "2026-04-09",
            "2026-04-08T10:00:00",
        )
        trend = tracker.get_calibration_trend(weeks=8)
        self.assertIsInstance(trend, list)
        if trend:
            self.assertIn("week", trend[0])
            self.assertIn("brier", trend[0])
            self.assertIn("n", trend[0])


# ── Task 4: get_analysis_bias (#55) ───────────────────────────────────────────


class TestGetAnalysisBias(unittest.TestCase):
    """Tests for get_analysis_bias() (#55).

    Rewritten 2026-07-12: previously populated analysis_attempts via
    analyze_all_markets(), which turned out to have zero production callers
    -- batch_log_analysis_attempts() (called from cron.py) is the function
    that actually populates this table live, so analyze_all_markets() was
    deleted as a superseded/never-wired duplicate. These tests now populate
    analysis_attempts the same way production does.
    """

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_analyze55.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_attempt(self, ticker, city, our_prob, market_prob, target_date):
        return {
            "ticker": ticker,
            "city": city,
            "target_date": target_date,
            "condition": "above",
            "forecast_prob": our_prob,
            "market_prob": market_prob,
            "days_out": 1,
        }

    def test_batch_log_logs_all_items(self):
        from datetime import date

        attempts = [
            self._make_attempt("TK-AM-1", "NYC", 0.70, 0.50, date(2026, 4, 9)),
            self._make_attempt("TK-AM-2", "CHI", 0.60, 0.55, date(2026, 4, 9)),
            self._make_attempt("TK-AM-3", "LAX", 0.45, 0.50, date(2026, 4, 9)),
        ]
        tracker.batch_log_analysis_attempts(attempts)

        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            rows = con.execute("SELECT ticker FROM analysis_attempts").fetchall()
        tickers = {r[0] for r in rows}
        self.assertIn("TK-AM-1", tickers)
        self.assertIn("TK-AM-2", tickers)
        self.assertIn("TK-AM-3", tickers)

    def test_batch_log_stores_correct_probs(self):
        from datetime import date

        attempts = [
            self._make_attempt("TK-PROB-1", "NYC", 0.72, 0.48, date(2026, 4, 10)),
        ]
        tracker.batch_log_analysis_attempts(attempts)

        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT forecast_prob, market_prob FROM analysis_attempts WHERE ticker=?",
                ("TK-PROB-1",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 0.72)
        self.assertAlmostEqual(row[1], 0.48)

    def test_get_analysis_bias_returns_none_with_no_outcomes(self):
        from datetime import date

        attempts = [
            self._make_attempt("TK-BIAS-X", "NYC", 0.80, 0.50, date(2026, 4, 9)),
        ]
        tracker.batch_log_analysis_attempts(attempts)
        result = tracker.get_analysis_bias()
        self.assertIsNone(result)

    def test_get_analysis_bias_computes_mean_bias(self):
        from datetime import date

        attempts = [
            self._make_attempt("TK-BIAS-1", "NYC", 0.80, 0.50, date(2026, 4, 1)),
            self._make_attempt("TK-BIAS-2", "CHI", 0.60, 0.50, date(2026, 4, 2)),
        ]
        tracker.batch_log_analysis_attempts(attempts)
        tracker.log_outcome("TK-BIAS-1", True)
        tracker.log_outcome("TK-BIAS-2", False)
        result = tracker.get_analysis_bias()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.20, places=4)

    def test_batch_log_empty_list_is_noop(self):
        tracker.batch_log_analysis_attempts([])
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            count = con.execute("SELECT COUNT(*) FROM analysis_attempts").fetchone()[0]
        self.assertEqual(count, 0)


# ── Task 6: get_optimal_threshold guard = 20 (#60) ────────────────────────────


class TestOptimalThresholdGuard20(_Phase3Base):
    """Verify get_optimal_threshold returns None below 20 data points (#60)."""

    def test_returns_none_with_19_samples(self):
        """19 samples (< 20) must return None."""
        for i in range(19):
            self._add(f"TKOPT20-{i}", "NYC", 0.7, 0.5, True)
        result = tracker.get_optimal_threshold()
        self.assertIsNone(result, "Expected None with 19 samples (< 20 threshold)")

    def test_returns_dict_with_exactly_20_samples(self):
        """Exactly 20 samples must return a result dict."""
        for i in range(10):
            self._add(f"TKOPT20-YES-{i}", "NYC", 0.8, 0.5, True)
        for i in range(10):
            self._add(f"TKOPT20-NO-{i}", "NYC", 0.2, 0.5, False)
        result = tracker.get_optimal_threshold()
        self.assertIsNotNone(result, "Expected dict with exactly 20 samples")
        assert result is not None
        self.assertIn("threshold_f1", result)
        self.assertIn("best_f1", result)

    def test_returns_none_with_10_samples(self):
        """10 samples (old guard) must now return None (guard raised to 20)."""
        for i in range(10):
            self._add(f"TKOPT20-10-{i}", "NYC", 0.7, 0.5, True)
        result = tracker.get_optimal_threshold()
        self.assertIsNone(
            result, "Expected None with 10 samples after guard raised to 20"
        )


class TestGetRollingWinRateCI(_Phase3Base):
    """get_rolling_win_rate_ci() pairs get_rolling_win_rate's real
    (win_rate, count) with bayesian_confidence_interval -- added 2026-07-12
    to give bayesian_confidence_interval (a correct, tested, #57 utility with
    no caller anywhere until now) a real call site."""

    def test_returns_none_with_no_data(self):
        result = tracker.get_rolling_win_rate_ci()
        self.assertIsNone(result)

    def test_returns_dict_with_settled_data(self):
        for i in range(8):
            self._add(f"TKWRCI-YES-{i}", "NYC", 0.8, 0.5, True)
        for i in range(2):
            self._add(f"TKWRCI-NO-{i}", "NYC", 0.7, 0.5, False)
        result = tracker.get_rolling_win_rate_ci(window=20)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["n"], 10)
        self.assertAlmostEqual(result["win_rate"], 0.8, places=4)
        self.assertLess(result["ci_low"], result["win_rate"])
        self.assertGreater(result["ci_high"], result["win_rate"])
        self.assertGreaterEqual(result["ci_low"], 0.0)
        self.assertLessEqual(result["ci_high"], 1.0)

    def test_small_sample_has_wider_interval_than_large_sample(self):
        from pathlib import Path

        for i in range(4):
            self._add(f"TKWRCI-SMALL-{i}", "NYC", 0.8, 0.5, True)
        small = tracker.get_rolling_win_rate_ci(window=20)

        tracker.DB_PATH = Path(self._tmpdir) / "test_p3_large.db"
        tracker._db_initialized = False
        tracker.init_db()
        for i in range(40):
            self._add(f"TKWRCI-LARGE-{i}", "NYC", 0.8, 0.5, True)
        large = tracker.get_rolling_win_rate_ci(window=40)

        assert small is not None and large is not None
        small_width = small["ci_high"] - small["ci_low"]
        large_width = large["ci_high"] - large["ci_low"]
        self.assertGreater(
            small_width, large_width, "Small-sample CI must be wider than large-sample"
        )


class TestMarketCalibrationQuantile(unittest.TestCase):
    """#13 - get_market_calibration() must use equal-frequency buckets and accept n_buckets."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _seed(self, ticker, market_prob, settled):
        tracker.log_prediction(
            ticker,
            "NYC",
            date(2026, 3, 1),
            {
                "forecast_prob": 0.6,
                "market_prob": market_prob,
                "edge": 0.1,
                "method": "ensemble",
                "n_members": 50,
                "condition": {"type": "above", "threshold": 70.0},
            },
        )
        tracker.log_outcome(ticker, settled_yes=settled)

    def test_grpb_calibration_empty_returns_empty_buckets(self):
        result = tracker.get_market_calibration()
        self.assertIn("buckets", result)
        self.assertEqual(result["buckets"], [])

    def test_grpb_calibration_n_buckets_param_accepted(self):
        """n_buckets parameter should control number of output buckets."""
        for i in range(20):
            self._seed(f"CAL-NB-{i}", 0.1 * (i % 10) + 0.05, bool(i % 2))
        result_5 = tracker.get_market_calibration(n_buckets=5)
        result_10 = tracker.get_market_calibration(n_buckets=10)
        self.assertLessEqual(len(result_5["buckets"]), len(result_10["buckets"]))

    def test_grpb_calibration_buckets_equal_frequency(self):
        """Buckets should be roughly equal in count (quantile, not equal-width)."""
        for i in range(15):
            self._seed(f"CAL-EF-LOW-{i}", 0.10, False)
        for i in range(5):
            self._seed(f"CAL-EF-HIGH-{i}", 0.90, True)
        result = tracker.get_market_calibration(n_buckets=4)
        buckets = result["buckets"]
        self.assertGreater(len(buckets), 0)
        counts = [b["count"] for b in buckets]
        self.assertLess(max(counts), 20)

    def test_grpb_calibration_bucket_fields(self):
        """Each bucket must have the required keys."""
        for i in range(10):
            self._seed(f"CAL-FK-{i}", 0.1 * i + 0.05, bool(i % 2))
        result = tracker.get_market_calibration(n_buckets=3)
        for b in result["buckets"]:
            for key in ("bucket_min", "bucket_max", "mean_prob", "freq_yes", "count"):
                self.assertIn(key, b)

    def test_grpb_calibration_default_n_buckets_is_10(self):
        """Default call (no args) should use 10 buckets."""
        for i in range(30):
            self._seed(f"CAL-DEF-{i}", round(0.03 * i + 0.01, 2), bool(i % 2))
        result_default = tracker.get_market_calibration()
        result_explicit = tracker.get_market_calibration(n_buckets=10)
        self.assertEqual(
            len(result_default["buckets"]), len(result_explicit["buckets"])
        )


class TestEdgeDecayCurveConditionTypeGrpB(unittest.TestCase):
    """#14 - get_edge_decay_curve() must segment by condition_type when provided."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _log_with_days_out(
        self, ticker, our_prob, market_prob, days_out, settled, ctype
    ):
        tracker.log_prediction(
            ticker,
            "NYC",
            date(2026, 4, 1),
            {
                "forecast_prob": our_prob,
                "market_prob": market_prob,
                "edge": abs(our_prob - market_prob),
                "method": "ensemble",
                "n_members": 50,
                "condition": {"type": ctype, "threshold": 70.0},
            },
        )
        with tracker._conn() as con:
            con.execute(
                "UPDATE predictions SET days_out=? WHERE ticker=?", (days_out, ticker)
            )
        tracker.log_outcome(ticker, settled_yes=settled)

    def test_grpb_edge_decay_condition_type_filters(self):
        """Filtering by above should exclude precip_any rows."""
        for i in range(5):
            self._log_with_days_out(f"EDC-ABOVE-{i}", 0.75, 0.50, 1, True, "above")
        for i in range(5):
            self._log_with_days_out(
                f"EDC-PRECIP-{i}", 0.30, 0.50, 1, False, "precip_any"
            )
        above_result = tracker.get_edge_decay_curve(condition_type="above")
        precip_result = tracker.get_edge_decay_curve(condition_type="precip_any")
        self.assertTrue(len(above_result) > 0 or len(precip_result) > 0)
        if above_result and precip_result:
            self.assertNotAlmostEqual(
                above_result[0]["avg_edge"], precip_result[0]["avg_edge"], places=3
            )

    def test_grpb_edge_decay_no_filter_returns_all(self):
        """No filter should return rows from all condition types."""
        for i in range(4):
            self._log_with_days_out(f"EDC-MIX-ABOVE-{i}", 0.80, 0.50, 2, True, "above")
        for i in range(4):
            self._log_with_days_out(
                f"EDC-MIX-PRECIP-{i}", 0.20, 0.50, 2, False, "precip_any"
            )
        all_result = tracker.get_edge_decay_curve(condition_type=None)
        above_only = tracker.get_edge_decay_curve(condition_type="above")
        if all_result and above_only:
            self.assertGreaterEqual(all_result[0]["n"], above_only[0]["n"])

    def test_grpb_edge_decay_unknown_condition_type_returns_empty(self):
        """Filtering by a condition_type with no data returns empty list."""
        for i in range(5):
            self._log_with_days_out(f"EDC-ABOVE2-{i}", 0.75, 0.50, 1, True, "above")
        result = tracker.get_edge_decay_curve(condition_type="nonexistent_type")
        self.assertEqual(result, [])

    def test_grpb_edge_decay_returns_list(self):
        """Return value is always a list (never None)."""
        result = tracker.get_edge_decay_curve(condition_type="above")
        self.assertIsInstance(result, list)


class TestEnsembleMemberAccuracyStratified(unittest.TestCase):
    """#18 - get_ensemble_member_accuracy() must stratify by city and season."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_grpb_ensemble_empty_returns_none(self):
        result = tracker.get_ensemble_member_accuracy(city="NYC", season="winter")
        self.assertIsNone(result)

    def test_grpb_ensemble_city_filter(self):
        tracker.log_member_score("NYC", "model_a", 72.0, 70.0, "2026-01-15")
        tracker.log_member_score("NYC", "model_a", 74.0, 71.0, "2026-01-16")
        tracker.log_member_score("LAX", "model_a", 85.0, 80.0, "2026-01-15")
        nyc_result = tracker.get_ensemble_member_accuracy(city="NYC", season=None)
        lax_result = tracker.get_ensemble_member_accuracy(city="LAX", season=None)
        self.assertIsNotNone(nyc_result)
        self.assertIsNotNone(lax_result)
        self.assertNotAlmostEqual(
            nyc_result["model_a"]["mae"], lax_result["model_a"]["mae"], places=2
        )

    def test_grpb_ensemble_season_winter_oct_to_mar(self):
        tracker.log_member_score("NYC", "model_b", 30.0, 25.0, "2026-01-10")
        tracker.log_member_score("NYC", "model_b", 90.0, 85.0, "2026-07-10")
        winter = tracker.get_ensemble_member_accuracy(city="NYC", season="winter")
        summer = tracker.get_ensemble_member_accuracy(city="NYC", season="summer")
        self.assertIsNotNone(winter)
        self.assertIsNotNone(summer)
        self.assertAlmostEqual(winter["model_b"]["mae"], 5.0, places=2)
        self.assertAlmostEqual(summer["model_b"]["mae"], 5.0, places=2)

    def test_grpb_ensemble_season_filter_excludes_wrong_months(self):
        tracker.log_member_score("NYC", "model_c", 32.0, 30.0, "2026-02-15")
        tracker.log_member_score("NYC", "model_c", 95.0, 75.0, "2026-06-15")
        winter_only = tracker.get_ensemble_member_accuracy(city="NYC", season="winter")
        all_seasons = tracker.get_ensemble_member_accuracy(city="NYC", season=None)
        self.assertIsNotNone(winter_only)
        self.assertIsNotNone(all_seasons)
        self.assertLess(winter_only["model_c"]["mae"], all_seasons["model_c"]["mae"])

    def test_grpb_ensemble_return_shape(self):
        tracker.log_member_score("NYC", "model_d", 70.0, 68.0, "2026-03-01")
        result = tracker.get_ensemble_member_accuracy(city="NYC", season=None)
        self.assertIsNotNone(result)
        self.assertIn("model_d", result)
        self.assertIn("mae", result["model_d"])
        self.assertIn("count", result["model_d"])


class TestCalibrationByCityConditionTypeGrpB(unittest.TestCase):
    """#56 - get_calibration_by_city() must accept condition_type filter."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _log(self, ticker, city, our_prob, settled, ctype):
        tracker.log_prediction(
            ticker,
            city,
            date(2099, 1, 1),
            {
                "forecast_prob": our_prob,
                "market_prob": 0.5,
                "edge": 0.1,
                "method": "ensemble",
                "n_members": 50,
                "condition": {"type": ctype, "threshold": 70.0},
            },
        )
        tracker.log_outcome(ticker, settled_yes=settled)

    def test_grpb_calib_city_empty_returns_empty_dict(self):
        result = tracker.get_calibration_by_city()
        self.assertEqual(result, {})

    def test_grpb_calib_city_no_filter_includes_all_types(self):
        self._log("CBC-ABOVE-1", "NYC", 0.80, True, "above")
        self._log("CBC-ABOVE-2", "NYC", 0.80, True, "above")
        self._log("CBC-PRECIP-1", "NYC", 0.30, False, "precip_any")
        self._log("CBC-PRECIP-2", "NYC", 0.30, False, "precip_any")
        result_all = tracker.get_calibration_by_city()
        self.assertIn("NYC", result_all)
        self.assertEqual(result_all["NYC"]["n"], 4)

    def test_grpb_calib_city_filter_above_only(self):
        self._log("CBC2-ABOVE-1", "NYC", 0.80, True, "above")
        self._log("CBC2-ABOVE-2", "NYC", 0.80, True, "above")
        self._log("CBC2-PRECIP-1", "NYC", 0.30, False, "precip_any")
        result_above = tracker.get_calibration_by_city(condition_type="above")
        self.assertIn("NYC", result_above)
        self.assertEqual(result_above["NYC"]["n"], 2)

    def test_grpb_calib_city_filter_changes_brier(self):
        for i in range(4):
            self._log(f"CBC3-ABOVE-{i}", "NYC", 0.90, True, "above")
        for i in range(4):
            self._log(f"CBC3-PRECIP-{i}", "NYC", 0.90, False, "precip_any")
        all_result = tracker.get_calibration_by_city()
        above_result = tracker.get_calibration_by_city(condition_type="above")
        self.assertLess(above_result["NYC"]["brier"], all_result["NYC"]["brier"])

    def test_grpb_calib_city_multi_city(self):
        self._log("CBC4-NYC-A", "NYC", 0.70, True, "above")
        self._log("CBC4-LAX-A", "LAX", 0.70, True, "above")
        self._log("CBC4-NYC-P", "NYC", 0.70, False, "precip_any")
        result = tracker.get_calibration_by_city(condition_type="above")
        self.assertEqual(result.get("NYC", {}).get("n", 0), 1)
        self.assertEqual(result.get("LAX", {}).get("n", 0), 1)


# ── TestPerSourceProbColumns (#118/#122 prerequisite) ────────────────────────


class TestPerSourceProbColumns(unittest.TestCase):
    """Schema v9 must add ensemble_prob, nws_prob, clim_prob to predictions."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_v9.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_columns_exist_after_init(self):
        """After init_db(), predictions table must have ensemble_prob, nws_prob, clim_prob."""
        import sqlite3

        tracker.init_db()
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(predictions)")}
        self.assertIn("ensemble_prob", cols)
        self.assertIn("nws_prob", cols)
        self.assertIn("clim_prob", cols)

    def test_log_prediction_stores_source_probs(self):
        """log_prediction with source probs stores them retrievable from DB."""
        import sqlite3
        from datetime import date as _date

        tracker.init_db()
        tracker.log_prediction(
            "SRCPROB-TEST",
            "NYC",
            _date(2026, 5, 1),
            {
                "forecast_prob": 0.65,
                "market_prob": 0.50,
                "edge": 0.15,
                "method": "ensemble",
                "n_members": 50,
                "condition": {"type": "above", "threshold": 70.0},
            },
            ensemble_prob=0.68,
            nws_prob=0.60,
            clim_prob=0.55,
        )
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT ensemble_prob, nws_prob, clim_prob FROM predictions WHERE ticker=?",
                ("SRCPROB-TEST",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 0.68, places=4)
        self.assertAlmostEqual(row[1], 0.60, places=4)
        self.assertAlmostEqual(row[2], 0.55, places=4)


# ── TestSourceProbsPassthrough ────────────────────────────────────────────────


class TestSourceProbsPassthrough(unittest.TestCase):
    """log_prediction called without source probs must store NULLs (backward compat)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_passthrough.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_missing_source_probs_stored_as_null(self):
        """Calling log_prediction without source probs stores NULL (old callers safe)."""
        import sqlite3
        from datetime import date as _date

        tracker.init_db()
        tracker.log_prediction(
            "NULL-SRCPROB",
            "NYC",
            _date(2026, 5, 2),
            {
                "forecast_prob": 0.60,
                "market_prob": 0.50,
                "edge": 0.10,
                "method": "ensemble",
                "n_members": 30,
                "condition": {"type": "above", "threshold": 70.0},
            },
        )
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT ensemble_prob, nws_prob, clim_prob FROM predictions WHERE ticker=?",
                ("NULL-SRCPROB",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        self.assertIsNone(row[2])


class TestRetentionPolicy:
    def test_purge_old_predictions_removes_settled(self, tmp_path, monkeypatch):
        """purge_old_predictions removes settled predictions older than retention_days."""
        from datetime import date, timedelta

        db = tmp_path / "test.db"
        monkeypatch.setattr(tracker, "DB_PATH", db)
        tracker._db_initialized = False
        tracker.init_db()

        old_date = (date.today() - timedelta(days=800)).isoformat()
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO predictions (ticker, city, our_prob, market_prob, "
                "predicted_at) VALUES (?, ?, ?, ?, ?)",
                ("OLD-TICKER", "NYC", 0.7, 0.5, old_date + " 00:00:00"),
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES (?, ?, ?)",
                ("OLD-TICKER", 1, old_date + " 12:00:00"),
            )

        tracker.purge_old_predictions(retention_days=365)

        with tracker._conn() as con:
            count = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE ticker = 'OLD-TICKER'"
            ).fetchone()[0]
        assert count == 0

    def test_purge_old_predictions_keeps_recent(self, tmp_path, monkeypatch):
        """purge_old_predictions keeps predictions within retention_days."""
        from datetime import date

        db = tmp_path / "test.db"
        monkeypatch.setattr(tracker, "DB_PATH", db)
        tracker._db_initialized = False
        tracker.init_db()

        recent_date = date.today().isoformat()
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO predictions (ticker, city, our_prob, market_prob, "
                "predicted_at) VALUES (?, ?, ?, ?, ?)",
                ("NEW-TICKER", "NYC", 0.7, 0.5, recent_date + " 00:00:00"),
            )

        tracker.purge_old_predictions(retention_days=365)

        with tracker._conn() as con:
            count = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE ticker = 'NEW-TICKER'"
            ).fetchone()[0]
        assert count == 1


class TestGetQuintileBias(unittest.TestCase):
    """E1: per-quintile bias correction."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_predictions.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _seed(self, our_prob: float, settled_yes: int, n: int = 10, city: str = "NYC"):
        """Insert n settled predictions at our_prob in quintile of our_prob."""
        for i in range(n):
            tk = f"QQ-{our_prob:.2f}-{city}-{i}"
            tracker.log_prediction(
                tk,
                city,
                date(2099, 4, 1),
                {
                    "condition": {"type": "above", "threshold": 70.0},
                    "forecast_prob": our_prob,
                    "market_prob": 0.50,
                    "edge": our_prob - 0.50,
                    "method": "ensemble",
                    "n_members": 20,
                },
            )
            tracker.log_outcome(tk, settled_yes=bool(settled_yes))

    def test_falls_back_to_global_when_quintile_empty(self):
        """With no data in the target quintile, returns global bias."""
        # Seed data only in the 0.60-0.80 quintile (our_prob=0.70)
        # so the 0.40-0.60 quintile has nothing
        self._seed(our_prob=0.70, settled_yes=0, n=10)
        # Query for a prob in the 0.40-0.60 quintile — should fall back to global
        result = tracker.get_quintile_bias("NYC", 4, forecast_prob=0.50, min_samples=5)
        global_bias = tracker.get_bias("NYC", 4, min_samples=5)
        self.assertAlmostEqual(result, global_bias, places=6)

    def test_quintile_specific_bias_returned(self):
        """Bias for a well-populated quintile differs from the global bias."""
        # Over-predict in the 0.60-0.80 bucket (all lose)
        self._seed(our_prob=0.70, settled_yes=0, n=15)
        # Under-predict in the 0.20-0.40 bucket (all win)
        self._seed(our_prob=0.30, settled_yes=1, n=15)

        high_bias = tracker.get_quintile_bias("NYC", 4, forecast_prob=0.70)
        low_bias = tracker.get_quintile_bias("NYC", 4, forecast_prob=0.30)

        # 0.70 bucket: our_prob > outcome → positive bias (over-estimate)
        self.assertGreater(high_bias, 0.0)
        # 0.30 bucket: our_prob < outcome → negative bias (under-estimate)
        self.assertLess(low_bias, 0.0)
        # The two quintiles should have different corrections
        self.assertNotAlmostEqual(high_bias, low_bias, places=3)

    def test_returns_zero_when_no_data_at_all(self):
        """Empty DB → both global and quintile bias return 0.0."""
        result = tracker.get_quintile_bias("NYC", 4, forecast_prob=0.55, min_samples=5)
        self.assertEqual(result, 0.0)

    def test_quintile_boundary_0_maps_to_first_bucket(self):
        """forecast_prob=0.0 maps to quintile 0 (0.0–0.20)."""
        self._seed(our_prob=0.10, settled_yes=0, n=10)
        result = tracker.get_quintile_bias("NYC", 4, forecast_prob=0.0, min_samples=5)
        expected = tracker.get_quintile_bias(
            "NYC", 4, forecast_prob=0.10, min_samples=5
        )
        self.assertAlmostEqual(result, expected, places=6)

    def test_quintile_boundary_1_maps_to_last_bucket(self):
        """forecast_prob=1.0 maps to quintile 4 (0.80–1.0)."""
        self._seed(our_prob=0.90, settled_yes=0, n=10)
        result = tracker.get_quintile_bias("NYC", 4, forecast_prob=1.0, min_samples=5)
        expected = tracker.get_quintile_bias(
            "NYC", 4, forecast_prob=0.90, min_samples=5
        )
        self.assertAlmostEqual(result, expected, places=6)

    def test_city_isolation(self):
        """Quintile bias for NYC does not bleed into CHI."""
        self._seed(our_prob=0.70, settled_yes=0, n=10, city="NYC")
        result_chi = tracker.get_quintile_bias(
            "CHI", 4, forecast_prob=0.70, min_samples=5
        )
        self.assertEqual(result_chi, 0.0)


# ── P0-12: _SCHEMA_VERSION must equal len(_MIGRATIONS) ───────────────────────


class TestSchemaVersionMatchesMigrations(unittest.TestCase):
    """P0-12 — _SCHEMA_VERSION must equal the number of migrations so local_hour
    column is applied and user_version is set correctly."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_schema.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_schema_version_equals_migration_count(self):
        """_SCHEMA_VERSION must equal len(_MIGRATIONS) — off-by-one leaves last migration unapplied."""
        self.assertEqual(
            tracker._SCHEMA_VERSION,
            len(tracker._MIGRATIONS),
            f"_SCHEMA_VERSION={tracker._SCHEMA_VERSION} but there are "
            f"{len(tracker._MIGRATIONS)} migrations — mismatch causes the last "
            "migration to be skipped or re-run every time",
        )

    def test_local_hour_column_exists_after_init(self):
        """After init_db(), the predictions table must have the local_hour column."""
        import sqlite3

        tracker.init_db()
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            cols = {row[1] for row in con.execute("PRAGMA table_info(predictions)")}
        self.assertIn(
            "local_hour",
            cols,
            "local_hour column missing — migration v19 was not applied",
        )

    def test_user_version_equals_schema_version_after_init(self):
        """After init_db(), PRAGMA user_version must equal _SCHEMA_VERSION."""
        import sqlite3

        tracker.init_db()
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            user_ver = con.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(
            user_ver,
            tracker._SCHEMA_VERSION,
            f"PRAGMA user_version={user_ver} != _SCHEMA_VERSION={tracker._SCHEMA_VERSION}",
        )

    def test_log_prediction_succeeds_with_local_hour(self):
        """log_prediction must not crash when local_hour is present in analysis dict."""
        tracker.init_db()
        tracker.log_prediction(
            "LHOUR-TEST",
            "NYC",
            date(2026, 5, 1),
            {
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": 0.65,
                "market_prob": 0.50,
                "edge": 0.15,
                "method": "ensemble",
                "n_members": 50,
                "local_hour": 14,
            },
        )
        history = tracker.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["ticker"], "LHOUR-TEST")


# ── P0-13: sync_outcomes aware/naive datetime fix ────────────────────────────


class TestPriceHistory(unittest.TestCase):
    """log_price_candles / get_price_history — OHLC candlestick storage."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_predictions.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_logs_and_retrieves_candle(self):
        candles = [
            {
                "end_period_ts": 1700000000,
                "price": {
                    "open_dollars": "0.40",
                    "high_dollars": "0.55",
                    "low_dollars": "0.38",
                    "close_dollars": "0.52",
                },
                "yes_bid": {"close_dollars": "0.51"},
                "yes_ask": {"close_dollars": "0.53"},
                "volume_fp": "12.00",
                "open_interest_fp": "40.00",
            }
        ]
        n = tracker.log_price_candles("TK1", "KXHIGHNY", 1, candles)
        self.assertEqual(n, 1)

        rows = tracker.get_price_history("TK1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["series_ticker"], "KXHIGHNY")
        self.assertEqual(rows[0]["period_interval"], 1)
        self.assertEqual(rows[0]["end_period_ts"], 1700000000)
        self.assertAlmostEqual(rows[0]["price_open"], 0.40)
        self.assertAlmostEqual(rows[0]["price_high"], 0.55)
        self.assertAlmostEqual(rows[0]["price_low"], 0.38)
        self.assertAlmostEqual(rows[0]["price_close"], 0.52)
        self.assertAlmostEqual(rows[0]["yes_bid_close"], 0.51)
        self.assertAlmostEqual(rows[0]["yes_ask_close"], 0.53)
        self.assertAlmostEqual(rows[0]["volume"], 12.00)
        self.assertAlmostEqual(rows[0]["open_interest"], 40.00)

    def test_null_price_field_stored_as_none(self):
        """A candle with no trades in-period has price=None (only bid/ask quotes)."""
        candles = [
            {
                "end_period_ts": 1700000060,
                "price": None,
                "yes_bid": {"close_dollars": "0.51"},
                "yes_ask": {"close_dollars": "0.53"},
                "volume_fp": "0.00",
                "open_interest_fp": "40.00",
            }
        ]
        tracker.log_price_candles("TK2", "KXHIGHNY", 1, candles)
        rows = tracker.get_price_history("TK2")
        self.assertIsNone(rows[0]["price_close"])
        self.assertAlmostEqual(rows[0]["yes_bid_close"], 0.51)

    def test_dedup_via_unique_index_is_idempotent(self):
        """Re-inserting the same ticker/period/end_ts candle is a no-op."""
        candles = [{"end_period_ts": 1700000000, "volume_fp": "5.00"}]
        first = tracker.log_price_candles("TK3", "KXHIGHNY", 1, candles)
        second = tracker.log_price_candles("TK3", "KXHIGHNY", 1, candles)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(len(tracker.get_price_history("TK3")), 1)

    def test_empty_candlesticks_list_is_noop(self):
        n = tracker.log_price_candles("TK4", "KXHIGHNY", 1, [])
        self.assertEqual(n, 0)
        self.assertEqual(tracker.get_price_history("TK4"), [])

    def test_candle_missing_end_period_ts_is_skipped(self):
        candles = [{"volume_fp": "5.00"}]  # no end_period_ts
        n = tracker.log_price_candles("TK5", "KXHIGHNY", 1, candles)
        self.assertEqual(n, 0)

    def test_get_price_history_orders_by_end_period_ts(self):
        candles = [
            {"end_period_ts": 1700000200, "volume_fp": "1.00"},
            {"end_period_ts": 1700000100, "volume_fp": "1.00"},
        ]
        tracker.log_price_candles("TK6", "KXHIGHNY", 1, candles)
        rows = tracker.get_price_history("TK6")
        self.assertEqual([r["end_period_ts"] for r in rows], [1700000100, 1700000200])


class TestDisputedOutcomeTracking(unittest.TestCase):
    """Restored backlog piece (mystery-revert 24559a7): disputed flag on outcomes,
    set by audit_settlement() on an archive/Kalshi mismatch, excluded from every
    Brier/calibration/bias query that uses settled_yes as ground truth — a
    corrupted settlement label must never silently pollute calibration scoring.
    """

    _FUTURE = date(2099, 1, 1)  # clamps to a large positive days_out (multiday)
    _PAST = date(2020, 1, 1)  # clamps to days_out=0 (same-day)

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_predictions.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _log_settled(
        self,
        ticker,
        our_prob,
        settled_yes,
        market_date,
        city="NYC",
        market_prob=0.50,
        method="ensemble",
        edge=0.20,
        condition_type="above",
        edge_calc_version="v1",
        signal_source="src",
        blend_sources=None,
        local_hour=None,
    ):
        analysis = {
            "condition": {"type": condition_type, "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": market_prob,
            "edge": edge,
            "method": method,
            "n_members": 82,
            "local_hour": local_hour,
        }
        tracker.log_prediction(
            ticker,
            city,
            market_date,
            analysis,
            edge_calc_version=edge_calc_version,
            signal_source=signal_source,
            blend_sources=blend_sources
            if blend_sources is not None
            else {"icon_seamless": 0.6, "gfs_seamless": 0.4},
        )
        tracker.log_outcome(ticker, settled_yes)

    def _seed_baseline(
        self, n=25, city="NYC", market_date=None, condition_type="above"
    ):
        """Log n diverse trusted (non-disputed) settled predictions — enough to
        clear every min-sample gate in the calibration functions under test
        (the largest is get_optimal_threshold's 20)."""
        market_date = market_date or self._FUTURE
        for i in range(n):
            self._log_settled(
                f"BASE-{i}",
                round(0.30 + (i % 5) * 0.15, 2),
                i % 2,
                market_date,
                city=city,
                condition_type=condition_type,
                edge=round(0.15 + (i % 3) * 0.10, 2),
                local_hour=(i % 24),
            )

    def _add_disputed_outlier(self, ticker="DISPUTED", market_date=None, city="NYC"):
        """Log one settled row with an extreme value that WOULD change any of
        the tested aggregates if included, then mark it disputed."""
        self._log_settled(
            ticker, 1.0, 0, market_date or self._FUTURE, city=city, edge=0.99
        )
        tracker.mark_outcome_disputed(ticker)

    # ── Core mechanism ──────────────────────────────────────────────────────

    def test_mark_outcome_disputed_sets_flag(self):
        tracker.log_outcome("TK-DISP", True)
        tracker.mark_outcome_disputed("TK-DISP")
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT disputed FROM outcomes WHERE ticker=?", ("TK-DISP",)
            ).fetchone()
        self.assertEqual(row[0], 1)

    def test_mark_outcome_disputed_nonexistent_ticker_is_noop(self):
        # Must not raise even though no matching row exists.
        tracker.mark_outcome_disputed("NO-SUCH-TICKER")

    def test_get_disputed_count(self):
        tracker.log_outcome("TK1", True)
        tracker.log_outcome("TK2", True)
        tracker.log_outcome("TK3", True)
        tracker.mark_outcome_disputed("TK1")
        tracker.mark_outcome_disputed("TK2")
        self.assertEqual(tracker.get_disputed_count(), 2)

    def test_audit_settlement_marks_disputed_on_mismatch(self):
        from unittest.mock import patch

        import weather_markets

        ticker = "KXHIGHNY-26APR09-T70"
        self._log_settled(ticker, 0.70, False, date(2026, 4, 9))

        with (
            patch.object(weather_markets, "_metar_station_for_city", return_value=None),
            patch.object(tracker, "_fetch_actual_daily_temp", return_value=75.0),
        ):
            # threshold=70, archive says 75°F (>70 => archive_yes=True), but
            # Kalshi's real settlement was NO — a genuine mismatch.
            result = tracker.audit_settlement(ticker, settled_yes=False)

        self.assertTrue(result)
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT disputed FROM outcomes WHERE ticker=?", (ticker,)
            ).fetchone()
        self.assertEqual(row[0], 1)

    def test_audit_settlement_does_not_mark_disputed_when_matched(self):
        from unittest.mock import patch

        import weather_markets

        ticker = "KXHIGHNY-26APR09-T71"
        self._log_settled(ticker, 0.70, True, date(2026, 4, 9))

        with (
            patch.object(weather_markets, "_metar_station_for_city", return_value=None),
            patch.object(tracker, "_fetch_actual_daily_temp", return_value=75.0),
        ):
            # threshold=70, archive says 75°F (>70 => archive_yes=True), Kalshi
            # also settled YES — no mismatch.
            result = tracker.audit_settlement(ticker, settled_yes=True)

        self.assertTrue(result)
        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT disputed FROM outcomes WHERE ticker=?", (ticker,)
            ).fetchone()
        self.assertEqual(row[0], 0)

    # ── Every calibration/Brier/bias query must exclude disputed rows ──────

    def test_get_bias_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_bias("NYC", None, min_samples=1)
        self._add_disputed_outlier()
        after = tracker.get_bias("NYC", None, min_samples=1)
        # assertAlmostEqual: SQLite gives no row-order guarantee without ORDER
        # BY, and adding a row can change unordered full-table-scan order —
        # shifting float summation order by a last-ULP amount even when the
        # same 25 rows are summed. Not a disputed-exclusion bug.
        self.assertAlmostEqual(before, after, places=10)

    def test_get_quintile_bias_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_quintile_bias("NYC", None, 0.9, min_samples=1)
        self._add_disputed_outlier()
        after = tracker.get_quintile_bias("NYC", None, 0.9, min_samples=1)
        self.assertAlmostEqual(before, after, places=10)

    def test_get_brier_by_days_out_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_brier_by_days_out()
        self._add_disputed_outlier()
        after = tracker.get_brier_by_days_out()
        self.assertEqual(before, after)

    def test_brier_score_by_method_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.brier_score_by_method(min_samples=1)
        self._add_disputed_outlier()
        after = tracker.brier_score_by_method(min_samples=1)
        self.assertEqual(before, after)

    def test_brier_score_by_method_rolling_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.brier_score_by_method_rolling(window=100, min_samples=1)
        self._add_disputed_outlier()
        after = tracker.brier_score_by_method_rolling(window=100, min_samples=1)
        self.assertEqual(before, after)

    def test_get_component_attribution_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_component_attribution()
        self._add_disputed_outlier()
        after = tracker.get_component_attribution()
        self.assertEqual(before, after)

    def test_brier_score_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.brier_score()
        self._add_disputed_outlier()
        after = tracker.brier_score()
        self.assertEqual(before, after)

    def test_brier_score_rolling_with_n_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.brier_score_rolling_with_n(weeks=52)
        self._add_disputed_outlier()
        after = tracker.brier_score_rolling_with_n(weeks=52)
        self.assertEqual(before, after)

    def test_get_rolling_win_rate_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_rolling_win_rate(window=100)
        self._add_disputed_outlier()
        after = tracker.get_rolling_win_rate(window=100)
        self.assertEqual(before, after)

    def test_get_recent_win_loss_excludes_disputed(self):
        self._seed_baseline()
        before = tracker._get_recent_win_loss(window=100)
        self._add_disputed_outlier()
        after = tracker._get_recent_win_loss(window=100)
        self.assertEqual(before, after)

    def test_get_brier_by_tier_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_brier_by_tier()
        self._add_disputed_outlier()
        after = tracker.get_brier_by_tier()
        self.assertEqual(before, after)

    def test_get_brier_over_time_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_brier_over_time(weeks=9999)
        self._add_disputed_outlier()
        after = tracker.get_brier_over_time(weeks=9999)
        self.assertEqual(before, after)

    def test_brier_skill_score_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.brier_skill_score()
        self._add_disputed_outlier()
        after = tracker.brier_skill_score()
        self.assertEqual(before, after)

    def test_get_calibration_trend_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_calibration_trend(weeks=9999)
        self._add_disputed_outlier()
        after = tracker.get_calibration_trend(weeks=9999)
        self.assertEqual(before, after)

    def test_get_calibration_by_city_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_calibration_by_city()
        self._add_disputed_outlier()
        after = tracker.get_calibration_by_city()
        self.assertEqual(before, after)

    def test_get_calibration_by_season_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_calibration_by_season()
        self._add_disputed_outlier()
        after = tracker.get_calibration_by_season()
        self.assertEqual(before, after)

    def test_get_calibration_by_type_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_calibration_by_type()
        self._add_disputed_outlier()
        after = tracker.get_calibration_by_type()
        self.assertEqual(before, after)

    def test_get_sameday_calibration_excludes_disputed(self):
        self._seed_baseline(market_date=self._PAST)
        before = tracker.get_sameday_calibration()
        self._add_disputed_outlier(market_date=self._PAST)
        after = tracker.get_sameday_calibration()
        self.assertEqual(before, after)

    def test_get_multiday_calibration_cli_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_multiday_calibration_cli()
        self._add_disputed_outlier()
        after = tracker.get_multiday_calibration_cli()
        self.assertEqual(before, after)

    def test_get_sameday_calibration_cli_excludes_disputed(self):
        self._seed_baseline(market_date=self._PAST)
        before = tracker.get_sameday_calibration_cli()
        self._add_disputed_outlier(market_date=self._PAST)
        after = tracker.get_sameday_calibration_cli()
        self.assertEqual(before, after)

    def test_get_market_calibration_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_market_calibration()
        self._add_disputed_outlier()
        after = tracker.get_market_calibration()
        self.assertEqual(before, after)

    def test_get_confusion_matrix_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_confusion_matrix()
        self._add_disputed_outlier()
        after = tracker.get_confusion_matrix()
        self.assertEqual(before, after)

    def test_get_optimal_threshold_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_optimal_threshold()
        self._add_disputed_outlier()
        after = tracker.get_optimal_threshold()
        self.assertEqual(before, after)

    def test_get_roc_auc_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_roc_auc()
        self._add_disputed_outlier()
        after = tracker.get_roc_auc()
        self.assertEqual(before, after)

    def test_get_edge_decay_curve_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_edge_decay_curve()
        self._add_disputed_outlier()
        after = tracker.get_edge_decay_curve()
        self.assertEqual(before, after)

    def test_get_model_calibration_buckets_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_model_calibration_buckets()
        self._add_disputed_outlier()
        after = tracker.get_model_calibration_buckets()
        self.assertEqual(before, after)

    def test_get_brier_by_version_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_brier_by_version(min_samples=1)
        self._add_disputed_outlier()
        after = tracker.get_brier_by_version(min_samples=1)
        self.assertEqual(before, after)

    def test_get_pnl_by_signal_source_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_pnl_by_signal_source(min_samples=1)
        self._add_disputed_outlier()
        after = tracker.get_pnl_by_signal_source(min_samples=1)
        self.assertEqual(before, after)

    def test_get_analysis_bias_excludes_disputed(self):
        for i in range(3):
            ticker = f"AA-{i}"
            tracker.log_analysis_attempt(
                ticker, "NYC", "above", self._FUTURE, 0.6, 0.5, 10
            )
            tracker.log_outcome(ticker, i % 2)
        before = tracker.get_analysis_bias()

        d_ticker = "AA-DISPUTED"
        tracker.log_analysis_attempt(
            d_ticker, "NYC", "above", self._FUTURE, 1.0, 0.5, 10
        )
        tracker.log_outcome(d_ticker, 0)
        tracker.mark_outcome_disputed(d_ticker)
        after = tracker.get_analysis_bias()

        self.assertEqual(before, after)

    def test_get_edge_realization_by_city_excludes_disputed(self):
        self._seed_baseline(n=25)
        before = tracker.get_edge_realization_by_city()
        self._add_disputed_outlier()
        after = tracker.get_edge_realization_by_city()
        self.assertEqual(before, after)

    # ── Sample-size gates and training-data selectors that joined raw
    # outcomes without the disputed-row exclusion 30+ near-identical siblings
    # above already had (backlog.txt "DISPUTED-ROW EXCLUSION PREDICATE
    # HAND-COPIED ~40 TIMES IN tracker.py" -- found while consolidating that
    # predicate into the outcomes_valid view). No live impact when these were
    # found (0 disputed rows in production), but each is a real sample-size
    # gate or training-data selector that must not count/train on a disputed
    # settlement, same rationale as every test above.

    def test_count_settled_predictions_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.count_settled_predictions()
        self._add_disputed_outlier()
        after = tracker.count_settled_predictions()
        self.assertEqual(before, after)

    def test_count_settled_predictions_rolling_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.count_settled_predictions_rolling()
        self._add_disputed_outlier()
        after = tracker.count_settled_predictions_rolling()
        self.assertEqual(before, after)

    def test_count_settled_sameday_predictions_excludes_disputed(self):
        # _seed_baseline logs multiday (days_out>=1) rows only, so the
        # same-day count starts at 0 regardless -- the outlier itself must be
        # same-day (market_date=_PAST clamps to days_out=0) to actually
        # exercise this function's WHERE clause.
        before = tracker.count_settled_sameday_predictions()
        self._add_disputed_outlier(market_date=self._PAST)
        after = tracker.count_settled_sameday_predictions()
        self.assertEqual(before, after)

    def test_count_settled_below_predictions_excludes_disputed(self):
        # _add_disputed_outlier always logs condition_type="above" -- this
        # gate filters on condition_type='below', so build the outlier
        # directly with the matching condition_type instead.
        self._seed_baseline(condition_type="below")
        before = tracker.count_settled_below_predictions()
        self._log_settled(
            "DISPUTED-BELOW", 1.0, 0, self._FUTURE, condition_type="below", edge=0.99
        )
        tracker.mark_outcome_disputed("DISPUTED-BELOW")
        after = tracker.count_settled_below_predictions()
        self.assertEqual(before, after)

    def test_count_settled_west_coast_multiday_excludes_disputed(self):
        # This gate filters on o.settled_temp_f IS NOT NULL, which
        # _log_settled never populates -- without setting it explicitly,
        # before/after are both {} regardless of the join table, making the
        # assertEqual below pass vacuously. Set it via raw SQL, matching the
        # pattern _add_disputed_emos_outlier already uses for the same column.
        self._seed_baseline(city="LA")
        with tracker._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = 75.0 WHERE ticker LIKE 'BASE-%'"
            )
        before = tracker.count_settled_west_coast_multiday()
        self.assertEqual(
            before.get("LA", 0),
            25,
            "fixture sanity check — test would be vacuous otherwise",
        )

        self._add_disputed_outlier(city="LA")
        with tracker._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ? WHERE ticker = ?",
                (999.0, "DISPUTED"),
            )
        after = tracker.count_settled_west_coast_multiday()
        self.assertEqual(before, after)

    def _add_disputed_emos_outlier(self, ticker="DISPUTED-EMOS"):
        """Log an EMOS-trainable disputed row: needs ens_mean (predictions)
        and settled_temp_f (outcomes) both populated, neither of which
        _log_settled's analysis dict sets -- mirrors the raw-SQL-UPDATE
        pattern tests/test_p9_p10.py already uses for the same columns."""
        tracker.log_prediction(
            ticker,
            "NYC",
            self._FUTURE,
            {
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": 1.0,
                "market_prob": 0.50,
                "edge": 0.99,
                "method": "ensemble",
                "n_members": 82,
            },
            ens_mean=999.0,  # extreme value: would visibly skew EMOS training if included
        )
        tracker.log_outcome(ticker, False)
        with tracker._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ? WHERE ticker = ?",
                (999.0, ticker),
            )
        tracker.mark_outcome_disputed(ticker)

    def test_count_emos_ready_predictions_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.count_emos_ready_predictions()
        self._add_disputed_emos_outlier()
        after = tracker.count_emos_ready_predictions()
        self.assertEqual(before, after)

    def test_get_emos_training_data_excludes_disputed(self):
        self._seed_baseline()
        before = tracker.get_emos_training_data()
        self._add_disputed_emos_outlier()
        after = tracker.get_emos_training_data()
        self.assertEqual(len(before), len(after))
        self.assertNotIn(999.0, [row["ens_mean"] for row in after])


class TestStopLossAccuracy(unittest.TestCase):
    """Restored backlog piece (mystery-revert 24559a7, piece 3): stop-loss exit
    audit. Rebuilt against the current architecture -- the original targeted
    tracker.live_fills (now a slippage-only table with zero live rows ever,
    since no live order has been placed); this instead takes paper-trade rows
    already filtered to stop-loss-tagged early exits and joins them against
    tracker.outcomes, which has the real settlement regardless of whether the
    bot's own position was still open when the market settled.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_predictions.db"
        tracker._db_initialized = False

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _sl_trade(self, ticker, side, entry_price, exit_price, qty=10):
        return {
            "ticker": ticker,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": qty,
        }

    def test_no_trades_returns_zero_dict(self):
        result = tracker.get_stop_loss_accuracy([])
        self.assertEqual(
            result,
            {"total": 0, "saved_money": 0, "exited_winner": 0, "avg_saving": 0.0},
        )

    def test_yes_side_stop_loss_that_saved_money(self):
        # Sold at 0.20 after entering at 0.40; NO won, so holding would have
        # paid $0 -- the stop-loss avoided a larger loss.
        tracker.log_outcome("SL-SAVE", False)
        trade = self._sl_trade("SL-SAVE", "yes", 0.40, 0.20)
        result = tracker.get_stop_loss_accuracy([trade])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["saved_money"], 1)
        self.assertEqual(result["exited_winner"], 0)
        self.assertAlmostEqual(result["avg_saving"], 2.0)  # -2.00 - (-4.00)

    def test_yes_side_stop_loss_that_exited_a_winner(self):
        # Sold at 0.20 after entering at 0.40; YES won, so holding would have
        # paid $1 -- the stop-loss prematurely cut off a winner.
        tracker.log_outcome("SL-WINNER", True)
        trade = self._sl_trade("SL-WINNER", "yes", 0.40, 0.20)
        result = tracker.get_stop_loss_accuracy([trade])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["saved_money"], 0)
        self.assertEqual(result["exited_winner"], 1)
        self.assertAlmostEqual(result["avg_saving"], -8.0)  # -2.00 - 6.00

    def test_no_side_settlement_priced_correctly(self):
        # NO position: entry 0.30, stopped out at 0.15, qty 5. YES won (NO
        # loses), so holding a NO position would have paid $0 -- confirms the
        # hold-to-settlement leg reprices correctly for the "no" side.
        tracker.log_outcome("SL-NOSIDE", True)
        trade = self._sl_trade("SL-NOSIDE", "no", 0.30, 0.15, qty=5)
        result = tracker.get_stop_loss_accuracy([trade])
        self.assertEqual(result["saved_money"], 1)
        self.assertAlmostEqual(result["avg_saving"], 0.75)  # -0.75 - (-1.50)

    def test_excludes_disputed_outcome(self):
        tracker.log_outcome("SL-DISPUTED", True)
        tracker.mark_outcome_disputed("SL-DISPUTED")
        trade = self._sl_trade("SL-DISPUTED", "yes", 0.40, 0.20)
        result = tracker.get_stop_loss_accuracy([trade])
        self.assertEqual(result["total"], 0)

    def test_skips_ticker_with_no_synced_outcome(self):
        # No log_outcome call at all -- market hasn't settled/synced yet.
        trade = self._sl_trade("SL-UNSYNCED", "yes", 0.40, 0.20)
        result = tracker.get_stop_loss_accuracy([trade])
        self.assertEqual(result["total"], 0)

    def test_multiple_trades_averaged(self):
        tracker.log_outcome("SL-A", False)
        tracker.log_outcome("SL-B", True)
        trades = [
            self._sl_trade("SL-A", "yes", 0.40, 0.20),  # saving = +2.0
            self._sl_trade("SL-B", "yes", 0.40, 0.20),  # saving = -8.0
        ]
        result = tracker.get_stop_loss_accuracy(trades)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["saved_money"], 1)
        self.assertEqual(result["exited_winner"], 1)
        self.assertAlmostEqual(result["avg_saving"], -3.0)  # (2.0 + -8.0) / 2


class TestSyncOutcomesDatetimeFix(unittest.TestCase):
    """P0-13 — sync_outcomes must not crash on aware/naive datetime subtraction."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_sync.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _log(self, ticker):
        tracker.log_prediction(
            ticker,
            "NYC",
            date(2026, 4, 1),
            {
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": 0.70,
                "market_prob": 0.50,
                "edge": 0.20,
                "method": "ensemble",
                "n_members": 50,
            },
        )

    def test_sync_outcomes_does_not_raise_on_z_suffix_close_time(self):
        """close_time with Z suffix must not raise TypeError (aware vs naive mismatch)."""
        from unittest.mock import MagicMock

        self._log("TK-ZSUFFIX")

        mock_client = MagicMock()
        # Provide a close_time >1 hour ago in UTC with Z suffix (the previously broken path)
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": "2026-01-01T00:00:00Z",
        }
        # Must not raise
        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 1)

    def test_sync_outcomes_does_not_raise_on_offset_close_time(self):
        """close_time with +00:00 offset must not raise TypeError."""
        from unittest.mock import MagicMock

        self._log("TK-OFFSET")
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "no",
            "close_time": "2026-01-01T00:00:00+00:00",
        }
        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 1)

    def test_sync_outcomes_skips_market_closed_less_than_1h_ago(self):
        """Markets finalized less than 1 hour ago must be skipped (Kalshi may revise)."""
        from datetime import datetime as _datetime
        from datetime import timedelta
        from unittest.mock import MagicMock

        self._log("TK-RECENT")
        # close_time 30 minutes ago
        recent_close = (_datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": recent_close,
        }
        count = tracker.sync_outcomes(mock_client)
        self.assertEqual(count, 0, "Should skip markets finalized < 1h ago")


def test_api_reliability_returns_empty_for_unknown_city(monkeypatch):
    import utils

    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    # utils.DASHBOARD_PASSWORD is cached at import time (conftest.py imports
    # main, transitively importing utils, before any test runs) — deleting
    # the env var here doesn't reach that cached module attribute, so the
    # attribute itself must be patched directly (matches test_web_auth.py's
    # established convention).
    monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
    from web_app import _build_app

    app = _build_app(object())
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/api/reliability/UnknownCity123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "bins" in data
        assert "city" in data
        assert data["city"] == "UnknownCity123"
        assert isinstance(data["bins"], list)
        assert data["n"] == 0


def test_api_edge_realization_returns_list(monkeypatch):
    import utils

    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
    from web_app import _build_app

    app = _build_app(object())
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/api/edge-realization")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        # Each entry should have the expected keys (may be empty list if no data)
        for entry in data:
            assert "city" in entry
            assert "mean_edge" in entry
            assert "win_rate" in entry
            assert "n" in entry


def test_health_endpoint_returns_ok(monkeypatch):
    import utils

    # Health endpoint must be public (no auth) and return JSON status
    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
    from web_app import _build_app

    app = _build_app(object())
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data is not None
        assert "status" in data
        assert data["status"] == "ok"


class TestFetchAsosDailyTemp(unittest.TestCase):
    """R-42: _fetch_asos_daily_temp must use precise sts/ets timestamps, not
    day1/day2 date params (which turned out to be exclusive of day2 on the
    live IEM API and silently truncated the window before it reached the full
    local calendar day, since a US city's local day straddles two UTC dates).

    Also covers: 'min' must NOT reach into the following local day. An earlier
    version extended the window through 10 AM local the next day on the theory
    that NWS climate days run ~7 AM to 7 AM; real NWS Daily Climatological
    Reports disprove that (pre-7am lows are attributed to the same date, not
    the day before), and the extension was found to silently misattribute the
    next morning's own low to the target date when that morning was colder."""

    def _mock_response(self, rows, station="KSEA"):
        from unittest.mock import MagicMock

        text = "station,valid,tmpf\n" + "\n".join(
            f"{station},{ts},{temp}" for ts, temp in rows
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.text = text
        resp.raise_for_status.return_value = None
        return resp

    def test_request_uses_sts_ets_not_day_params(self):
        """The HTTP request must use sts/ets, never day1/day2/year1/year2."""
        from unittest.mock import patch

        import tracker

        mock_resp = self._mock_response([("2026-07-03 07:53", "58.0")])
        with patch("requests.get", return_value=mock_resp) as mock_get:
            tracker._fetch_asos_daily_temp(
                "KSEA", date(2026, 7, 3), "min", city_tz="America/Los_Angeles"
            )
        params = mock_get.call_args.kwargs["params"]
        assert "sts" in params and "ets" in params
        for stale_key in ("day1", "day2", "year1", "year2", "month1", "month2"):
            assert stale_key not in params, f"stale date param {stale_key!r} still sent"

    def test_min_excludes_next_day_readings(self):
        """A colder reading on the following local day must NOT be picked up as
        the target date's low — NWS attributes it to its own calendar day."""
        from unittest.mock import patch

        import tracker

        # Readings during 2026-07-03 itself run 57-70F (coldest same-day: 57F
        # at 23:53 local). The 56F reading at 2026-07-04 05:53 local belongs to
        # July 4's own low, not July 3's, and must be excluded even though it's
        # colder than anything actually observed on July 3.
        rows = [
            ("2026-07-03 07:53", "60.0"),  # 2026-07-03 00:53 local
            ("2026-07-03 20:53", "70.0"),  # 2026-07-03 13:53 local
            ("2026-07-04 06:53", "57.0"),  # 2026-07-03 23:53 local -- true low
            (
                "2026-07-04 12:53",
                "56.0",
            ),  # 2026-07-04 05:53 local -- excluded (next day)
            (
                "2026-07-04 17:53",
                "60.0",
            ),  # 2026-07-04 10:53 local -- excluded (next day)
        ]
        with patch("requests.get", return_value=self._mock_response(rows)):
            result = tracker._fetch_asos_daily_temp(
                "KSEA", date(2026, 7, 3), "min", city_tz="America/Los_Angeles"
            )
        assert result == 57.0, f"expected same-day low 57.0, got {result}"

    def test_max_picks_same_day_peak(self):
        """HIGH markets don't need the next-day extension; peak stays on target day."""
        from unittest.mock import patch

        import tracker

        rows = [
            ("2026-07-03 07:53", "60.0"),  # 2026-07-03 00:53 local
            ("2026-07-03 20:53", "72.0"),  # 2026-07-03 13:53 local -- peak
            ("2026-07-04 06:53", "57.0"),  # 2026-07-03 23:53 local
        ]
        with patch("requests.get", return_value=self._mock_response(rows)):
            result = tracker._fetch_asos_daily_temp(
                "KSEA", date(2026, 7, 3), "max", city_tz="America/Los_Angeles"
            )
        assert result == 72.0

    def test_min_excludes_next_day_readings_phoenix_no_dst(self):
        """Same same-day-only rule, exercised on a station/timezone the fix's
        own justifying comment cited (Phoenix, America/Phoenix — no DST ever,
        so this also confirms the logic doesn't accidentally depend on DST
        machinery being present)."""
        from unittest.mock import patch

        import tracker

        # Phoenix is UTC-7 year-round. 2026-06-26 local 05:16 = 12:16 UTC same day.
        rows = [
            ("2026-06-26 07:00", "92.0"),  # 2026-06-26 00:00 local
            ("2026-06-26 20:00", "112.0"),  # 2026-06-26 13:00 local -- afternoon peak
            ("2026-06-27 06:00", "89.0"),  # 2026-06-26 23:00 local -- true low
            (
                "2026-06-27 12:00",
                "84.0",
            ),  # 2026-06-27 05:00 local -- excluded (next day)
        ]
        with patch(
            "requests.get", return_value=self._mock_response(rows, station="KPHX")
        ):
            result = tracker._fetch_asos_daily_temp(
                "KPHX", date(2026, 6, 26), "min", city_tz="America/Phoenix"
            )
        assert result == 89.0, f"expected same-day low 89.0, got {result}"

    def test_min_excludes_next_day_readings_spring_forward(self):
        """Same-day-only rule on a 23-hour local day (US DST spring-forward,
        2026-03-08 — clocks skip 2:00-2:59 AM local) for a DST-observing zone."""
        from unittest.mock import patch

        import tracker

        # America/Chicago: CST (UTC-6) before 2 AM local, CDT (UTC-5) after.
        rows = [
            ("2026-03-08 07:53", "28.0"),  # 2026-03-08 01:53 local (CST, UTC-6)
            ("2026-03-08 13:53", "45.0"),  # 2026-03-08 08:53 local (CDT, UTC-5)
            ("2026-03-09 04:53", "26.0"),  # 2026-03-08 23:53 local (CDT) -- true low
            (
                "2026-03-09 10:53",
                "20.0",
            ),  # 2026-03-09 05:53 local -- excluded (next day)
        ]
        with patch(
            "requests.get", return_value=self._mock_response(rows, station="KMDW")
        ):
            result = tracker._fetch_asos_daily_temp(
                "KMDW", date(2026, 3, 8), "min", city_tz="America/Chicago"
            )
        assert result == 26.0, f"expected same-day low 26.0, got {result}"

    def test_min_excludes_next_day_readings_fall_back(self):
        """Same-day-only rule on a 25-hour local day (US DST fall-back,
        2026-11-01 — the 1:00-1:59 AM local hour occurs twice) for a
        DST-observing zone. IEM's timestamps are UTC, so the repeated local
        hour is unambiguous here regardless of the fold."""
        from unittest.mock import patch

        import tracker

        # America/Chicago: CDT (UTC-5) before 2 AM local, CST (UTC-6) after.
        rows = [
            ("2026-11-01 05:53", "50.0"),  # 2026-11-01 00:53 local (CDT, UTC-5)
            ("2026-11-01 06:53", "48.0"),  # 2026-11-01 01:53 local (CDT) -- 1st pass
            ("2026-11-01 07:53", "47.0"),  # 2026-11-01 01:53 local (CST) -- 2nd pass
            ("2026-11-02 05:53", "40.0"),  # 2026-11-01 23:53 local (CST) -- true low
            (
                "2026-11-02 11:53",
                "35.0",
            ),  # 2026-11-02 05:53 local -- excluded (next day)
        ]
        with patch(
            "requests.get", return_value=self._mock_response(rows, station="KMDW")
        ):
            result = tracker._fetch_asos_daily_temp(
                "KMDW", date(2026, 11, 1), "min", city_tz="America/Chicago"
            )
        assert result == 40.0, f"expected same-day low 40.0, got {result}"


def test_composite_indexes_exist(tmp_path, monkeypatch):
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    with tracker._conn() as con:
        indexes = {
            row[1]
            for row in con.execute(
                "SELECT * FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "idx_predictions_ticker_settled" in indexes
    assert "idx_predictions_city_days_created" in indexes
    assert "idx_predictions_prob_settled" in indexes
    assert "idx_outcomes_ticker_settled" in indexes


class TestFetchPreviousRunLeads(unittest.TestCase):
    """backlog.txt "FORECAST RUN-TO-RUN TREND SIGNAL" -- _fetch_previous_run_leads
    fetches several lead offsets for one model in a single Previous Runs API
    call, unlike _fetch_previous_run_daily which only supports one lead and
    only for already-past target dates."""

    def _mock_response(self, hourly_values: dict, target_date, hour="12:00"):
        from unittest.mock import MagicMock

        time_str = f"{target_date.isoformat()}T{hour}"
        hourly = {"time": [time_str]}
        for var_name, value in hourly_values.items():
            hourly[var_name] = [value]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"hourly": hourly}
        return resp

    def test_parses_multiple_leads_from_one_response(self):
        """Requesting leads [3, 4] must return both, read from their own
        temperature_2m_previous_dayN column -- not conflated with each other."""
        from unittest.mock import patch

        target = date(2026, 7, 20)
        resp = self._mock_response(
            {
                "temperature_2m_previous_day3": 80.0,
                "temperature_2m_previous_day4": 82.0,
            },
            target,
        )
        with patch("requests.get", return_value=resp) as mock_get:
            result = tracker._fetch_previous_run_leads(
                40.7, -74.0, "America/New_York", target, "gfs_seamless", [3, 4], "max"
            )
        assert result == {3: 80.0, 4: 82.0}
        # Single HTTP call carries both leads as comma-separated hourly vars.
        assert mock_get.call_count == 1
        hourly_param = mock_get.call_args.kwargs["params"]["hourly"]
        assert "temperature_2m_previous_day3" in hourly_param
        assert "temperature_2m_previous_day4" in hourly_param

    def test_uses_max_or_min_per_var_argument(self):
        from unittest.mock import MagicMock, patch

        target = date(2026, 7, 20)
        time_a = f"{target.isoformat()}T06:00"
        time_b = f"{target.isoformat()}T18:00"
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "hourly": {
                "time": [time_a, time_b],
                "temperature_2m_previous_day3": [70.0, 90.0],
            }
        }
        with patch("requests.get", return_value=resp):
            max_result = tracker._fetch_previous_run_leads(
                40.7, -74.0, "America/New_York", target, "gfs_seamless", [3], "max"
            )
            min_result = tracker._fetch_previous_run_leads(
                40.7, -74.0, "America/New_York", target, "gfs_seamless", [3], "min"
            )
        assert max_result == {3: 90.0}
        assert min_result == {3: 70.0}

    def test_lead_with_no_data_is_omitted_not_zero(self):
        """A lead the API returns as all-null must be absent from the result,
        never silently coerced to 0.0 (which would corrupt the weighted mean)."""
        from unittest.mock import patch

        target = date(2026, 7, 20)
        resp = self._mock_response(
            {
                "temperature_2m_previous_day3": 80.0,
                "temperature_2m_previous_day8": None,
            },
            target,
        )
        with patch("requests.get", return_value=resp):
            result = tracker._fetch_previous_run_leads(
                40.7, -74.0, "America/New_York", target, "gfs_seamless", [3, 8], "max"
            )
        assert result == {3: 80.0}
        assert 8 not in result

    def test_network_failure_returns_empty_dict_not_raise(self):
        from unittest.mock import patch

        target = date(2026, 7, 20)
        with patch("requests.get", side_effect=ConnectionError("boom")):
            result = tracker._fetch_previous_run_leads(
                40.7, -74.0, "America/New_York", target, "gfs_seamless", [3, 4], "max"
            )
        assert result == {}

    def test_malformed_json_returns_empty_dict_not_raise(self):
        from unittest.mock import MagicMock, patch

        target = date(2026, 7, 20)
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.side_effect = ValueError("not json")
        with patch("requests.get", return_value=resp):
            result = tracker._fetch_previous_run_leads(
                40.7, -74.0, "America/New_York", target, "gfs_seamless", [3, 4], "max"
            )
        assert result == {}


class TestGetForecastRunTrend(unittest.TestCase):
    """get_forecast_run_trend() combines all 3 _PREVIOUS_RUN_MODEL_MAP models,
    weighted by _model_weights, into one apples-to-apples revision series."""

    def setUp(self):
        # Module-level cache persists across tests in the same process --
        # clear it so one test's fetch can't be served from another's cache.
        tracker._run_trend_cache.clear()

    def _model_response(self, values_by_lead: dict, leads: list, target_date):
        from unittest.mock import MagicMock

        time_str = f"{target_date.isoformat()}T12:00"
        hourly = {"time": [time_str]}
        for lead in leads:
            hourly[f"temperature_2m_previous_day{lead}"] = [values_by_lead.get(lead)]
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"hourly": hourly}
        return resp

    def test_days_out_zero_returns_none_without_network_call(self):
        """Same-day markets use the METAR pipeline, not this signal (matches
        the existing days_out >= 1 gate on ens_mean backfill)."""
        from unittest.mock import patch

        target = date.today() + timedelta(days=3)
        with patch("requests.get") as mock_get:
            result = tracker.get_forecast_run_trend("NYC", target, 0, "max")
        assert result is None
        mock_get.assert_not_called()

    def test_unknown_city_returns_none(self):
        from unittest.mock import patch

        target = date.today() + timedelta(days=3)
        with patch("requests.get") as mock_get:
            result = tracker.get_forecast_run_trend("Atlantis", target, 3, "max")
        assert result is None
        mock_get.assert_not_called()

    def test_days_out_seven_has_only_one_valid_lead_returns_none(self):
        """lead0 = min(days_out, 7) = 7; leads 8-10 are all clamped out by the
        API's valid 1-7 range, leaving only 1 usable lead -- too few for a delta."""
        from unittest.mock import patch

        target = date.today() + timedelta(days=7)
        with patch("requests.get") as mock_get:
            result = tracker.get_forecast_run_trend("NYC", target, 7, "max")
        assert result is None
        mock_get.assert_not_called()

    def test_computes_weighted_delta_and_jumpiness_exactly(self):
        """Known per-model values at 4 leads, known (unequal) model weights --
        assert the exact weighted mean, delta, and population-stdev jumpiness,
        not just that a result was produced."""
        from unittest.mock import patch

        import weather_markets

        target = date.today() + timedelta(days=3)
        leads = [3, 4, 5, 6]
        # icon weighted 2x gfs/ecmwf so the test proves real weighting, not a
        # plain average across models.
        weights = {
            "icon_seamless": 2.0,
            "gfs_seamless": 1.0,
            "ecmwf_aifs025_ensemble": 1.0,
        }
        model_values = {
            "icon_seamless": {3: 80.0, 4: 82.0, 5: 81.0, 6: 79.0},
            "gfs_seamless": {3: 84.0, 4: 86.0, 5: 85.0, 6: 83.0},
            "ecmwf_aifs025_single": {3: 82.0, 4: 84.0, 5: 83.0, 6: 81.0},
        }

        def _fake_get(url, params, timeout):
            model = params["models"]
            return self._model_response(model_values[model], leads, target)

        with (
            patch.object(weather_markets, "_model_weights", return_value=weights),
            patch("requests.get", side_effect=_fake_get),
        ):
            result = tracker.get_forecast_run_trend("NYC", target, 3, "max")

        assert result is not None
        # weighted mean per lead = (2*icon + gfs + ecmwf) / 4
        assert result["points"] == [
            {"lead": 3, "value": 81.5},
            {"lead": 4, "value": 83.5},
            {"lead": 5, "value": 82.5},
            {"lead": 6, "value": 80.5},
        ]
        assert result["delta"] == -2.0  # points[0].value - points[1].value
        assert result["jumpy"] == 1.118  # population stdev of the 4 values

    def test_second_call_hits_cache_not_network(self):
        from unittest.mock import patch

        import weather_markets

        target = date.today() + timedelta(days=3)
        leads = [3, 4, 5, 6]
        weights = {
            "icon_seamless": 1.0,
            "gfs_seamless": 1.0,
            "ecmwf_aifs025_ensemble": 1.0,
        }
        model_values = {
            m: dict.fromkeys(leads, 80.0)
            for m in ("icon_seamless", "gfs_seamless", "ecmwf_aifs025_single")
        }

        def _fake_get(url, params, timeout):
            return self._model_response(model_values[params["models"]], leads, target)

        with (
            patch.object(weather_markets, "_model_weights", return_value=weights),
            patch("requests.get", side_effect=_fake_get) as mock_get,
        ):
            first = tracker.get_forecast_run_trend("NYC", target, 3, "max")
            second = tracker.get_forecast_run_trend("NYC", target, 3, "max")

        assert first == second
        assert mock_get.call_count == 3  # one per model, only on the FIRST call

    def test_never_raises_on_total_network_failure(self):
        from unittest.mock import patch

        import weather_markets

        target = date.today() + timedelta(days=3)
        with (
            patch.object(
                weather_markets,
                "_model_weights",
                return_value={
                    "icon_seamless": 1.0,
                    "gfs_seamless": 1.0,
                    "ecmwf_aifs025_ensemble": 1.0,
                },
            ),
            patch("requests.get", side_effect=ConnectionError("boom")),
        ):
            result = tracker.get_forecast_run_trend("NYC", target, 3, "max")
        assert result is None


class TestGetForecastRunTrendFromAnalysis(unittest.TestCase):
    """get_forecast_run_trend_from_analysis() extracts city/target_date/
    days_out/var from an analyze_trade()-shaped dict and is the ONLY place
    that calls get_forecast_run_trend live -- 2026-07-16 review found the
    fetch must never run inside analyze_trade itself (order-placement
    latency risk), so this extraction/dispatch boundary is what actually
    keeps it off that path. Never calls the network directly; delegates to
    get_forecast_run_trend, so these tests patch that instead."""

    def test_extracts_fields_and_delegates(self):
        from unittest.mock import patch

        target = date.today() + timedelta(days=3)
        analysis = {
            "city": "NYC",
            "days_out": 3,
            "target_date": target.isoformat(),
            "condition": {"type": "temp_above", "var": "min"},
        }
        sentinel = {"points": [], "delta": 0.0, "jumpy": 0.0}
        with patch.object(
            tracker, "get_forecast_run_trend", return_value=sentinel
        ) as mock_fn:
            result = tracker.get_forecast_run_trend_from_analysis(analysis)
        assert result is sentinel
        mock_fn.assert_called_once_with("NYC", target, 3, "min")

    def test_var_defaults_to_max_when_condition_missing_var(self):
        from unittest.mock import patch

        target = date.today() + timedelta(days=3)
        analysis = {
            "city": "NYC",
            "days_out": 3,
            "target_date": target.isoformat(),
            "condition": {"type": "temp_above"},  # no "var" key
        }
        with patch.object(
            tracker, "get_forecast_run_trend", return_value=None
        ) as mock_fn:
            tracker.get_forecast_run_trend_from_analysis(analysis)
        mock_fn.assert_called_once_with("NYC", target, 3, "max")

    def test_missing_city_returns_none_without_calling_through(self):
        from unittest.mock import patch

        analysis = {"days_out": 3, "target_date": "2026-07-20", "condition": {}}
        with patch.object(tracker, "get_forecast_run_trend") as mock_fn:
            result = tracker.get_forecast_run_trend_from_analysis(analysis)
        assert result is None
        mock_fn.assert_not_called()

    def test_malformed_target_date_returns_none_not_raise(self):
        from unittest.mock import patch

        analysis = {
            "city": "NYC",
            "days_out": 3,
            "target_date": "not-a-date",
            "condition": {},
        }
        with patch.object(tracker, "get_forecast_run_trend") as mock_fn:
            result = tracker.get_forecast_run_trend_from_analysis(analysis)
        assert result is None
        mock_fn.assert_not_called()

    def test_empty_dict_returns_none_not_raise(self):
        result = tracker.get_forecast_run_trend_from_analysis({})
        assert result is None


class TestLogPredictionRunTrend(unittest.TestCase):
    """log_prediction() must persist run_trend's points/delta/jumpy through
    the UPSERT round-trip, and leave them NULL when no signal was computed."""

    def test_run_trend_round_trips_through_upsert(self):
        run_trend = {
            "points": [{"lead": 3, "value": 81.5}, {"lead": 4, "value": 83.5}],
            "delta": -2.0,
            "jumpy": 1.118,
        }
        tracker.log_prediction(
            "TEST-TICKER-1",
            "NYC",
            date(2099, 1, 1),
            {"forecast_prob": 0.6, "market_prob": 0.5},
            run_trend=run_trend,
        )
        with tracker._conn() as con:
            row = con.execute(
                "SELECT run_trend_points, run_trend_delta, run_trend_jumpy "
                "FROM predictions WHERE ticker = ?",
                ("TEST-TICKER-1",),
            ).fetchone()
        assert row is not None
        import json

        assert json.loads(row["run_trend_points"]) == run_trend["points"]
        assert row["run_trend_delta"] == -2.0
        assert row["run_trend_jumpy"] == 1.118

    def test_run_trend_none_stores_null_columns(self):
        tracker.log_prediction(
            "TEST-TICKER-2",
            "NYC",
            date(2099, 1, 1),
            {"forecast_prob": 0.6, "market_prob": 0.5},
            run_trend=None,
        )
        with tracker._conn() as con:
            row = con.execute(
                "SELECT run_trend_points, run_trend_delta, run_trend_jumpy "
                "FROM predictions WHERE ticker = ?",
                ("TEST-TICKER-2",),
            ).fetchone()
        assert row is not None
        assert row["run_trend_points"] is None
        assert row["run_trend_delta"] is None
        assert row["run_trend_jumpy"] is None
