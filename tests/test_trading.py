"""
Tests for Phase 5 trading improvements:
  #39  bayesian_kelly_fraction
  #49  dynamic correlation matrix
  #50  estimate_slippage
  #63  time_decay_edge
  #65  price improvement tracking
  #73/#74 simulate_fill
  #15  calc_trade_pnl
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Task 1: bayesian_kelly_fraction (#39) ─────────────────────────────────────


class TestBayesianKellyFraction:
    def test_bayesian_kelly_le_point_estimate(self):
        """Bayesian Kelly should be <= point-estimate Kelly for same edge."""
        from weather_markets import bayesian_kelly_fraction, kelly_fraction

        our_prob = 0.65
        market_prob = 0.50
        bk = bayesian_kelly_fraction(our_prob, market_prob, n_predictions=20)
        pk = kelly_fraction(our_prob, market_prob)
        assert bk <= pk, f"bayesian_kelly {bk} should be <= point kelly {pk}"

    def test_converges_toward_point_estimate_with_many_predictions(self):
        """With many more predictions, Bayesian Kelly moves closer to point estimate."""
        from weather_markets import bayesian_kelly_fraction, kelly_fraction

        our_prob = 0.65
        market_prob = 0.50
        pk = kelly_fraction(our_prob, market_prob)
        bk_few = bayesian_kelly_fraction(our_prob, market_prob, n_predictions=5)
        bk_many = bayesian_kelly_fraction(our_prob, market_prob, n_predictions=1000)
        # More predictions → closer to point estimate (less shrinkage)
        assert bk_many > bk_few, (
            f"More predictions should shrink less: bk_many={bk_many} bk_few={bk_few}"
        )
        assert bk_many <= pk, "Bayesian Kelly should never exceed point estimate"

    def test_never_negative(self):
        """bayesian_kelly_fraction must always return >= 0."""
        from weather_markets import bayesian_kelly_fraction

        for our_prob in [0.1, 0.3, 0.5, 0.7, 0.9]:
            for market_prob in [0.2, 0.5, 0.8]:
                result = bayesian_kelly_fraction(our_prob, market_prob)
                assert result >= 0.0, (
                    f"Got negative value {result} for our={our_prob} mkt={market_prob}"
                )

    def test_capped_at_25_percent(self):
        """Result must never exceed 0.25."""
        from weather_markets import bayesian_kelly_fraction

        # Extreme edge: our_prob very high, market_prob very low
        result = bayesian_kelly_fraction(0.99, 0.01)
        assert result <= 0.25, f"Expected <= 0.25, got {result}"


# ── Task 2: dynamic correlation matrix (#49) ──────────────────────────────────


class TestDynamicCorrelationMatrix:
    def test_uses_dynamic_when_available(self, tmp_path):
        """When learned_correlations.json exists, get_city_correlation uses it."""
        import json

        import monte_carlo

        corr_file = tmp_path / "learned_correlations.json"
        corr_file.write_text(json.dumps({"NYC|Boston": 0.92}))

        # Reset the module-level cache so our mock takes effect
        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

        with patch.object(
            monte_carlo,
            "_load_dynamic_correlations",
            return_value={frozenset({"NYC", "Boston"}): 0.92},
        ):
            monte_carlo._dynamic_corr_loaded = False
            result = monte_carlo.get_city_correlation("NYC", "Boston")

        assert result == pytest.approx(0.92)

        # Restore for other tests
        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

    def test_falls_back_to_hardcoded_when_none(self):
        """When _load_dynamic_correlations returns None, use _HARDCODED_CORR."""
        import monte_carlo

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

        with patch.object(monte_carlo, "_load_dynamic_correlations", return_value=None):
            monte_carlo._dynamic_corr_loaded = False
            result = monte_carlo.get_city_correlation("NYC", "Boston")

        # Hardcoded value is 0.85
        assert result == pytest.approx(0.85)

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

    def test_unknown_pair_returns_zero(self):
        """Unknown city pairs should return 0.0."""
        import monte_carlo

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None

        with patch.object(monte_carlo, "_load_dynamic_correlations", return_value=None):
            monte_carlo._dynamic_corr_loaded = False
            result = monte_carlo.get_city_correlation("NYC", "Honolulu")

        assert result == 0.0

        monte_carlo._dynamic_corr_loaded = False
        monte_carlo._dynamic_corr_cache = None


# ── Task 3: estimate_slippage (#50) ───────────────────────────────────────────


class TestEstimateSlippage:
    def test_near_zero_for_single_contract(self):
        """A single contract (quantity=1) should have essentially zero slippage."""
        from paper import estimate_slippage

        result = estimate_slippage(1, market_prob=0.5)
        assert result == 0.0

    def test_zero_at_depth_scale(self):
        """Exactly at depth_scale (50) contracts: no slippage."""
        from paper import estimate_slippage

        result = estimate_slippage(50, market_prob=0.5)
        assert result == 0.0

    def test_slippage_increases_with_quantity(self):
        """Larger orders should have more slippage."""
        from paper import estimate_slippage

        s1 = estimate_slippage(60, market_prob=0.5)
        s2 = estimate_slippage(100, market_prob=0.5)
        s3 = estimate_slippage(200, market_prob=0.5)
        assert 0.0 < s1 < s2 < s3

    def test_capped_at_0_05(self):
        """Slippage should never exceed 0.05."""
        from paper import estimate_slippage

        result = estimate_slippage(10_000, market_prob=0.5)
        assert result <= 0.05


# ── Task 4: time_decay_edge (#63) ─────────────────────────────────────────────


class TestTimeDecayEdge:
    def test_full_edge_far_from_close(self):
        """Well before close (>= reference_hours), edge should be unchanged."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        close_time = datetime.now(UTC) + timedelta(hours=72)
        result = time_decay_edge(raw_edge, close_time, reference_hours=48.0)
        assert result == pytest.approx(raw_edge)

    def test_zero_at_close_time(self):
        """At or past close_time, edge should be 0."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        # Past close
        result = time_decay_edge(raw_edge, datetime.now(UTC) - timedelta(minutes=1))
        assert result == 0.0

    def test_half_edge_at_half_time(self):
        """At exactly half of reference_hours remaining, edge should be halved."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        reference_hours = 48.0
        close_time = datetime.now(UTC) + timedelta(hours=24)  # exactly half
        result = time_decay_edge(raw_edge, close_time, reference_hours=reference_hours)
        assert result == pytest.approx(raw_edge * 0.5, rel=0.02)

    def test_edge_decays_as_close_approaches(self):
        """Edge at 12 hours remaining < edge at 36 hours remaining."""
        from weather_markets import time_decay_edge

        raw_edge = 0.10
        e_far = time_decay_edge(raw_edge, datetime.now(UTC) + timedelta(hours=36))
        e_near = time_decay_edge(raw_edge, datetime.now(UTC) + timedelta(hours=12))
        assert e_far > e_near > 0.0


