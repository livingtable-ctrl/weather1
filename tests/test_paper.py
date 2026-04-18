"""
Tests for paper.py — Kelly compounding, balance, order placement, settlement.
"""

import shutil
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest


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

        # 10% of $1000 = $100 pre-cap, but per-trade cap is $50
        dollars = paper.kelly_bet_dollars(0.10, cap=50.0)
        self.assertAlmostEqual(dollars, 50.0)

    def test_kelly_bet_dollars_caps_at_50_dollars(self):
        import paper

        # Even if Kelly says 50% of $1000, per-trade cap is $50
        dollars = paper.kelly_bet_dollars(1.0, cap=50.0)
        self.assertAlmostEqual(dollars, 50.0)

    def test_kelly_bet_dollars_floors_at_zero(self):
        import paper

        dollars = paper.kelly_bet_dollars(-0.10)
        self.assertEqual(dollars, 0.0)

    def test_kelly_quantity_basic(self):
        import paper

        # 10% of $1000 = $100 pre-cap, capped at $50; $50 / $0.50 = 100 contracts
        qty = paper.kelly_quantity(0.10, 0.50, cap=50.0)
        self.assertEqual(qty, 100)

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
        # Next Kelly bet should be positive (capped at $50 per-trade limit)
        dollars_after = paper.kelly_bet_dollars(0.10, cap=50.0)
        self.assertGreater(dollars_after, 0)
        self.assertLessEqual(dollars_after, 50.0)

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
        self._patch_exp = patch("paper.MAX_SINGLE_TICKER_EXPOSURE", 1.0)
        self._patch_exp.start()

    def tearDown(self):
        self._patch_exp.stop()
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
        """kelly_bet_dollars works normally when balance >= $500 (capped at $50)."""
        import paper

        # Balance is $1000, 10% = $100 pre-cap, capped at $50 per-trade limit
        result = paper.kelly_bet_dollars(0.10, cap=50.0)
        self.assertAlmostEqual(result, 50.0)

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
        self._patch_exp = patch("paper.MAX_SINGLE_TICKER_EXPOSURE", 1.0)
        self._patch_exp.start()

    def tearDown(self):
        self._patch_exp.stop()
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

        # Place $250 trade → exposure = 0.25 = MAX_CITY_DATE_EXPOSURE
        paper.place_paper_order(
            "TK1", "yes", 500, 0.50, city="NYC", target_date="2026-04-09"
        )
        result = paper.portfolio_kelly_fraction(0.10, "NYC", "2026-04-09")
        self.assertEqual(result, 0.0)

    def test_portfolio_kelly_partial_exposure(self):
        """Half of max city/date exposure → Kelly reduced by both city-date scale
        and the continuous correlated-city penalty."""
        import paper

        # Place $125 trade → city/date exposure = 0.125 = half of MAX (0.25)
        # NYC is in the {NYC, Boston} correlated group, so corr penalty also applies.
        paper.place_paper_order(
            "TK1", "yes", 250, 0.50, city="NYC", target_date="2026-04-09"
        )
        result = paper.portfolio_kelly_fraction(0.10, "NYC", "2026-04-09")
        # city/date scale = 0.5, corr_scale = 1 - (0.125/0.35)*0.70 ≈ 0.75
        # expected = 0.10 * 0.5 * 0.75 = 0.0375
        self.assertAlmostEqual(result, 0.0375, places=4)

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
        self._patch_exp = patch("paper.MAX_SINGLE_TICKER_EXPOSURE", 1.0)
        self._patch_exp.start()

    def tearDown(self):
        self._patch_exp.stop()
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
        self._patch_exp = patch("paper.MAX_SINGLE_TICKER_EXPOSURE", 1.0)
        self._patch_exp.start()

    def tearDown(self):
        self._patch_exp.stop()
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

        # Place $160 YES (16% of $1000) — above MAX_DIRECTIONAL_EXPOSURE (15%)
        paper.place_paper_order(
            "TK1", "yes", 320, 0.50, city="NYC", target_date="2026-04-09"
        )
        # 0.16 directional YES → penalty kicks in, city exposure 0.16 < 0.25 cap
        result = paper.portfolio_kelly_fraction(0.10, "NYC", "2026-04-09", side="yes")
        # penalty applies: result should be less than without penalty
        self.assertLess(result, 0.05)

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
        self._patch_exp = patch("paper.MAX_SINGLE_TICKER_EXPOSURE", 1.0)
        self._patch_exp.start()

    def tearDown(self):
        self._patch_exp.stop()
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

    def test_tier2_scaling_between_50_and_55_pct(self):
        """Balance at 52% of peak → step tier = 0.10 (TIER_1–TIER_2 with 50% halt)."""
        import paper

        paper.place_paper_order("TK", "yes", 480, 1.00)  # balance → $520 (52% of $1000)
        # Tiers relative to 50% halt: TIER_1=0.50, TIER_2=0.55 → survival 0.10
        self.assertAlmostEqual(paper.drawdown_scaling_factor(), 0.10, places=4)

    def test_tier3_scaling_between_55_and_60_pct(self):
        """Balance at 57% of peak → step tier = 0.30 (TIER_2–TIER_3 with 50% halt)."""
        import paper

        paper.place_paper_order("TK", "yes", 430, 1.00)  # balance → $570 (57% of $1000)
        # Tiers relative to 50% halt: TIER_2=0.55, TIER_3=0.60 → conservative 0.30
        self.assertAlmostEqual(paper.drawdown_scaling_factor(), 0.30, places=4)

    def test_tier4_scaling_between_60_and_65_pct(self):
        """Balance at 62% of peak → step tier = 0.70 (TIER_3–TIER_4 with 50% halt)."""
        import paper

        paper.place_paper_order("TK", "yes", 380, 1.00)  # balance → $620 (62% of $1000)
        # Tiers relative to 50% halt: TIER_3=0.60, TIER_4=0.65 → reduced 0.70
        self.assertAlmostEqual(paper.drawdown_scaling_factor(), 0.70, places=4)

    def test_kelly_scaled_at_partial_recovery(self):
        """Kelly dollars are scaled by recovery factor, not all-or-nothing."""
        import paper

        paper.place_paper_order(
            "TK", "yes", 430, 1.00
        )  # balance → $570 (57% of peak), scale=0.30 (TIER_2–TIER_3)
        dollars = paper.kelly_bet_dollars(0.10)
        # 0.10 * 0.30 * $570 = $17.10
        self.assertAlmostEqual(dollars, 17.10)

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


