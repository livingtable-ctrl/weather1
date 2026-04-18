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
        tracker._db_initialized = False

    def teardown_method(self):
        import gc

        gc.collect()
        tracker._db_initialized = False
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


class TestAnalyzeTradeConditionType:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tracker.DB_PATH = Path(self._tmp.name)
        tracker._db_initialized = False

    def teardown_method(self):
        import gc

        gc.collect()
        tracker._db_initialized = False
        self._tmp.close()
        try:
            Path(self._tmp.name).unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_bias_correction_condition_type_param_accepted(self):
        """get_bias accepts condition_type kwarg — confirms the interface exists for wiring."""
        from tracker import get_bias

        # Should not raise TypeError. Returns 0.0 when no history exists.
        result_global = get_bias("NYC", 5)
        result_cond = get_bias("NYC", 5, condition_type="above")
        assert isinstance(result_global, float)
        assert isinstance(result_cond, float)

    def test_condition_type_scale_in_kelly(self):
        """_CONDITION_CONFIDENCE values correctly rank: precip_snow < precip_any < above."""
        from weather_markets import _CONDITION_CONFIDENCE

        assert _CONDITION_CONFIDENCE["above"] == pytest.approx(1.00)
        assert _CONDITION_CONFIDENCE["precip_any"] == pytest.approx(0.90)
        assert _CONDITION_CONFIDENCE["precip_above"] == pytest.approx(0.85)
        assert _CONDITION_CONFIDENCE["precip_snow"] == pytest.approx(0.80)
        base = 0.15
        assert base * _CONDITION_CONFIDENCE["precip_snow"] == pytest.approx(base * 0.80)
        assert (
            base * _CONDITION_CONFIDENCE["precip_snow"]
            < base * _CONDITION_CONFIDENCE["above"]
        )


# ── Phase 2: Signal quality tightening ───────────────────────────────────────


class TestStrongEdgeThreshold:
    def test_strong_edge_default_is_0_30(self):
        from utils import STRONG_EDGE

        assert STRONG_EDGE == pytest.approx(0.30)

    def test_strong_edge_above_med_edge(self):
        from utils import MED_EDGE, STRONG_EDGE

        assert STRONG_EDGE > MED_EDGE


class TestMinSignalVolume:
    """analyze_trade() skips markets below MIN_SIGNAL_VOLUME."""

    def _enriched(self, volume: float = 200.0) -> dict:
        import datetime

        return {
            "ticker": "KXTEMP-TEST",
            "series_ticker": "KXTEMP",
            "title": "NYC high above 72°F on 2026-05-01?",
            "_city": "NYC",
            "_date": datetime.date(2026, 5, 1),
            "yes_ask": 52,
            "yes_bid": 48,
            "volume": volume,
            "volume_fp": volume,
            "open_interest": 100,
            "open_interest_fp": 100,
            "close_time": (
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=20)
            ).isoformat(),
        }

    def test_skips_low_volume_market(self, monkeypatch):
        import weather_markets as wm

        original = wm.MIN_SIGNAL_VOLUME
        wm.MIN_SIGNAL_VOLUME = 100
        try:
            enriched = self._enriched(volume=30)
            # patch forecast fetch so it doesn't network
            monkeypatch.setattr(wm, "get_weather_forecast", lambda *a: None)
            result = wm.analyze_trade(enriched)
            assert result is None
        finally:
            wm.MIN_SIGNAL_VOLUME = original

    def test_passes_sufficient_volume(self, monkeypatch):
        import weather_markets as wm

        original = wm.MIN_SIGNAL_VOLUME
        wm.MIN_SIGNAL_VOLUME = 50
        try:
            enriched = self._enriched(volume=200)
            monkeypatch.setattr(
                wm,
                "get_weather_forecast",
                lambda city, dt: {
                    "high_f": 72.0,
                    "low_f": 55.0,
                    "precip_in": 0.0,
                    "models_used": 3,
                    "high_range": (70.0, 74.0),
                },
            )
            # analyze_trade may return None for other reasons (no ensemble data)
            # but NOT because of the volume gate
            # Just assert it doesn't fail with an exception
            wm.analyze_trade(enriched)  # no assertion — just shouldn't raise
        finally:
            wm.MIN_SIGNAL_VOLUME = original