# ── Task 5: price improvement tracking (#65) ──────────────────────────────────


class TestPriceImprovementTracking:
    def test_log_two_entries_stored(self, tmp_path):
        """log_price_improvement stores rows in the DB."""
        import sqlite3

        import tracker

        db_path = tmp_path / "test.db"
        with patch.object(tracker, "DB_PATH", db_path):
            tracker._db_initialized = False
            tracker.init_db()
            tracker.log_price_improvement("TICK1", 0.60, 0.58, 5, "yes")
            tracker.log_price_improvement("TICK1", 0.60, 0.61, 10, "no")
            tracker._db_initialized = False  # reset for next test

        with sqlite3.connect(db_path) as con:
            rows = con.execute("SELECT * FROM price_improvement").fetchall()
        assert len(rows) == 2

    def test_stats_returns_none_with_fewer_than_5_entries(self, tmp_path):
        """get_price_improvement_stats returns None when < 5 entries exist."""
        import tracker

        db_path = tmp_path / "test2.db"
        with patch.object(tracker, "DB_PATH", db_path):
            tracker._db_initialized = False
            tracker.init_db()
            tracker.log_price_improvement("TICK1", 0.60, 0.58, 5, "yes")
            tracker.log_price_improvement("TICK1", 0.60, 0.61, 10, "no")
            result = tracker.get_price_improvement_stats()
            tracker._db_initialized = False

        assert result is None


# ── Task 6: simulate_fill (#73, #74) ─────────────────────────────────────────


class TestSimulateFill:
    def test_small_order_in_deep_market_fully_filled(self):
        """A small order (< 20% of volume) should be fully filled."""
        from paper import simulate_fill

        # quantity=10, volume=500 → 10 <= 100 → full fill
        filled, _ = simulate_fill(10, market_prob=0.50, volume=500)
        assert filled == pytest.approx(10.0)

    def test_large_order_in_thin_market_partially_filled(self):
        """A large order (>> 20% of volume) should be partially filled."""
        from paper import simulate_fill

        # quantity=200, volume=500 → 200 > 100 → partial
        filled, _ = simulate_fill(200, market_prob=0.50, volume=500)
        assert filled < 200

    def test_fill_price_within_valid_range(self):
        """avg_fill_price must always be in (0, 1)."""
        from paper import simulate_fill

        for qty in [1, 50, 500]:
            _, price = simulate_fill(qty, market_prob=0.60, volume=500)
            assert 0.0 < price < 1.0, f"price {price} out of range for qty={qty}"