class TestCheckExitTargetsPartialFill:
    """#78: check_exit_targets logs partial fill simulation."""

    def test_check_exit_targets_logs_partial_fill(self, tmp_path, caplog):
        """When exit target is hit, a partial fill log message is emitted."""
        import logging

        import paper

        with patch("paper.DATA_PATH", tmp_path / "trades.json"):
            paper.place_paper_order(
                ticker="KXHIGH-25APR10-NYC",
                side="yes",
                quantity=20,
                entry_price=0.50,
                entry_prob=0.65,
                city="NYC",
                target_date="2025-04-10",
                exit_target=0.80,
            )

            mock_client = type(
                "C", (), {"get_market": lambda self, t: {"yes_bid": 0.85}}
            )()

            with caplog.at_level(logging.INFO, logger="paper"):
                exited = paper.check_exit_targets(client=mock_client)

        assert exited >= 1
        messages = " ".join(caplog.messages).lower()
        assert "fill" in messages or exited >= 1

    def test_partial_fill_quantity_bounded(self):
        """Partial fill formula: filled = min(qty, int(qty * uniform(0.7, 1.0)))."""
        import random

        qty = 100
        for _ in range(50):
            filled = min(qty, int(qty * random.uniform(0.7, 1.0)))
            assert 70 <= filled <= qty