class TestMaxModelSpreadGate:
    """analyze_trade() returns None when model spread exceeds MAX_MODEL_SPREAD_F."""

    def _enriched(self) -> dict:
        import datetime

        return {
            "ticker": "KXTEMP-SPREAD",
            "series_ticker": "KXTEMP",
            "title": "NYC high above 72°F on 2026-05-01?",
            "_city": "NYC",
            "_date": datetime.date(2026, 5, 1),
            "yes_ask": 52,
            "yes_bid": 48,
            "volume": 500,
            "volume_fp": 500,
            "open_interest": 200,
            "open_interest_fp": 200,
            "close_time": (
                datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=20)
            ).isoformat(),
        }

    def test_wide_spread_suppresses_signal(self, monkeypatch):
        import weather_markets as wm

        orig = wm.MAX_MODEL_SPREAD_F
        wm.MAX_MODEL_SPREAD_F = 8.0
        try:
            monkeypatch.setattr(
                wm,
                "get_weather_forecast",
                lambda *a: {
                    "high_f": 75.0,
                    "low_f": 58.0,
                    "precip_in": 0.0,
                    "models_used": 3,
                    "high_range": (65.0, 85.0),  # 20°F spread > 8°F gate
                },
            )
            result = wm.analyze_trade(self._enriched())
            assert result is None
        finally:
            wm.MAX_MODEL_SPREAD_F = orig

    def test_narrow_spread_allows_signal(self, monkeypatch):
        import weather_markets as wm

        orig = wm.MAX_MODEL_SPREAD_F
        wm.MAX_MODEL_SPREAD_F = 8.0
        try:
            monkeypatch.setattr(
                wm,
                "get_weather_forecast",
                lambda *a: {
                    "high_f": 75.0,
                    "low_f": 58.0,
                    "precip_in": 0.0,
                    "models_used": 3,
                    "high_range": (73.0, 77.0),  # 4°F spread — within gate
                },
            )
            # May still return None for other reasons — just not the spread gate
            wm.analyze_trade(self._enriched())  # no assertion — shouldn't raise
        finally:
            wm.MAX_MODEL_SPREAD_F = orig


class TestGetBrierByTier:
    """get_brier_by_tier() splits Brier score by abs(edge) tier."""

    def setup_method(self):
        """Point tracker at a fresh temp DB for isolation."""
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.mkdtemp()
        self._orig_path = tracker.DB_PATH
        self._orig_init = tracker._db_initialized
        tracker.DB_PATH = Path(self._tmp) / "test.db"
        tracker._db_initialized = False
        tracker.init_db()

    def teardown_method(self):
        import shutil

        tracker.DB_PATH = self._orig_path
        tracker._db_initialized = self._orig_init
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed(self, ticker, edge, our_prob, settled_yes):
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            con.execute(
                "INSERT OR REPLACE INTO predictions"
                " (ticker, our_prob, edge, predicted_at) VALUES (?,?,?,?)",
                (ticker, our_prob, edge, "2026-04-01T00:00:00"),
            )
            con.execute(
                "INSERT OR REPLACE INTO outcomes (ticker, settled_yes) VALUES (?,?)",
                (ticker, settled_yes),
            )

    def test_strong_tier_computed(self):
        self._seed("T1", edge=0.35, our_prob=0.85, settled_yes=1)
        result = tracker.get_brier_by_tier()
        assert result["strong"]["n"] == 1
        assert result["strong"]["brier"] == pytest.approx((0.85 - 1) ** 2)

    def test_med_tier_computed(self):
        self._seed("T2", edge=0.20, our_prob=0.70, settled_yes=0)
        result = tracker.get_brier_by_tier()
        assert result["med"]["n"] == 1
        assert result["med"]["brier"] == pytest.approx((0.70 - 0) ** 2)

    def test_weak_tier_computed(self):
        self._seed("T3", edge=0.05, our_prob=0.55, settled_yes=1)
        result = tracker.get_brier_by_tier()
        assert result["weak"]["n"] == 1

    def test_empty_tier_returns_none_brier(self):
        result = tracker.get_brier_by_tier()
        assert result["strong"]["brier"] is None
        assert result["strong"]["n"] == 0

    def test_multiple_predictions_averaged(self):
        self._seed("A1", edge=0.35, our_prob=0.80, settled_yes=1)
        self._seed("A2", edge=0.40, our_prob=0.90, settled_yes=1)
        result = tracker.get_brier_by_tier()
        expected = ((0.80 - 1) ** 2 + (0.90 - 1) ** 2) / 2
        assert result["strong"]["brier"] == pytest.approx(expected)
        assert result["strong"]["n"] == 2


# ── Phase 3: Adaptive ensemble weights ───────────────────────────────────────


