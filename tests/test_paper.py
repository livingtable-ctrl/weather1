"""
Tests for paper.py — Kelly compounding, balance, order placement, settlement.
"""

import shutil
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest.mock import patch


class TestKellyCompounding(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _reload(self):
        import importlib

        import paper

        importlib.reload(paper)
        return paper

    def test_initial_balance_is_1000(self):
        import paper

        self.assertAlmostEqual(paper.get_balance(), 1000.0)

    def test_kelly_bet_dollars_scales_with_balance(self):
        import paper

        dollars = paper.kelly_bet_dollars(0.10)
        self.assertAlmostEqual(dollars, 100.0)  # 10% of $1000

    def test_kelly_bet_dollars_caps_at_25_percent(self):
        import paper

        # Even if Kelly says 50%, we cap at 25%
        dollars = paper.kelly_bet_dollars(0.50)
        self.assertAlmostEqual(dollars, 250.0)

    def test_kelly_bet_dollars_floors_at_zero(self):
        import paper

        dollars = paper.kelly_bet_dollars(-0.10)
        self.assertEqual(dollars, 0.0)

    def test_kelly_quantity_basic(self):
        import paper

        # $100 bet at $0.50/contract = 200 contracts
        qty = paper.kelly_quantity(0.10, 0.50)
        self.assertEqual(qty, 200)

    def test_kelly_quantity_zero_price_returns_zero(self):
        import paper

        self.assertEqual(paper.kelly_quantity(0.10, 0.0), 0)

    def test_kelly_quantity_zero_fraction_returns_zero(self):
        import paper

        self.assertEqual(paper.kelly_quantity(0.0, 0.50), 0)

    def test_balance_decreases_after_order(self):
        import paper

        paper.place_paper_order("TKTEST", "yes", 10, 0.50)
        self.assertAlmostEqual(paper.get_balance(), 995.0)  # 1000 - 5

    def test_kelly_bet_compounds_after_win(self):
        import paper

        # Place a trade
        trade = paper.place_paper_order("TKTEST", "yes", 10, 0.50)
        balance_before = paper.get_balance()
        # Settle as a winner — payout = 10 * 0.965 = 9.65 (fee on winnings only)
        paper.settle_paper_trade(trade["id"], outcome_yes=True)
        balance_after = paper.get_balance()
        self.assertGreater(balance_after, balance_before)
        # Next Kelly bet should be larger
        dollars_after = paper.kelly_bet_dollars(0.10)
        self.assertGreater(dollars_after, 100.0 - 0.50)  # slightly less than 1000 * 10%

    def test_balance_decreases_after_loss(self):
        import paper

        trade = paper.place_paper_order("TKTEST", "yes", 10, 0.50)
        paper.settle_paper_trade(trade["id"], outcome_yes=False)
        # Lost the $5 stake
        self.assertAlmostEqual(paper.get_balance(), 995.0)

    def test_insufficient_balance_raises(self):
        import paper

        with self.assertRaises(ValueError):
            # Try to bet $2000 with only $1000 balance
            paper.place_paper_order("TKTEST", "yes", 4000, 0.50)

    def test_settle_nonexistent_trade_raises(self):
        import paper

        with self.assertRaises(ValueError):
            paper.settle_paper_trade(9999, outcome_yes=True)

    def test_reset_restores_starting_balance(self):
        import paper

        paper.place_paper_order("TKTEST", "yes", 10, 0.50)
        paper.reset_paper_account()
        self.assertAlmostEqual(paper.get_balance(), 1000.0)
        self.assertEqual(len(paper.get_all_trades()), 0)

    def test_get_performance_empty(self):
        import paper

        perf = paper.get_performance()
        self.assertEqual(perf["settled"], 0)
        self.assertIsNone(perf["win_rate"])

    def test_get_performance_with_win(self):
        import paper

        trade = paper.place_paper_order("TKTEST", "yes", 100, 0.50)
        paper.settle_paper_trade(trade["id"], outcome_yes=True)
        perf = paper.get_performance()
        self.assertEqual(perf["settled"], 1)
        self.assertEqual(perf["wins"], 1)
        self.assertAlmostEqual(perf["win_rate"], 1.0)
        self.assertGreater(perf["total_pnl"], 0)


class TestIsStale(unittest.TestCase):
    def test_market_with_volume_not_stale(self):
        from weather_markets import is_stale

        market = {"volume": 100, "close_time": "2025-04-09T00:01:00Z"}
        self.assertFalse(is_stale(market))

    def test_market_no_volume_far_future_not_stale(self):
        # Closes in 2 hours
        from datetime import datetime, timedelta

        from weather_markets import is_stale

        close = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        market = {"volume": 0, "open_interest": 0, "close_time": close}
        self.assertFalse(is_stale(market))

    def test_market_no_volume_closing_soon_is_stale(self):
        from datetime import datetime, timedelta

        from weather_markets import is_stale

        close = (datetime.now(UTC) + timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        market = {"volume": 0, "open_interest": 0, "close_time": close}
        self.assertTrue(is_stale(market))

    def test_market_with_open_interest_not_stale(self):
        from datetime import datetime, timedelta

        from weather_markets import is_stale

        close = (datetime.now(UTC) + timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        market = {"volume": 0, "open_interest": 50, "close_time": close}
        self.assertFalse(is_stale(market))

    def test_missing_close_time_not_stale(self):
        from weather_markets import is_stale

        market = {"volume": 0, "open_interest": 0, "close_time": ""}
        self.assertFalse(is_stale(market))


class TestMaxDrawdown(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_not_paused_at_start(self):
        import paper

        self.assertFalse(paper.is_paused_drawdown())

    def test_paused_below_threshold(self):
        """Balance below 50% of $1000 → drawdown active."""
        import paper

        # Drain balance to $400 by placing a losing trade
        paper.place_paper_order("TK", "yes", 600, 1.00)  # cost=$600 → balance=$400
        self.assertTrue(paper.is_paused_drawdown())

    def test_kelly_returns_zero_in_drawdown(self):
        """kelly_bet_dollars should return 0.0 when in drawdown."""
        import paper

        paper.place_paper_order("TK", "yes", 600, 1.00)  # balance → $400
        self.assertEqual(paper.kelly_bet_dollars(0.10), 0.0)

    def test_kelly_normal_above_threshold(self):
        """kelly_bet_dollars works normally when balance >= $500."""
        import paper

        # Balance is $1000 (starting), which is above threshold
        result = paper.kelly_bet_dollars(0.10)
        self.assertAlmostEqual(result, 100.0)

    def test_boundary_exactly_500_not_paused(self):
        """Balance exactly at $500 (= 50% of $1000) is NOT paused (strict less-than)."""
        import paper

        paper.place_paper_order("TK", "yes", 500, 1.00)  # cost=$500 → balance=$500
        self.assertFalse(paper.is_paused_drawdown())


class TestPortfolioKelly(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_exposure_zero_with_no_trades(self):
        import paper

        self.assertAlmostEqual(paper.get_city_date_exposure("NYC", "2026-04-09"), 0.0)

    def test_exposure_with_matching_trade(self):
        """Open trade for NYC/2026-04-09 should show up in exposure."""
        import paper

        paper.place_paper_order(
            "TK1", "yes", 50, 0.50, city="NYC", target_date="2026-04-09"
        )
        # cost = 50 * 0.50 = $25; exposure = 25 / 1000 = 0.025
        exposure = paper.get_city_date_exposure("NYC", "2026-04-09")
        self.assertAlmostEqual(exposure, 0.025)

    def test_exposure_ignores_other_city(self):
        """Trade for Chicago should not count toward NYC exposure."""
        import paper

        paper.place_paper_order(
            "TK1", "yes", 50, 0.50, city="CHI", target_date="2026-04-09"
        )
        exposure = paper.get_city_date_exposure("NYC", "2026-04-09")
        self.assertAlmostEqual(exposure, 0.0)

    def test_exposure_ignores_settled_trade(self):
        """Settled trades should not count toward exposure."""
        import paper

        trade = paper.place_paper_order(
            "TK1", "yes", 50, 0.50, city="NYC", target_date="2026-04-09"
        )
        paper.settle_paper_trade(trade["id"], outcome_yes=True)
        exposure = paper.get_city_date_exposure("NYC", "2026-04-09")
        self.assertAlmostEqual(exposure, 0.0)

    def test_portfolio_kelly_no_exposure(self):
        """Zero existing exposure → base fraction returned unchanged."""
        import paper

        result = paper.portfolio_kelly_fraction(0.10, "NYC", "2026-04-09")
        self.assertAlmostEqual(result, 0.10)

    def test_portfolio_kelly_at_cap(self):
        """Existing exposure >= MAX → returns 0.0."""
        import paper

        # Place $150 trade → exposure = 0.15 = MAX_CITY_DATE_EXPOSURE
        paper.place_paper_order(
            "TK1", "yes", 300, 0.50, city="NYC", target_date="2026-04-09"
        )
        result = paper.portfolio_kelly_fraction(0.10, "NYC", "2026-04-09")
        self.assertEqual(result, 0.0)

    def test_portfolio_kelly_partial_exposure(self):
        """Half of max city/date exposure → Kelly reduced by both city-date scale
        and the continuous correlated-city penalty."""
        import paper

        # Place $75 trade → city/date exposure = 0.075 = half of MAX (0.15)
        # NYC is in the {NYC, Boston} correlated group, so corr penalty also applies.
        paper.place_paper_order(
            "TK1", "yes", 150, 0.50, city="NYC", target_date="2026-04-09"
        )
        result = paper.portfolio_kelly_fraction(0.10, "NYC", "2026-04-09")
        # city/date scale = 0.5, corr_scale = 1 - (0.075/0.20)*0.70 ≈ 0.7375
        # expected = 0.10 * 0.5 * 0.7375 = 0.036875
        self.assertAlmostEqual(result, 0.036875, places=4)

    def test_portfolio_kelly_no_city_passthrough(self):
        """None city → base fraction returned unchanged (no lookup possible)."""
        import paper

        result = paper.portfolio_kelly_fraction(0.10, None, None)
        self.assertAlmostEqual(result, 0.10)

    def test_place_paper_order_stores_city_date(self):
        """Trade record should include city and target_date fields."""
        import paper

        trade = paper.place_paper_order(
            "TK1", "yes", 10, 0.50, city="NYC", target_date="2026-04-09"
        )
        self.assertEqual(trade["city"], "NYC")
        self.assertEqual(trade["target_date"], "2026-04-09")


class TestHighWaterMark(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_peak_tracks_winning_trade(self):
        import paper

        trade = paper.place_paper_order(
            "TK", "yes", 100, 0.50
        )  # cost=$50, balance=$950
        paper.settle_paper_trade(
            trade["id"], outcome_yes=True
        )  # payout=96.5, balance=$1046.5
        self.assertGreater(paper.get_peak_balance(), 1000.0)

    def test_peak_does_not_decrease_on_loss(self):
        import paper

        trade = paper.place_paper_order("TK", "yes", 100, 0.50)
        paper.settle_paper_trade(trade["id"], outcome_yes=False)  # balance drops
        self.assertAlmostEqual(paper.get_peak_balance(), 1000.0)

    def test_max_drawdown_pct_correct(self):
        import paper

        # Drain $600 → balance=$400, peak=$1000, drawdown=60%
        paper.place_paper_order("TK", "yes", 600, 1.00)
        dd = paper.get_max_drawdown_pct()
        self.assertAlmostEqual(dd, 0.60, places=4)

    def test_paused_from_peak_not_start(self):
        """Win to $1500+, then lose >50% of peak → should be paused."""
        import paper

        # Win big: 1000 contracts at $0.50 → payout = 1000 * 0.965 = $965 (fee on winnings only)
        t1 = paper.place_paper_order(
            "TK1", "yes", 1000, 0.50
        )  # cost=$500, balance=$500
        paper.settle_paper_trade(t1["id"], outcome_yes=True)  # +$965 → balance=$1465
        peak = paper.get_peak_balance()
        self.assertGreater(peak, 1000.0)

        # Now lose enough to go below 50% of peak
        half_peak = peak * 0.5
        current = paper.get_balance()
        loss_amount = current - half_peak + 10  # put balance below 50% of peak
        if loss_amount > 0:
            t2 = paper.place_paper_order("TK2", "yes", int(loss_amount), 1.00)
            paper.settle_paper_trade(t2["id"], outcome_yes=False)
            self.assertTrue(paper.is_paused_drawdown())

    def test_drawdown_zero_at_start(self):
        import paper

        self.assertAlmostEqual(paper.get_max_drawdown_pct(), 0.0)

    def test_performance_includes_peak_and_drawdown(self):
        import paper

        perf = paper.get_performance()
        self.assertIn("peak_balance", perf)
        self.assertIn("max_drawdown_pct", perf)


class TestDirectionalExposure(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_directional_exposure_same_side(self):
        """Two YES bets on same city/date sum correctly."""
        import paper

        paper.place_paper_order(
            "TK1", "yes", 50, 0.50, city="NYC", target_date="2026-04-09"
        )
        paper.place_paper_order(
            "TK2", "yes", 50, 0.50, city="NYC", target_date="2026-04-09"
        )
        # Each costs $25 → total YES = $50 → 0.05
        exp = paper.get_directional_exposure("NYC", "2026-04-09", "yes")
        self.assertAlmostEqual(exp, 0.05, places=4)

    def test_directional_exposure_other_side(self):
        """NO bets don't count toward YES directional exposure."""
        import paper

        paper.place_paper_order(
            "TK1", "yes", 50, 0.50, city="NYC", target_date="2026-04-09"
        )
        paper.place_paper_order(
            "TK2", "no", 50, 0.50, city="NYC", target_date="2026-04-09"
        )
        yes_exp = paper.get_directional_exposure("NYC", "2026-04-09", "yes")
        no_exp = paper.get_directional_exposure("NYC", "2026-04-09", "no")
        self.assertAlmostEqual(yes_exp, 0.025, places=4)
        self.assertAlmostEqual(no_exp, 0.025, places=4)

    def test_portfolio_kelly_with_directional_penalty(self):
        """Concentrated same-side bets trigger 50% further reduction."""
        import paper

        # Place $150 YES (15% of $1000) — above MAX_DIRECTIONAL_EXPOSURE (10%)
        paper.place_paper_order(
            "TK1", "yes", 300, 0.50, city="NYC", target_date="2026-04-09"
        )
        # 0.15 directional YES → penalty kicks in
        result = paper.portfolio_kelly_fraction(0.10, "NYC", "2026-04-09", side="yes")
        # Either 0 (hit city cap) or reduced with penalty
        # City exposure = 0.15 = MAX → returns 0
        self.assertEqual(result, 0.0)

    def test_directional_penalty_applies_before_city_cap(self):
        """When city exposure < max but directional > threshold, penalty applies."""
        import paper

        # $75 YES → city_exposure=0.075 (under cap), directional_YES=0.075 (under penalty threshold)
        paper.place_paper_order(
            "TK1", "yes", 150, 0.50, city="NYC", target_date="2026-04-09"
        )
        # Add more YES to push directional over 0.10
        paper.place_paper_order(
            "TK2", "yes", 50, 0.50, city="NYC", target_date="2026-04-09"
        )
        # directional YES = $100 / 1000 = 0.10 exactly (not strictly >), so no penalty yet
        result_no_penalty = paper.portfolio_kelly_fraction(
            0.10, "NYC", "2026-04-09", side="yes"
        )
        # Add one more to exceed threshold
        paper.place_paper_order(
            "TK3", "yes", 20, 0.50, city="NYC", target_date="2026-04-09"
        )
        result_with_penalty = paper.portfolio_kelly_fraction(
            0.10, "NYC", "2026-04-09", side="yes"
        )
        # With more directional exposure, result should be smaller (or 0 if at cap)
        self.assertLessEqual(result_with_penalty, result_no_penalty)


class TestExportTrades(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_export_trades_csv(self):
        import csv

        import paper

        paper.place_paper_order(
            "TK1", "yes", 10, 0.50, city="NYC", target_date="2026-04-09"
        )
        paper.place_paper_order(
            "TK2", "no", 5, 0.60, city="CHI", target_date="2026-04-10"
        )

        out_path = str(Path(self._tmpdir) / "trades.csv")
        n = paper.export_trades_csv(out_path)
        self.assertEqual(n, 2)

        with open(out_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ticker"], "TK1")
        self.assertEqual(rows[1]["ticker"], "TK2")

    def test_export_trades_csv_empty(self):
        import paper

        out_path = str(Path(self._tmpdir) / "trades.csv")
        n = paper.export_trades_csv(out_path)
        self.assertEqual(n, 0)


class TestDrawdownScaling(unittest.TestCase):
    """Tests for the gradual drawdown recovery sizing feature."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_full_scaling_at_peak(self):
        """At full balance, scaling factor is 1.0."""
        import paper

        self.assertEqual(paper.drawdown_scaling_factor(), 1.0)

    def test_zero_scaling_below_50_pct(self):
        """Below 50% of peak → scale = 0.0 (fully paused)."""
        import paper

        paper.place_paper_order("TK", "yes", 600, 1.00)  # balance → $400 (40% of $1000)
        self.assertEqual(paper.drawdown_scaling_factor(), 0.0)

    def test_tier2_scaling_between_50_and_60_pct(self):
        """Balance 50–60% of peak → scale = 0.10 (conservative recovery)."""
        import paper

        paper.place_paper_order("TK", "yes", 450, 1.00)  # balance → $550 (55% of $1000)
        self.assertEqual(paper.drawdown_scaling_factor(), 0.10)

    def test_tier3_scaling_between_60_and_75_pct(self):
        """Balance 60–75% of peak → scale = 0.30."""
        import paper

        paper.place_paper_order("TK", "yes", 350, 1.00)  # balance → $650 (65% of $1000)
        self.assertEqual(paper.drawdown_scaling_factor(), 0.30)

    def test_tier4_scaling_between_75_and_90_pct(self):
        """Balance 75–90% of peak → scale = 0.70."""
        import paper

        paper.place_paper_order("TK", "yes", 200, 1.00)  # balance → $800 (80% of $1000)
        self.assertEqual(paper.drawdown_scaling_factor(), 0.70)

    def test_kelly_scaled_at_partial_recovery(self):
        """Kelly dollars are scaled by recovery factor, not all-or-nothing."""
        import paper

        paper.place_paper_order(
            "TK", "yes", 350, 1.00
        )  # balance → $650 (65% of peak), scale=0.30
        dollars = paper.kelly_bet_dollars(0.10)
        # 0.10 * 0.30 * $650 = $19.50
        self.assertAlmostEqual(dollars, 19.50)

    def test_kelly_zero_below_50_pct(self):
        """Kelly still returns 0.0 when fully in drawdown (scale=0.0)."""
        import paper

        paper.place_paper_order("TK", "yes", 600, 1.00)  # balance → $400
        self.assertEqual(paper.kelly_bet_dollars(0.10), 0.0)


class TestAutoSettlePaperTrades(unittest.TestCase):
    """Tests for auto-settling paper trades when tracker outcomes are recorded."""

    def setUp(self):
        import tempfile

        import tracker

        self._paper_dir = tempfile.mkdtemp()
        self._tracker_dir = tempfile.mkdtemp()
        self._paper_patch = patch(
            "paper.DATA_PATH", Path(self._paper_dir) / "paper_trades.json"
        )
        self._tracker_patch = patch(
            "tracker.DB_PATH", Path(self._tracker_dir) / "predictions.db"
        )
        self._paper_patch.start()
        self._tracker_patch.start()
        # Reset the init flag so init_db() re-creates tables in the new temp DB
        tracker._db_initialized = False

    def tearDown(self):
        import tracker

        self._paper_patch.stop()
        self._tracker_patch.stop()
        tracker._db_initialized = False
        shutil.rmtree(self._paper_dir, ignore_errors=True)
        shutil.rmtree(self._tracker_dir, ignore_errors=True)

    def test_auto_settle_settles_matching_trade(self):
        """auto_settle_paper_trades() closes paper trades with recorded outcomes."""
        import paper
        import tracker

        paper.place_paper_order("TKAUTO", "yes", 10, 0.50)
        tracker.log_outcome("TKAUTO", True)  # YES settled

        settled = paper.auto_settle_paper_trades()
        self.assertEqual(settled, 1)
        open_trades = paper.get_open_trades()
        self.assertEqual(len(open_trades), 0)

    def test_auto_settle_skips_no_outcome(self):
        """auto_settle_paper_trades() leaves trades open when no outcome recorded."""
        import paper

        paper.place_paper_order("TKPENDING", "yes", 10, 0.50)
        settled = paper.auto_settle_paper_trades()
        self.assertEqual(settled, 0)
        self.assertEqual(len(paper.get_open_trades()), 1)

    def test_get_outcome_for_ticker_returns_none_when_missing(self):
        import tracker

        result = tracker.get_outcome_for_ticker("NOTEXIST")
        self.assertIsNone(result)

    def test_get_outcome_for_ticker_returns_correct_value(self):
        import tracker

        tracker.log_prediction(
            "TKOUT",
            "NYC",
            __import__("datetime").date(2026, 4, 9),
            {
                "our_prob": 0.70,
                "market_prob": 0.60,
                "edge": 0.10,
                "condition": {"type": "above", "threshold": 70},
                "signal": "BUY YES",
                "forecast_prob": 0.70,
                "forecast_temp": 72.0,
            },
        )
        tracker.log_outcome("TKOUT", False)
        self.assertIs(tracker.get_outcome_for_ticker("TKOUT"), False)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestGaussianFillSlippage:
    """#73: place_paper_order simulates random Gaussian fill slippage."""

    def _place(self, qty=10, price=0.50, side="yes"):
        import paper

        tmpdir = tempfile.mkdtemp()
        try:
            with patch("paper.DATA_PATH", Path(tmpdir) / "trades.json"):
                trade = paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side=side,
                    quantity=qty,
                    entry_price=price,
                    entry_prob=0.60,
                    city="NYC",
                    target_date="2025-04-10",
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return trade

    def test_actual_fill_price_in_valid_range(self):
        """actual_fill_price must always be in [0.01, 0.99]."""
        for _ in range(20):
            trade = self._place(price=0.50)
            assert 0.01 <= trade["actual_fill_price"] <= 0.99

    def test_actual_fill_price_deviates_from_entry(self):
        """Over many fills, actual_fill_price should vary around entry_price."""
        fills = [self._place(price=0.50)["actual_fill_price"] for _ in range(30)]
        assert len(set(fills)) > 1, "All fills identical — Gaussian noise not applied"

    def test_entry_price_unchanged(self):
        """entry_price on the trade record must equal the requested price."""
        trade = self._place(price=0.60)
        assert trade["entry_price"] == 0.60


class TestSimulatePartialFill:
    """#74: simulate_partial_fill returns filled_quantity based on market depth."""

    def test_returns_at_most_requested_quantity(self):
        from paper import simulate_partial_fill

        for qty in [1, 10, 100]:
            filled = simulate_partial_fill(qty, market_depth_estimate=1000.0)
            assert filled <= qty

    def test_deep_market_fills_fully(self):
        from paper import simulate_partial_fill

        for _ in range(20):
            filled = simulate_partial_fill(10, market_depth_estimate=10_000.0)
            assert filled == 10

    def test_shallow_market_may_partially_fill(self):
        from paper import simulate_partial_fill

        results = [
            simulate_partial_fill(20, market_depth_estimate=10.0) for _ in range(30)
        ]
        assert any(r < 20 for r in results), "Expected at least some partial fills"

    def test_returns_integer(self):
        from paper import simulate_partial_fill

        result = simulate_partial_fill(50, market_depth_estimate=100.0)
        assert isinstance(result, int)

    def test_minimum_fill_is_one(self):
        from paper import simulate_partial_fill

        for _ in range(20):
            filled = simulate_partial_fill(5, market_depth_estimate=1.0)
            assert filled >= 1