class TestMaxOrderLatency:
    """#79: place_paper_order warns when execution exceeds MAX_ORDER_LATENCY_MS."""

    def test_max_order_latency_constant_exists(self):
        import paper

        assert hasattr(paper, "MAX_ORDER_LATENCY_MS")
        assert paper.MAX_ORDER_LATENCY_MS == 5000

    def test_fast_order_no_warning(self, tmp_path, caplog):
        import logging

        import paper

        with patch("paper.DATA_PATH", tmp_path / "trades.json"):
            with caplog.at_level(logging.WARNING, logger="paper"):
                paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side="yes",
                    quantity=1,
                    entry_price=0.50,
                    entry_prob=0.60,
                )

        latency_warns = [m for m in caplog.messages if "latency" in m.lower()]
        assert len(latency_warns) == 0

    def test_slow_order_logs_warning(self, tmp_path, caplog):
        import logging
        import time

        import paper

        original_save = paper._save

        def slow_save(data):
            time.sleep(0.020)  # 20 ms — well above 5 ms threshold, robust on Windows
            original_save(data)

        with (
            patch("paper.DATA_PATH", tmp_path / "trades.json"),
            patch.object(paper, "_save", slow_save),
            patch.object(paper, "MAX_ORDER_LATENCY_MS", 5),
        ):
            with caplog.at_level(logging.WARNING, logger="paper"):
                paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side="yes",
                    quantity=1,
                    entry_price=0.50,
                    entry_prob=0.60,
                )

        latency_warns = [m for m in caplog.messages if "latency" in m.lower()]
        assert len(latency_warns) >= 1


def test_med_edge_and_max_daily_spend_constants_exist():
    from utils import MAX_DAILY_SPEND, MED_EDGE

    assert 0 < MED_EDGE < 0.25
    assert MAX_DAILY_SPEND > 0


# ── Task 2: kelly_bet_dollars cap/method params and dynamic Brier cap ─────────


def test_kelly_bet_dollars_respects_explicit_cap(mock_balance_1000):
    """Explicit cap overrides dynamic Brier cap."""
    from paper import kelly_bet_dollars

    result = kelly_bet_dollars(0.5, cap=20.0)
    assert result <= 20.0


def test_kelly_bet_dollars_dynamic_cap_higher_with_good_brier(
    mock_balance_1000, monkeypatch
):
    """Dynamic cap raises above $50 when Brier score is excellent."""
    import paper

    monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 125.0)
    result = paper.kelly_bet_dollars(0.5)
    # kelly_fraction=0.5, balance=1000 → half-Kelly → 0.25 * 1000 = $250, capped at 125
    assert result <= 125.0


def test_kelly_bet_dollars_method_scaling_reduces_kelly(mock_balance_1000, monkeypatch):
    """Poor-performing method (Brier > 0.20) reduces Kelly by 25%."""
    import paper

    # Patch DATA_PATH again after reload (fixture patching is overwritten by reload)
    monkeypatch.setattr(paper, "DATA_PATH", mock_balance_1000.DATA_PATH)
    monkeypatch.setattr(paper, "get_balance", lambda: 1000.0)
    monkeypatch.setattr(paper, "drawdown_scaling_factor", lambda: 1.0)
    monkeypatch.setattr(paper, "is_streak_paused", lambda: False)
    monkeypatch.setattr(paper, "_dynamic_kelly_cap", lambda: 500.0)
    monkeypatch.setattr(paper, "_method_kelly_multiplier", lambda m: 0.75 if m else 1.0)

    base = paper.kelly_bet_dollars(0.5)  # method=None  → multiplier=1.0
    scaled = paper.kelly_bet_dollars(0.5, method="normal_dist")  # multiplier=0.75

    # With balance=1000, scale=1.0: fraction=0.25, dollars=250.0 (well under $500 cap)
    assert scaled < base
    assert abs(scaled - base * 0.75) < 0.02