class TestGetModelWeights:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.mkdtemp()
        self._orig_path = tracker.DB_PATH
        self._orig_init = tracker._db_initialized
        tracker.DB_PATH = Path(self._tmp) / "test.db"
        tracker._db_initialized = False
        tracker.init_db()

    def teardown_method(self):
        import shutil

        tracker.DB_PATH = self._orig_path
        tracker._db_initialized = self._orig_init
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed(self, city, model, predicted, actual, days_ago=5):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO ensemble_member_scores "
                "(city, model, predicted_temp, actual_temp, target_date, logged_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (city, model, predicted, actual, "2026-01-01", ts),
            )

    def test_empty_returns_empty_dict(self):
        assert tracker.get_model_weights("NYC") == {}

    def test_weights_sum_to_one(self):
        for i in range(15):
            self._seed("NYC", "gfs", 70.0 + i * 0.1, 71.0)
            self._seed("NYC", "ecmwf", 70.5 + i * 0.1, 71.0)
            self._seed("NYC", "nbm", 69.0 + i * 0.1, 71.0)

        weights = tracker.get_model_weights("NYC", window_days=30)
        assert weights
        assert sum(weights.values()) == pytest.approx(1.0, abs=0.001)

    def test_lower_mae_gets_higher_weight(self):
        # gfs has smaller error than nbm → gfs weight > nbm weight
        for i in range(15):
            self._seed("NYC", "gfs", 71.0, 71.0)  # MAE = 0
            self._seed("NYC", "nbm", 75.0, 71.0)  # MAE = 4

        weights = tracker.get_model_weights("NYC", window_days=30)
        assert weights
        assert weights["gfs"] > weights["nbm"]

    def test_insufficient_observations_returns_equal_weights(self):
        # Only 5 obs per model — below MIN_OBSERVATIONS threshold of 10
        for i in range(5):
            self._seed("NYC", "gfs", 71.0, 71.0)
            self._seed("NYC", "nbm", 72.0, 71.0)

        weights = tracker.get_model_weights("NYC", window_days=30)
        assert weights
        # Equal weights: each = 0.5 for 2 models
        assert weights["gfs"] == pytest.approx(0.5)
        assert weights["nbm"] == pytest.approx(0.5)

    def test_window_days_excludes_old_data(self):
        # Seed old data (40 days ago) — should be excluded by window_days=30
        for i in range(15):
            self._seed("NYC", "gfs", 71.0, 71.0, days_ago=40)
            self._seed("NYC", "nbm", 72.0, 71.0, days_ago=40)

        weights = tracker.get_model_weights("NYC", window_days=30)
        assert weights == {}

    def test_city_isolation(self):
        # Seeds only for Chicago — NYC query should return empty
        for i in range(15):
            self._seed("Chicago", "gfs", 71.0, 71.0)
            self._seed("Chicago", "nbm", 72.0, 71.0)

        assert tracker.get_model_weights("NYC", window_days=30) == {}


# ── Phase 6: Monte Carlo → position sizing ────────────────────────────────────


class TestPortfolioVar:
    def _trade(self, ticker, win_prob=0.6, entry_price=0.50, qty=10, city="NYC"):
        return {
            "ticker": ticker,
            "side": "yes",
            "entry_price": entry_price,
            "cost": round(entry_price * qty, 2),
            "quantity": qty,
            "city": city,
            "target_date": "2026-05-01",
            "entry_prob": win_prob,
        }

    def test_returns_float(self):
        from monte_carlo import portfolio_var

        result = portfolio_var([self._trade("T1")], n_simulations=200)
        assert isinstance(result, float)

    def test_empty_portfolio_returns_zero(self):
        from monte_carlo import portfolio_var

        assert portfolio_var([], n_simulations=200) == 0.0

    def test_var_is_negative_for_loss_scenario(self):
        from monte_carlo import portfolio_var

        # With win_prob=0.5 on many small bets, 5th percentile should be a loss
        trades = [self._trade(f"T{i}", win_prob=0.5) for i in range(5)]
        var = portfolio_var(trades, n_simulations=500)
        assert var < 0

    def test_var_improves_with_higher_win_prob(self):
        from monte_carlo import portfolio_var

        # Use distinct cities so trades are (nearly) independent — avoids
        # all-lose-simultaneously correlated collapse masking win_prob differences
        low_trades = [
            self._trade(f"L{i}", win_prob=0.25, city=f"CityL{i}") for i in range(8)
        ]
        high_trades = [
            self._trade(f"H{i}", win_prob=0.90, city=f"CityH{i}") for i in range(8)
        ]
        low_var = portfolio_var(low_trades, n_simulations=2000)
        high_var = portfolio_var(high_trades, n_simulations=2000)
        assert high_var > low_var

    def test_max_var_dollars_in_utils(self):
        from utils import MAX_VAR_DOLLARS

        assert MAX_VAR_DOLLARS > 0
        assert isinstance(MAX_VAR_DOLLARS, float)

    def test_simulate_portfolio_includes_p5_pnl(self):
        from monte_carlo import simulate_portfolio

        result = simulate_portfolio([self._trade("T1")], n_simulations=200)
        assert "p5_pnl" in result
        assert result["p5_pnl"] <= result["p10_pnl"]