# ── Task 7: calc_trade_pnl (#15) ─────────────────────────────────────────────


class TestCalcTradePnl:
    def test_yes_win_with_actual_fill_price(self):
        """YES side, settled YES, actual_fill_price=0.62 on 10 contracts."""
        from paper import calc_trade_pnl

        trade = {
            "side": "yes",
            "outcome": "yes",
            "actual_fill_price": 0.62,
            "quantity": 10,
        }
        pnl = calc_trade_pnl(trade)
        expected = (1.0 - 0.62) * 10  # = 3.80
        assert pnl == pytest.approx(expected)

    def test_yes_loss_uses_actual_fill_price(self):
        """YES side, settled NO → loss."""
        from paper import calc_trade_pnl

        trade = {
            "side": "yes",
            "outcome": "no",
            "actual_fill_price": 0.62,
            "quantity": 10,
        }
        pnl = calc_trade_pnl(trade)
        expected = -0.62 * 10  # = -6.20
        assert pnl == pytest.approx(expected)

    def test_falls_back_to_entry_price_when_no_actual_fill(self):
        """When actual_fill_price is absent, uses entry_price."""
        from paper import calc_trade_pnl

        trade = {
            "side": "yes",
            "outcome": "yes",
            "entry_price": 0.60,
            "quantity": 5,
        }
        pnl = calc_trade_pnl(trade)
        expected = (1.0 - 0.60) * 5  # = 2.00
        assert pnl == pytest.approx(expected)

    def test_no_side_win(self):
        """NO side, settled NO → win."""
        from paper import calc_trade_pnl

        trade = {
            "side": "no",
            "outcome": "no",
            "actual_fill_price": 0.40,
            "quantity": 10,
        }
        pnl = calc_trade_pnl(trade)
        expected = (1.0 - 0.40) * 10  # = 6.00
        assert pnl == pytest.approx(expected)


class TestBayesianKellyFractionBeta:
    """#39: bayesian_kelly_fraction must accept fee_rate and use Beta posterior."""

    def test_accepts_fee_rate_kwarg(self):
        """fee_rate kwarg must be accepted without error."""
        from weather_markets import bayesian_kelly_fraction

        result = bayesian_kelly_fraction(0.65, 0.50, n_predictions=20, fee_rate=0.07)
        assert result >= 0.0

    def test_higher_fee_reduces_fraction(self):
        """Higher fee_rate should produce equal or smaller Kelly fraction."""
        from weather_markets import bayesian_kelly_fraction

        f_low = bayesian_kelly_fraction(0.65, 0.50, n_predictions=20, fee_rate=0.01)
        f_high = bayesian_kelly_fraction(0.65, 0.50, n_predictions=20, fee_rate=0.20)
        assert f_low >= f_high

    def test_beta_posterior_is_conservative(self):
        """Beta-posterior Kelly must be <= point-estimate Kelly at same edge."""
        from weather_markets import bayesian_kelly_fraction, kelly_fraction

        our_prob = 0.70
        market_prob = 0.50
        bk = bayesian_kelly_fraction(
            our_prob, market_prob, n_predictions=20, fee_rate=0.07
        )
        pk = kelly_fraction(our_prob, market_prob, fee_rate=0.07)
        assert bk <= pk

    def test_zero_for_no_edge(self):
        """When our_prob == market_prob, Kelly should be 0."""
        from weather_markets import bayesian_kelly_fraction

        result = bayesian_kelly_fraction(0.50, 0.50, n_predictions=20, fee_rate=0.07)
        assert result == 0.0

    def test_capped_at_0_25(self):
        """Result must never exceed 0.25."""
        from weather_markets import bayesian_kelly_fraction

        result = bayesian_kelly_fraction(0.99, 0.01, n_predictions=20, fee_rate=0.07)
        assert result <= 0.25