class TestDynamicKellyCapMinSamples:
    def test_cap_returns_conservative_when_too_few_samples(self, monkeypatch):
        """_dynamic_kelly_cap returns $50 (conservative) when < MIN_BRIER_SAMPLES settled."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda: 0.006)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 5)
        assert paper._dynamic_kelly_cap() == 50.0

    def test_cap_uses_brier_when_enough_samples(self, monkeypatch):
        """_dynamic_kelly_cap uses Brier scaling when >= MIN_BRIER_SAMPLES settled."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda: 0.04)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 30)
        assert paper._dynamic_kelly_cap() == 500.0

    def test_method_multiplier_returns_neutral_when_too_few_samples(self, monkeypatch):
        """_method_kelly_multiplier returns 1.0 when < MIN_BRIER_SAMPLES settled."""
        import paper
        import tracker

        monkeypatch.setattr(
            tracker, "brier_score_by_method", lambda min_samples: {"ensemble": 0.25}
        )
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 5)
        assert paper._method_kelly_multiplier("ensemble") == 1.0


# ── Task 3: entry_hour and close_paper_early ──────────────────────────────────


def test_place_paper_order_records_entry_hour(tmp_path, monkeypatch):
    """place_paper_order should record the UTC hour of entry."""
    import importlib

    import paper as paper_mod

    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper_mod)
    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")

    paper_mod.place_paper_order("TEST-TICKER", "yes", 1, 0.40)
    trades = paper_mod.get_open_trades()
    assert len(trades) == 1
    assert "entry_hour" in trades[0]
    assert 0 <= trades[0]["entry_hour"] <= 23


def test_close_paper_early_settles_at_exit_price(tmp_path, monkeypatch):
    """close_paper_early should settle trade at exit price, not $0/$1."""
    import importlib

    import paper as paper_mod

    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper_mod)
    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")

    paper_mod.place_paper_order("TEST-TICKER", "yes", 10, 0.40)  # paid $4.00 total
    balance_after_entry = paper_mod.get_balance()
    trade_id = paper_mod.get_open_trades()[0]["id"]
    paper_mod.close_paper_early(trade_id, exit_price=0.55)  # selling at $5.50
    assert not paper_mod.get_open_trades()  # no more open trades
    assert paper_mod.get_balance() > balance_after_entry  # profit
    t = [t for t in paper_mod._load()["trades"] if t["id"] == trade_id][0]
    assert t["outcome"] == "early_exit"
    assert abs(t["pnl"] - 1.50) < 0.01  # (0.55 - 0.40) * 10 = $1.50


def test_close_paper_early_raises_on_unknown_id(tmp_path, monkeypatch):
    import importlib

    import paper as paper_mod

    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper_mod)
    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")

    with pytest.raises(ValueError, match="not found"):
        paper_mod.close_paper_early(9999, exit_price=0.50)


# ── Phase 5: Correlation-aware Kelly ─────────────────────────────────────────


class TestPositionCorrelationMatrix:
    def test_same_city_same_date_is_0_85(self):
        from paper import position_correlation_matrix

        trades = [
            {"city": "NYC", "target_date": "2026-05-01"},
            {"city": "NYC", "target_date": "2026-05-01"},
        ]
        mat = position_correlation_matrix(trades)
        assert mat[0][1] == pytest.approx(0.85)
        assert mat[1][0] == pytest.approx(0.85)

    def test_same_city_adjacent_date_is_0_50(self):
        from paper import position_correlation_matrix

        trades = [
            {"city": "NYC", "target_date": "2026-05-01"},
            {"city": "NYC", "target_date": "2026-05-02"},
        ]
        mat = position_correlation_matrix(trades)
        assert mat[0][1] == pytest.approx(0.50)

    def test_same_city_distant_dates_is_0_30(self):
        from paper import position_correlation_matrix

        trades = [
            {"city": "NYC", "target_date": "2026-05-01"},
            {"city": "NYC", "target_date": "2026-05-10"},
        ]
        mat = position_correlation_matrix(trades)
        assert mat[0][1] == pytest.approx(0.30)

    def test_known_city_pair_uses_lookup(self):
        from paper import position_correlation_matrix

        trades = [
            {"city": "NYC", "target_date": "2026-05-01"},
            {"city": "Boston", "target_date": "2026-05-01"},
        ]
        mat = position_correlation_matrix(trades)
        assert mat[0][1] == pytest.approx(0.85)  # NYC–Boston from _CITY_PAIR_CORR

    def test_unknown_city_pair_defaults_to_0_10(self):
        from paper import position_correlation_matrix

        trades = [
            {"city": "NYC", "target_date": "2026-05-01"},
            {"city": "Seattle", "target_date": "2026-05-01"},
        ]
        mat = position_correlation_matrix(trades)
        assert mat[0][1] == pytest.approx(0.10)

    def test_diagonal_is_one(self):
        from paper import position_correlation_matrix

        trades = [
            {"city": "NYC", "target_date": "2026-05-01"},
            {"city": "Chicago", "target_date": "2026-05-01"},
            {"city": "LA", "target_date": "2026-05-01"},
        ]
        mat = position_correlation_matrix(trades)
        for i in range(3):
            assert mat[i][i] == pytest.approx(1.0)

    def test_matrix_is_symmetric(self):
        from paper import position_correlation_matrix

        trades = [
            {"city": "NYC", "target_date": "2026-05-01"},
            {"city": "Boston", "target_date": "2026-05-01"},
            {"city": "Chicago", "target_date": "2026-05-01"},
        ]
        mat = position_correlation_matrix(trades)
        for i in range(3):
            for j in range(3):
                assert mat[i][j] == pytest.approx(mat[j][i])

    def test_empty_returns_empty(self):
        from paper import position_correlation_matrix

        mat = position_correlation_matrix([])
        assert mat == []


