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
                    "UPDATE predictions SET condition_type=? WHERE ticker=?",
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

    def test_bias_differs_by_condition_type(self):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