class TestCorrelationPersistence:
    """#49: load_correlations_from_backtest / save_correlations round-trip."""

    def test_save_and_reload(self, tmp_path):
        """save_correlations writes JSON; load_correlations_from_backtest reads it back."""
        from unittest.mock import patch

        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        pairs = {"NYC|Boston": 0.91, "Chicago|Denver": 0.43}

        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations(pairs)
            assert corr_file.exists()
            result = monte_carlo.load_correlations_from_backtest()

        assert result[frozenset({"NYC", "Boston"})] == pytest.approx(0.91)
        assert result[frozenset({"Chicago", "Denver"})] == pytest.approx(0.43)

    def test_fallback_to_hardcoded_when_file_missing(self, tmp_path):
        """When correlations.json is absent, returns _HARDCODED_CORR."""
        from unittest.mock import patch

        import monte_carlo

        missing = tmp_path / "correlations.json"

        with patch.object(monte_carlo, "_CORR_PATH", missing):
            result = monte_carlo.load_correlations_from_backtest()

        # NYC|Boston hardcoded at 0.85
        assert result[frozenset({"NYC", "Boston"})] == pytest.approx(0.85)

    def test_save_correlations_valid_json(self, tmp_path):
        """save_correlations produces valid JSON with pipe-separated keys."""
        import json
        from unittest.mock import patch

        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations({"LA|Phoenix": 0.60})

        raw = json.loads(corr_file.read_text())
        assert "LA|Phoenix" in raw
        assert raw["LA|Phoenix"] == pytest.approx(0.60)

    def test_unknown_pair_returns_zero_after_load(self, tmp_path):
        """After loading, unknown city pairs return 0.0."""
        from unittest.mock import patch

        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations({"NYC|Boston": 0.88})
            result = monte_carlo.load_correlations_from_backtest()

        assert result.get(frozenset({"NYC", "Honolulu"}), 0.0) == 0.0


class TestSlippageAdjustedPrice:
    """#50: slippage_adjusted_price uses 0.001 * sqrt(quantity) model."""

    def test_buy_yes_increases_price(self):
        """Buying YES adds slippage to base price."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.50, 100, "yes")
        expected_slip = 0.001 * (100**0.5)  # 0.01
        assert result == pytest.approx(0.50 + expected_slip, rel=1e-5)

    def test_buy_no_decreases_price(self):
        """Buying NO subtracts slippage (worse fill for the buyer)."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.40, 100, "no")
        expected_slip = 0.001 * (100**0.5)
        assert result == pytest.approx(0.40 - expected_slip, rel=1e-5)

    def test_zero_slippage_at_quantity_zero(self):
        """quantity=1 produces 0.001 slippage."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.50, 1, "yes")
        assert result == pytest.approx(0.501, rel=1e-5)

    def test_clamped_to_0_01_0_99(self):
        """Output must always be in [0.01, 0.99]."""
        from paper import slippage_adjusted_price

        high = slippage_adjusted_price(0.99, 1_000_000, "yes")
        low = slippage_adjusted_price(0.01, 1_000_000, "no")
        assert high <= 0.99
        assert low >= 0.01

    def test_place_paper_order_stores_actual_fill_price(self, tmp_path):
        """place_paper_order records actual_fill_price != entry_price for large orders."""
        import shutil
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import paper

        tmpdir = tempfile.mkdtemp()
        try:
            with patch("paper.DATA_PATH", Path(tmpdir) / "paper_trades.json"):
                trade = paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side="yes",
                    quantity=100,
                    entry_price=0.50,
                    entry_prob=0.65,
                    city="NYC",
                    target_date="2025-04-10",
                )
            assert "actual_fill_price" in trade
            assert trade["actual_fill_price"] != trade["entry_price"]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestPortfolioKelly:
    """#51: portfolio_kelly returns correlation-adjusted Kelly fractions."""

    def test_single_position_returns_list_of_one(self):
        """Single uncorrelated position returns its own Kelly fraction unchanged."""
        from paper import portfolio_kelly

        positions = [
            {
                "city": "NYC",
                "side": "yes",
                "our_prob": 0.65,
                "market_prob": 0.50,
                "quantity": 10,
            }
        ]
        result = portfolio_kelly(positions)
        assert len(result) == 1
        assert 0.0 <= result[0] <= 0.25

    def test_correlated_positions_reduce_fractions(self):
        """Highly correlated city pair should produce lower fractions than independent."""
        from paper import portfolio_kelly

        correlated = [
            {
                "city": "NYC",
                "side": "yes",
                "our_prob": 0.65,
                "market_prob": 0.50,
                "quantity": 10,
            },
            {
                "city": "Boston",
                "side": "yes",
                "our_prob": 0.65,
                "market_prob": 0.50,
                "quantity": 10,
            },
        ]
        independent = [
            {
                "city": "NYC",
                "side": "yes",
                "our_prob": 0.65,
                "market_prob": 0.50,
                "quantity": 10,
            },
            {
                "city": "Dallas",
                "side": "yes",
                "our_prob": 0.65,
                "market_prob": 0.50,
                "quantity": 10,
            },
        ]
        corr_fracs = portfolio_kelly(correlated)
        indep_fracs = portfolio_kelly(independent)
        assert sum(corr_fracs) <= sum(indep_fracs)

    def test_all_fractions_non_negative(self):
        """All returned fractions must be >= 0."""
        from paper import portfolio_kelly

        positions = [
            {
                "city": "NYC",
                "side": "yes",
                "our_prob": 0.70,
                "market_prob": 0.50,
                "quantity": 5,
            },
            {
                "city": "Boston",
                "side": "no",
                "our_prob": 0.60,
                "market_prob": 0.45,
                "quantity": 3,
            },
            {
                "city": "Chicago",
                "side": "yes",
                "our_prob": 0.55,
                "market_prob": 0.50,
                "quantity": 8,
            },
        ]
        result = portfolio_kelly(positions)
        assert all(f >= 0.0 for f in result)

    def test_returns_same_length_as_input(self):
        """Output list length must match input list length."""
        from paper import portfolio_kelly

        positions = [
            {
                "city": "LA",
                "side": "yes",
                "our_prob": 0.60,
                "market_prob": 0.50,
                "quantity": 2,
            },
            {
                "city": "Phoenix",
                "side": "yes",
                "our_prob": 0.65,
                "market_prob": 0.55,
                "quantity": 4,
            },
            {
                "city": "Miami",
                "side": "no",
                "our_prob": 0.58,
                "market_prob": 0.52,
                "quantity": 6,
            },
        ]
        result = portfolio_kelly(positions)
        assert len(result) == len(positions)

    def test_empty_positions_returns_empty_list(self):
        """Empty input returns empty output."""
        from paper import portfolio_kelly

        assert portfolio_kelly([]) == []