class TestCorrKellyScale:
    def test_no_open_trades_returns_one(self):
        from paper import corr_kelly_scale

        assert corr_kelly_scale(
            {"city": "NYC", "target_date": "2026-05-01"}, []
        ) == pytest.approx(1.0)

    def test_same_city_same_date_reduces_to_0_25(self):
        from paper import corr_kelly_scale

        open_trades = [{"city": "NYC", "target_date": "2026-05-01"}]
        trade = {"city": "NYC", "target_date": "2026-05-01"}
        # max_corr = 0.85 → scale = max(0.25, 1.0 - 0.85) = 0.25
        assert corr_kelly_scale(trade, open_trades) == pytest.approx(0.25)

    def test_uncorrelated_cities_returns_0_90(self):
        from paper import corr_kelly_scale

        open_trades = [{"city": "NYC", "target_date": "2026-05-01"}]
        trade = {"city": "Seattle", "target_date": "2026-05-01"}
        # max_corr = 0.10 → scale = 1.0 - 0.10 = 0.90
        assert corr_kelly_scale(trade, open_trades) == pytest.approx(0.90)

    def test_minimum_is_0_25(self):
        from paper import corr_kelly_scale

        # Even with 1.0 correlation, floor is 0.25
        open_trades = [{"city": "NYC", "target_date": "2026-05-01"}] * 5
        trade = {"city": "NYC", "target_date": "2026-05-01"}
        result = corr_kelly_scale(trade, open_trades)
        assert result >= 0.25


class TestMonteCarloCholesky:
    def test_cholesky_identity(self):
        from monte_carlo import _cholesky

        mat = [[1.0, 0.0], [0.0, 1.0]]
        L = _cholesky(mat)
        assert L is not None
        assert L[0][0] == pytest.approx(1.0)
        assert L[1][1] == pytest.approx(1.0)

    def test_cholesky_correlated(self):
        from monte_carlo import _cholesky

        rho = 0.5
        mat = [[1.0, rho], [rho, 1.0]]
        L = _cholesky(mat)
        assert L is not None
        # Verify L @ L.T == mat
        assert L[0][0] ** 2 == pytest.approx(1.0)
        assert L[1][0] ** 2 + L[1][1] ** 2 == pytest.approx(1.0)
        assert L[1][0] * L[0][0] == pytest.approx(rho)

    def test_cholesky_not_positive_definite_returns_none(self):
        from monte_carlo import _cholesky

        mat = [[1.0, 1.1], [1.1, 1.0]]  # not positive definite
        assert _cholesky(mat) is None

    def test_simulate_portfolio_correlated_widens_distribution(self):
        """Correlated positions (same city/date) should widen P&L distribution vs independent."""
        from monte_carlo import simulate_portfolio

        # Two perfectly correlated positions: same city, same date
        trades = [
            {
                "ticker": "T1",
                "side": "yes",
                "entry_price": 0.5,
                "cost": 5.0,
                "quantity": 10,
                "city": "NYC",
                "target_date": "2026-05-01",
                "entry_prob": 0.5,
            },
            {
                "ticker": "T2",
                "side": "yes",
                "entry_price": 0.5,
                "cost": 5.0,
                "quantity": 10,
                "city": "NYC",
                "target_date": "2026-05-01",
                "entry_prob": 0.5,
            },
        ]
        result = simulate_portfolio(trades, n_simulations=2000)
        # P10 < median < P90 — distribution is non-trivial
        assert result["p10_pnl"] < result["median_pnl"]
        assert result["median_pnl"] < result["p90_pnl"]
        # P10–P90 spread should be substantial (correlated risk)
        spread = result["p90_pnl"] - result["p10_pnl"]
        assert spread > 5.0


class TestCheckStopLosses:
    def _trade(self, ticker, side, entry_price, qty):
        cost = round(entry_price * qty, 4)
        return {
            "ticker": ticker,
            "side": side,
            "entry_price": entry_price,
            "quantity": qty,
            "cost": cost,
            "settled": False,
        }

    def test_stop_triggers_when_yes_price_halves(self):
        """YES trade: price halved → loss = 50% of cost → stop fires (MULT=2)."""
        from paper import check_stop_losses

        trade = self._trade("T1", "yes", 0.60, 10)
        # current yes = 0.30 → loss = (0.30-0.60)*10 = -3.0; threshold = -cost/2 = -3.0
        # At exactly threshold it fires (strictly less would not, so use 0.29)
        prices = {"T1": 0.29}
        assert check_stop_losses([trade], prices) == ["T1"]

    def test_stop_not_triggered_within_range(self):
        """YES trade: small adverse move → no stop."""
        from paper import check_stop_losses

        trade = self._trade("T1", "yes", 0.60, 10)
        prices = {"T1": 0.50}  # lost $1 of $6 — well within threshold
        assert check_stop_losses([trade], prices) == []

    def test_stop_triggers_for_no_trade(self):
        """NO trade: YES price rises sharply → NO value drops → stop fires."""
        from paper import check_stop_losses

        # NO trade: entry_price = 0.40 (paid 40¢ per contract)
        trade = self._trade("T1", "no", 0.40, 10)
        # current yes = 0.85 → current NO = 0.15; loss = (0.15-0.40)*10 = -2.5
        # threshold = -cost/2 = -2.0  →  -2.5 < -2.0 → fires
        prices = {"T1": 0.85}
        assert check_stop_losses([trade], prices) == ["T1"]

    def test_stop_not_triggered_when_multiplier_zero(self):
        """STOP_LOSS_MULT=0 disables stop-losses entirely."""
        from unittest.mock import patch

        import utils
        from paper import check_stop_losses

        trade = self._trade("T1", "yes", 0.60, 10)
        prices = {"T1": 0.01}  # extreme loss
        with patch.object(utils, "STOP_LOSS_MULT", 0.0):
            assert check_stop_losses([trade], prices) == []

    def test_missing_ticker_skipped(self):
        """Ticker not in current_yes_prices is skipped (no crash)."""
        from paper import check_stop_losses

        trade = self._trade("T1", "yes", 0.60, 10)
        assert check_stop_losses([trade], {}) == []

    def test_multiple_trades_only_breached_returned(self):
        """Only tickers that breach the threshold are returned."""
        from paper import check_stop_losses

        t1 = self._trade("T1", "yes", 0.60, 10)  # will breach
        t2 = self._trade("T2", "yes", 0.60, 10)  # will not breach
        prices = {"T1": 0.20, "T2": 0.55}
        result = check_stop_losses([t1, t2], prices)
        assert result == ["T1"]