# ── Task 5: tiered auto-trade ─────────────────────────────────────────────────


def test_auto_place_trades_med_tier_uses_20_cap(monkeypatch):
    """_auto_place_trades with cap=20.0 should call kelly_quantity with cap=20.0."""
    import main

    captured_caps = []

    def fake_kelly_quantity(kf, price, min_dollars=1.0, cap=None, method=None):
        captured_caps.append(cap)
        # Return 10 contracts so the trade goes through
        return 10

    def fake_portfolio_kelly_fraction(ci_kelly, city, target_date, side=None):
        return 0.05  # non-trivial fraction so we don't skip

    def fake_get_open_trades():
        return []  # no existing positions

    def fake_is_paused_drawdown():
        return False

    def fake_is_daily_loss_halted(client=None):
        return False

    def fake_is_streak_paused():
        return False

    def fake_place_paper_order(*args, **kwargs):
        return {"id": 1}

    def fake_was_ordered_this_cycle(ticker, side, cycle):
        return False

    monkeypatch.setattr("main.place_paper_order", fake_place_paper_order)
    monkeypatch.setattr(
        "main.execution_log.was_ordered_this_cycle", fake_was_ordered_this_cycle
    )

    import paper

    monkeypatch.setattr(paper, "kelly_quantity", fake_kelly_quantity)
    monkeypatch.setattr(
        paper, "portfolio_kelly_fraction", fake_portfolio_kelly_fraction
    )
    monkeypatch.setattr(paper, "get_open_trades", fake_get_open_trades)
    monkeypatch.setattr(paper, "is_paused_drawdown", fake_is_paused_drawdown)
    monkeypatch.setattr(paper, "is_daily_loss_halted", fake_is_daily_loss_halted)
    monkeypatch.setattr(paper, "is_streak_paused", fake_is_streak_paused)

    opps = [
        (
            {"ticker": "KXHIGH-26APR15-NYC", "_city": "NYC", "_date": None},
            {
                "net_signal": "STRONG BUY",
                "time_risk": "LOW",
                "recommended_side": "yes",
                "ci_adjusted_kelly": 0.10,
                "market_prob": 0.40,
                "forecast_prob": 0.60,
                "net_edge": 0.18,
                "method": "ensemble",
                "model_consensus": True,
                "near_threshold": False,
            },
        )
    ]

    placed = main._auto_place_trades(opps, client=None, cap=20.0)

    assert placed == 1
    assert len(captured_caps) == 1, f"kelly_quantity called {len(captured_caps)} times"
    assert captured_caps[0] == 20.0, f"Expected cap=20.0, got cap={captured_caps[0]}"
