"""
Tests for paper.py — Kelly compounding, balance, order placement, settlement.
"""

import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
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

    def test_kelly_quantity_no_truncation_to_zero(self):
        """L8-B: int() truncation silently gave 0 when dollars < price.

        Scenario: cap forces dollars=$0.50, price=$0.65/contract.
        dollars/price = 0.769 → int()=0 (BUG), round()=1 (fixed).

        Must pass min_dollars=0.40 explicitly so the min_dollars gate
        doesn't fire before we reach the truncation.
        """
        import paper

        # dollars=$0.50 (from cap), price=$0.65 → ratio=0.769
        # int(0.769)=0 (bug), round(0.769)=1 (fix)
        qty = paper.kelly_quantity(0.10, price=0.65, cap=0.50, min_dollars=0.40)
        self.assertGreaterEqual(
            qty,
            1,
            "kelly_quantity must return ≥1 after min_dollars gate — int() truncation bug",
        )

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

    def test_current_api_volume_fp_prevents_false_stale(self):
        # Real bug found 2026-07-19 (backlog.txt "is_liquid() ONLY READS
        # LEGACY volume/open_interest FIELD NAMES" -- same gap found by
        # adjacency in is_stale()): a market closing soon with real
        # volume_fp but no legacy volume/open_interest must NOT be called
        # stale -- a plain-names-only read would have silently skipped
        # every near-close market on the live API regardless of real
        # liquidity.
        from datetime import datetime, timedelta

        from weather_markets import is_stale

        close = (datetime.now(UTC) + timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        market = {"volume_fp": 500, "close_time": close}
        self.assertFalse(is_stale(market))

    def test_current_api_open_interest_fp_prevents_false_stale(self):
        from datetime import datetime, timedelta

        from weather_markets import is_stale

        close = (datetime.now(UTC) + timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        market = {"open_interest_fp": 500, "close_time": close}
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

    def test_boundary_exactly_800_not_paused(self):
        """Balance exactly at $800 (= 80% of $1000, 20% halt) is NOT paused (strict less-than)."""
        import paper

        paper.place_paper_order("TK", "yes", 200, 1.00)  # cost=$200 → balance=$800
        self.assertFalse(paper.is_paused_drawdown())

    def test_effective_balance_adds_back_same_day_cost(self):
        """get_effective_balance() adds back open same-day trade costs."""
        import paper

        paper.place_paper_order("SD1", "no", 18, 1.00, days_out=0)  # cost=$18
        eff = paper.get_effective_balance()
        bal = paper.get_balance()
        self.assertAlmostEqual(eff, bal + 18.0, places=2)

    def test_effective_balance_ignores_multiday_cost(self):
        """get_effective_balance() does NOT add back multi-day trade costs."""
        import paper

        paper.place_paper_order("MD1", "no", 18, 1.00, days_out=1)  # multi-day
        eff = paper.get_effective_balance()
        bal = paper.get_balance()
        self.assertAlmostEqual(eff, bal, places=2)

    def test_paused_drawdown_ignores_same_day_costs(self):
        """is_paused_drawdown() stays False when balance dips below halt only due
        to open same-day costs — effective balance is still above the floor."""
        import paper

        # Drain to just above the 20% halt floor ($800), then add a same-day cost
        # that would push actual balance below $800 but effective balance stays above.
        paper.place_paper_order("BIG", "yes", 190, 1.00)  # balance → $810
        paper.place_paper_order("SD2", "no", 15, 1.00, days_out=0)  # balance → $795
        self.assertFalse(
            paper.is_paused_drawdown()
        )  # effective = $795 + $15 = $810 > $800

    def test_reset_peak_sets_to_current_balance(self):
        """reset_peak_balance() resets peak to current balance, preserving trades."""
        import paper

        paper.place_paper_order("TK", "yes", 100, 1.00)  # balance → $900
        paper.settle_paper_trade(
            paper.get_open_trades()[0]["id"], False
        )  # loss → $900-$100
        # peak is still $1000; reset it
        new_peak = paper.reset_peak_balance(reason="test", confirmed=True)
        self.assertAlmostEqual(new_peak, paper.get_balance(), places=2)
        self.assertAlmostEqual(paper.get_peak_balance(), paper.get_balance(), places=2)
        # trade history preserved
        self.assertEqual(len(paper.get_all_trades()), 1)

    def test_reset_peak_requires_confirmed(self):
        """reset_peak_balance() raises ValueError without confirmed=True."""
        import paper

        with self.assertRaises(ValueError):
            paper.reset_peak_balance(reason="test")

    def test_max_drawdown_pct_uses_actual_balance(self):
        """get_max_drawdown_pct() uses actual balance for reporting — same-day
        open costs are not added back (performance metric, not trading decision)."""
        import paper

        paper.place_paper_order("BIG", "yes", 150, 1.00)  # balance → $850
        paper.place_paper_order("SD3", "no", 30, 1.00, days_out=0)  # balance → $820
        # actual balance = $820; drawdown = (1000 - 820) / 1000 = 0.18
        pct = paper.get_max_drawdown_pct()
        self.assertAlmostEqual(pct, 0.18, places=2)
        # effective balance would give 0.15 — reporting intentionally shows the higher value
        self.assertGreater(pct, paper.get_effective_balance() / 1000 - 1 + pct)

    def test_needs_manual_settle_excluded_from_effective_balance(self):
        """Same-day trades marked needs_manual_settle are excluded from effective
        balance — they will never settle and should not permanently inflate it."""
        import paper

        trade = paper.place_paper_order("SD4", "no", 20, 1.00, days_out=0)
        paper._mark_needs_manual_settle(trade["id"])
        # needs_manual_settle trade should NOT be added back
        self.assertAlmostEqual(
            paper.get_effective_balance(), paper.get_balance(), places=2
        )


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

    # ── L3-A: portfolio-level Kelly cap tests ────────────────────────────────

    def test_l3a_kelly_clamped_to_remaining_room(self):
        """L3-A: when portfolio is 80% full, a 20% Kelly is clamped to 10% (remaining room).

        Before L3-A fix, portfolio_kelly_fraction returned the full city/date-scaled
        Kelly even when total exposure was 40%. Adding a 20% trade would push total
        to 60%, exceeding MAX_TOTAL_OPEN_EXPOSURE=50% with no push-back.
        """
        import paper

        # Place $400 trade → total exposure = 0.40 (80% of 0.50 cap)
        # Use a different city so city/date scaling doesn't interfere
        paper.place_paper_order(
            "TK_CHI", "yes", 800, 0.50, city="Chicago", target_date="2026-05-01"
        )
        total_exp = paper.get_total_exposure()
        self.assertAlmostEqual(total_exp, 0.40, places=3)

        # Request Kelly=0.20 for a new NYC trade; remaining room = 0.50 - 0.40 = 0.10
        result = paper.portfolio_kelly_fraction(0.20, "NYC", "2026-05-02")

        # L3-A invariant: result must be ≤ remaining room (0.10), not 0.20
        self.assertLessEqual(
            result,
            0.10 + 1e-6,
            f"Kelly {result:.4f} must be clamped to remaining room 0.10 "
            "when portfolio exposure is 0.40",
        )
        self.assertGreater(result, 0.0, "Some Kelly must be returned when room exists")

    def test_l3a_no_city_context_also_clamped(self):
        """L3-A: even with no city/date context, result is clamped to remaining room."""
        import paper

        # Place $400 trade → 40% exposure; remaining room = 10%
        paper.place_paper_order(
            "TK_CHI", "yes", 800, 0.50, city="Chicago", target_date="2026-05-01"
        )

        # No city/date → previously passed base_fraction through unchanged (0.20)
        result = paper.portfolio_kelly_fraction(0.20, None, None)

        self.assertLessEqual(
            result,
            0.10 + 1e-6,
            f"No-city Kelly {result:.4f} must be clamped to remaining room 0.10",
        )

    def test_l3a_sum_of_independent_kellys_bounded(self):
        """L3-A: placing N independent city/date trades cannot push total Kelly sum past cap.

        This is the core invariant: 10 positions each with base_fraction=0.10 must
        NOT collectively commit more than MAX_TOTAL_OPEN_EXPOSURE of the bankroll.
        """
        import paper

        cities = [
            ("NYC", "2026-05-01"),
            ("Chicago", "2026-05-02"),
            ("LA", "2026-05-03"),
            ("Miami", "2026-05-04"),
            ("Dallas", "2026-05-05"),
            ("Denver", "2026-05-06"),
            ("Boston", "2026-05-07"),
            ("Phoenix", "2026-05-08"),
        ]
        total_committed_kelly = 0.0
        for city, date in cities:
            adj = paper.portfolio_kelly_fraction(0.10, city, date)
            if adj > 0:
                # Simulate placing the trade: cost = adj * STARTING_BALANCE
                cost = adj * paper.STARTING_BALANCE
                qty = max(1, round(cost / 0.50))
                try:
                    paper.place_paper_order(
                        f"TK_{city}", "yes", qty, 0.50, city=city, target_date=date
                    )
                    total_committed_kelly += adj
                except ValueError:
                    break  # balance too low — stop

        total_exp = paper.get_total_exposure()
        self.assertLessEqual(
            total_exp,
            paper.MAX_TOTAL_OPEN_EXPOSURE + 0.01,  # 1% tolerance for rounding
            f"Total exposure {total_exp:.4f} must not exceed MAX_TOTAL_OPEN_EXPOSURE "
            f"{paper.MAX_TOTAL_OPEN_EXPOSURE} after N independent trades",
        )


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

    def test_export_trades_csv_handles_heterogeneous_schema(self):
        """An older trade record (fewer keys, simulating a pre-field JSON row)
        must not crash the export when a later trade has extra keys, and no
        trade's fields may be silently dropped from the CSV (backlog.txt
        review-adjacency note on the 2026-07-19 exit_target deletion:
        trades[0].keys() alone crashes DictWriter's default
        extrasaction='raise' the moment trades[0] is missing a key a later
        trade has)."""
        import csv

        import paper

        paper.place_paper_order(
            "TKOLD", "yes", 10, 0.50, city="NYC", target_date="2026-04-09"
        )
        paper.place_paper_order(
            "TKNEW", "no", 5, 0.60, city="CHI", target_date="2026-04-10"
        )
        # Simulate schema drift directly on disk: strip a field from the
        # oldest trade (as a real pre-field JSON row would lack it) and add
        # a field only the newest trade has (as a future schema addition
        # would look before every old row is ever touched again).
        data = paper._load()
        del data["trades"][0]["thesis"]
        data["trades"][1]["brand_new_future_field"] = "only on the newest trade"
        paper._save(data)

        out_path = str(Path(self._tmpdir) / "trades.csv")
        n = paper.export_trades_csv(out_path)  # must not raise
        self.assertEqual(n, 2)

        with open(out_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        self.assertIn(
            "brand_new_future_field",
            fieldnames,
            "a field only the newest trade has must still get its own column",
        )
        self.assertIn(
            "thesis",
            fieldnames,
            "a field missing from the oldest trade must still get a column "
            "(from a later trade that has it), not be dropped entirely",
        )
        self.assertEqual(
            rows[0]["thesis"],
            "",
            "the oldest trade's missing field must render as an empty cell, not crash",
        )
        self.assertEqual(rows[1]["brand_new_future_field"], "only on the newest trade")


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

    def test_zero_scaling_below_20_pct(self):
        """Below 20% of peak → scale = 0.0 (fully paused)."""
        import paper

        paper.place_paper_order("TK", "yes", 250, 1.00)  # balance → $750 (75% of $1000)
        self.assertEqual(paper.drawdown_scaling_factor(), 0.0)

    def test_tier2_scaling_between_80_and_85_pct(self):
        """Balance at 82% of peak → step tier = 0.10 (TIER_1–TIER_2 with 20% halt)."""
        import paper

        paper.place_paper_order("TK", "yes", 180, 1.00)  # balance → $820 (82% of $1000)
        # Tiers relative to 20% halt: TIER_1=0.80, TIER_2=0.85 → survival 0.10
        self.assertAlmostEqual(paper.drawdown_scaling_factor(), 0.10, places=4)

    def test_tier3_scaling_between_85_and_90_pct(self):
        """Balance at 87% of peak → step tier = 0.30 (TIER_2–TIER_3 with 20% halt)."""
        import paper

        paper.place_paper_order("TK", "yes", 130, 1.00)  # balance → $870 (87% of $1000)
        # Tiers relative to 20% halt: TIER_2=0.85, TIER_3=0.90 → conservative 0.30
        self.assertAlmostEqual(paper.drawdown_scaling_factor(), 0.30, places=4)

    def test_tier4_scaling_between_90_and_95_pct(self):
        """Balance at 92% of peak → step tier = 0.70 (TIER_3–TIER_4 with 20% halt)."""
        import paper

        paper.place_paper_order("TK", "yes", 80, 1.00)  # balance → $920 (92% of $1000)
        # Tiers relative to 20% halt: TIER_3=0.90, TIER_4=0.95 → reduced 0.70
        self.assertAlmostEqual(paper.drawdown_scaling_factor(), 0.70, places=4)

    def test_kelly_scaled_at_partial_recovery(self):
        """Kelly dollars are scaled by recovery factor, not all-or-nothing."""
        import paper

        paper.place_paper_order(
            "TK", "yes", 130, 1.00
        )  # balance → $870 (87% of peak), scale=0.30 (TIER_2–TIER_3)
        dollars = paper.kelly_bet_dollars(0.10)
        # 0.10 * 0.30 * $870 = $26.10
        self.assertAlmostEqual(dollars, 26.10)

    def test_kelly_zero_below_20_pct(self):
        """Kelly still returns 0.0 when fully in drawdown (scale=0.0)."""
        import paper

        paper.place_paper_order("TK", "yes", 250, 1.00)  # balance → $750 (75%)
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
        self.assertEqual(len(settled), 1)
        open_trades = paper.get_open_trades()
        self.assertEqual(len(open_trades), 0)

    def test_auto_settle_skips_no_outcome(self):
        """auto_settle_paper_trades() leaves trades open when no outcome recorded."""
        import paper

        paper.place_paper_order("TKPENDING", "yes", 10, 0.50)
        settled = paper.auto_settle_paper_trades()
        self.assertEqual(len(settled), 0)
        self.assertEqual(len(paper.get_open_trades()), 1)

    def test_get_outcome_for_ticker_returns_none_when_missing(self):
        import tracker

        result = tracker.get_outcome_for_ticker("NOTEXIST")
        self.assertIsNone(result)

    def test_no_side_win_recorded_as_win(self):
        """NO-side trade that wins (outcome=NO) must be settled as a win, not a loss."""
        import paper

        trade = paper.place_paper_order("TKNO", "no", 10, 0.40)
        balance_before = paper.get_balance()
        # Outcome is NO (outcome_yes=False) → NO-holder wins
        paper.settle_paper_trade(trade["id"], outcome_yes=False)
        result = [t for t in paper._load()["trades"] if t["id"] == trade["id"]][0]
        self.assertTrue(result["settled"])
        self.assertGreater(result["pnl"], 0, "NO-side win must have positive P&L")
        self.assertGreater(paper.get_balance(), balance_before)

    def test_no_side_loss_recorded_as_loss(self):
        """NO-side trade that loses (outcome=YES) must have zero payout."""
        import paper

        trade = paper.place_paper_order("TKNOL", "no", 10, 0.40)
        balance_before = paper.get_balance()
        # Outcome is YES (outcome_yes=True) → NO-holder loses
        paper.settle_paper_trade(trade["id"], outcome_yes=True)
        result = [t for t in paper._load()["trades"] if t["id"] == trade["id"]][0]
        self.assertTrue(result["settled"])
        self.assertLess(result["pnl"], 0, "NO-side loss must have negative P&L")
        # Cost was already deducted at order time; on a loss payout=0, balance unchanged
        self.assertEqual(paper.get_balance(), balance_before)

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


def test_close_paper_early_records_exit_reason(tmp_path, monkeypatch):
    import importlib

    import paper as paper_mod

    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper_mod)
    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")

    paper_mod.place_paper_order("TEST-TICKER", "yes", 10, 0.40)
    trade_id = paper_mod.get_open_trades()[0]["id"]
    paper_mod.close_paper_early(trade_id, exit_price=0.20, reason="stop_loss")
    t = [t for t in paper_mod._load()["trades"] if t["id"] == trade_id][0]
    assert t["exit_reason"] == "stop_loss"
    assert t["outcome"] == "early_exit"  # unchanged existing semantics


def test_close_paper_early_exit_reason_defaults_to_none(tmp_path, monkeypatch):
    """Callers that don't pass reason= (the majority) must not be miscounted
    as stop-loss exits by get_stop_loss_accuracy()."""
    import importlib

    import paper as paper_mod

    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper_mod)
    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")

    paper_mod.place_paper_order("TEST-TICKER", "yes", 10, 0.40)
    trade_id = paper_mod.get_open_trades()[0]["id"]
    paper_mod.close_paper_early(trade_id, exit_price=0.55)
    t = [t for t in paper_mod._load()["trades"] if t["id"] == trade_id][0]
    assert t.get("exit_reason") is None


def test_get_stop_loss_accuracy_filters_to_stop_loss_reason(tmp_path, monkeypatch):
    """paper.get_stop_loss_accuracy() must only pass stop_loss-tagged exits to
    tracker's scoring join -- a breakeven or model-exit close must not count."""
    import importlib

    import paper as paper_mod

    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper_mod)
    monkeypatch.setattr(paper_mod, "DATA_PATH", tmp_path / "paper_trades.json")

    paper_mod.place_paper_order("SL-TICKER", "yes", 10, 0.40)
    paper_mod.place_paper_order("BE-TICKER", "yes", 10, 0.40)
    trades = paper_mod.get_open_trades()
    sl_id = next(t["id"] for t in trades if t["ticker"] == "SL-TICKER")
    be_id = next(t["id"] for t in trades if t["ticker"] == "BE-TICKER")
    paper_mod.close_paper_early(sl_id, exit_price=0.20, reason="stop_loss")
    paper_mod.close_paper_early(be_id, exit_price=0.40, reason="breakeven")

    captured = {}

    def fake_tracker_call(sl_trades):
        captured["tickers"] = [t["ticker"] for t in sl_trades]
        return {"total": 0, "saved_money": 0, "exited_winner": 0, "avg_saving": 0.0}

    import tracker as tracker_mod

    monkeypatch.setattr(tracker_mod, "get_stop_loss_accuracy", fake_tracker_call)
    paper_mod.get_stop_loss_accuracy()
    assert captured["tickers"] == ["SL-TICKER"]


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


class TestLiquidityKellyScale:
    """backlog.txt "LIQUIDITY-AWARE SIZING + DYNAMIC EDGE THRESHOLD" -- revives
    the 2026-07-12-deleted paper.slippage_kelly_scale's exact tier shape."""

    def test_liquid_market_returns_1_0(self):
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume": 400, "open_interest": 200}
        ) == pytest.approx(1.00)

    def test_medium_liquidity_returns_0_85(self):
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume": 250, "open_interest": 100}
        ) == pytest.approx(0.85)

    def test_low_liquidity_returns_0_70(self):
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume": 60, "open_interest": 20}
        ) == pytest.approx(0.70)

    def test_illiquid_market_returns_0_50(self):
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume": 10, "open_interest": 5}
        ) == pytest.approx(0.50)

    def test_zero_liquidity_returns_0_50(self):
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume": 0, "open_interest": 0}
        ) == pytest.approx(0.50)

    def test_missing_fields_treated_as_zero_not_typeerror(self):
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale({}) == pytest.approx(0.50)

    def test_volume_and_open_interest_are_summed_not_maxed(self):
        # 300 volume alone (below the 500 floor) plus 300 OI alone (also
        # below) sum to 600 -- must land in the liquid tier, proving the two
        # fields are summed together, not compared/maxed independently.
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume": 300, "open_interest": 300}
        ) == pytest.approx(1.00)

    def test_tier_boundaries_are_strict_greater_than(self):
        # Exactly at a boundary falls into the LOWER tier (> not >=), matching
        # the deleted original's exact comparison operators.
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume": 500, "open_interest": 0}
        ) == pytest.approx(0.85)
        assert liquidity_kelly_scale(
            {"volume": 200, "open_interest": 0}
        ) == pytest.approx(0.70)
        assert liquidity_kelly_scale(
            {"volume": 50, "open_interest": 0}
        ) == pytest.approx(0.50)

    def test_current_api_fp_field_names_are_read(self):
        # Real bug caught by opus review before this shipped: the current
        # Kalshi API returns volume_fp/open_interest_fp, not the legacy
        # volume/open_interest -- a market carrying ONLY the _fp names must
        # not silently fall through to the worst-case 0.50 tier the way a
        # plain-names-only read would.
        from paper import liquidity_kelly_scale

        assert liquidity_kelly_scale(
            {"volume_fp": 2000, "open_interest_fp": 3000}
        ) == pytest.approx(1.00)

    def test_fp_field_names_preferred_over_legacy_when_both_present(self):
        from paper import liquidity_kelly_scale

        # Legacy fields alone would give liq=600 (liquid tier); _fp fields
        # alone would give liq=20 (illiquid tier). Confirms _fp takes
        # priority when both keys exist on the same dict, matching
        # analyze_trade()'s own liquidity gate precedence.
        assert liquidity_kelly_scale(
            {
                "volume": 300,
                "open_interest": 300,
                "volume_fp": 10,
                "open_interest_fp": 10,
            }
        ) == pytest.approx(0.50)


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
        from datetime import date, timedelta

        from monte_carlo import simulate_portfolio

        future = (date.today() + timedelta(days=1)).isoformat()
        # Two perfectly correlated positions: same city, same date
        trades = [
            {
                "ticker": "T1",
                "side": "yes",
                "entry_price": 0.5,
                "cost": 5.0,
                "quantity": 10,
                "city": "NYC",
                "target_date": future,
                "entry_prob": 0.5,
            },
            {
                "ticker": "T2",
                "side": "yes",
                "entry_price": 0.5,
                "cost": 5.0,
                "quantity": 10,
                "city": "NYC",
                "target_date": future,
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

    def test_past_date_trade_excluded_from_simulation(self):
        """Trades whose target_date is in the past are skipped — no forward risk."""
        from datetime import timedelta

        from monte_carlo import simulate_portfolio
        from utils import utc_today

        # simulate_portfolio compares target_date against utils.utc_today(),
        # not local wall-clock date — using local date.today() here can
        # silently disagree with it (e.g. local date already a day ahead of
        # UTC makes "yesterday, local" equal today in UTC, so the skip never
        # fires and the trade wrongly falls through to the clamping path).
        today = utc_today()
        past = (today - timedelta(days=1)).isoformat()
        future = (today + timedelta(days=1)).isoformat()

        stale_trade = {
            "ticker": "KXSTALE-PAST",
            "side": "yes",
            "entry_price": 0.43,
            "cost": 4.73,
            "quantity": 11,
            "city": "Phoenix",
            "target_date": past,
            "entry_prob": 0.929,  # would trigger clamp warning if not skipped
        }
        future_trade = {
            "ticker": "KXFUTURE",
            "side": "yes",
            "entry_price": 0.50,
            "cost": 5.00,
            "quantity": 10,
            "city": "Dallas",
            "target_date": future,
            "entry_prob": 0.55,
        }

        result = simulate_portfolio([stale_trade, future_trade], n_simulations=200)

        # Stale trade must be skipped entirely — n_clamped==0 proves it wasn't
        # processed through the clamping path (entry_prob=0.929 would have fired).
        assert result["n_clamped"] == 0, (
            f"Stale trade should be skipped before clamping, got n_clamped={result['n_clamped']}"
        )
        # Result should reflect only the future trade (non-trivial distribution)
        assert result["p10_pnl"] < result["p90_pnl"]

    def test_past_date_only_portfolio_returns_empty_result(self):
        """All-stale portfolio skips every trade and returns the zero-position result."""
        from datetime import timedelta

        from monte_carlo import simulate_portfolio
        from utils import utc_today

        # See test_past_date_trade_excluded_from_simulation's comment above —
        # must compare against the same UTC reference simulate_portfolio uses.
        past = (utc_today() - timedelta(days=2)).isoformat()
        stale = {
            "ticker": "KXSTALE",
            "side": "yes",
            "entry_price": 0.50,
            "cost": 5.00,
            "quantity": 10,
            "city": "Phoenix",
            "target_date": past,
            "entry_prob": 0.929,
        }

        result = simulate_portfolio([stale], n_simulations=200)
        # Should behave like an empty portfolio
        assert result["median_pnl"] == 0.0
        assert result["prob_ruin"] == 0.0


def _flat_prices(prices: dict) -> dict:
    """Convert {ticker: yes_price} to the {ticker: {"bid":..., "ask":...}}
    shape check_stop_losses/update_peak_profits/check_breakeven_stops now
    take (#3) — zero spread (bid==ask) preserves these tests' original
    single-price semantics exactly."""
    return {t: {"bid": p, "ask": p} for t, p in prices.items()}


class TestLiquidationPriceZeroSide:
    """Deep-review followup: parse_market_price() coalesces a missing side
    to 0.0 (never None) -- a one-sided/thin book with no resting bids (or
    no resting asks) is common overnight and legitimately produces bid=0.0
    or ask=0.0 while the other side still has a real quote. Before this
    fix, _liquidation_price() treated that 0.0 as a real price: a YES
    position with bid=0.0 priced at $0.00 (phantom stop-loss/loss), and a
    NO position with ask=0.0 priced at 1.0-0.0=$1.00 (phantom win)."""

    def test_yes_zero_bid_returns_none_not_zero(self):
        from paper import _liquidation_price

        prices = {"T1": {"bid": 0.0, "ask": 0.35}}
        assert _liquidation_price(prices, "T1", "yes") is None

    def test_no_zero_ask_returns_none_not_one(self):
        from paper import _liquidation_price

        prices = {"T1": {"bid": 0.30, "ask": 0.0}}
        assert _liquidation_price(prices, "T1", "no") is None

    def test_yes_real_bid_still_prices_normally(self):
        from paper import _liquidation_price

        prices = {"T1": {"bid": 0.45, "ask": 0.50}}
        assert _liquidation_price(prices, "T1", "yes") == 0.45

    def test_no_real_ask_still_prices_normally(self):
        from paper import _liquidation_price

        prices = {"T1": {"bid": 0.45, "ask": 0.50}}
        assert _liquidation_price(prices, "T1", "no") == pytest.approx(0.50)

    def test_zero_bid_no_longer_fires_phantom_stop_loss(self):
        """End-to-end: a YES position with a one-sided (bid=0) book must not
        be treated as having crashed to $0 -- it must be skipped (fall back
        to entry_price by the caller), not counted as a stop-loss breach."""
        from paper import check_stop_losses

        trade = {
            "ticker": "T1",
            "side": "yes",
            "entry_price": 0.60,
            "quantity": 10,
            "cost": 6.0,
            "settled": False,
            "close_time": "2099-01-01T00:00:00Z",
        }
        # bid=0.0 (no resting bids), ask=0.35 -- a real, non-crashed market
        # with a thin/one-sided book, not an actual price collapse to zero.
        prices = {"T1": {"bid": 0.0, "ask": 0.35}}
        assert check_stop_losses([trade], prices) == []

    def test_zero_ask_no_longer_books_phantom_win(self):
        """End-to-end: a NO position with a one-sided (ask=0) book must not
        be treated as having appreciated to guaranteed-win $1.00."""
        from paper import check_breakeven_stops

        trade = {
            "ticker": "T1",
            "side": "no",
            "entry_price": 0.40,
            "quantity": 10,
            "cost": 4.0,
            "settled": False,
            "close_time": "2099-01-01T00:00:00Z",
            "peak_profit_pct": 0.5,  # already past BREAKEVEN_TRIGGER_PCT
        }
        # bid=0.65 (real), ask=0.0 (no resting asks) -- must be skipped, not
        # priced at a phantom $1.00 that would trivially trigger the stop.
        prices = {"T1": {"bid": 0.65, "ask": 0.0}}
        assert check_breakeven_stops([trade], prices) == []


class TestCheckStopLosses:
    def _trade(self, ticker, side, entry_price, qty, close_time="2099-01-01T00:00:00Z"):
        # close_time defaults to far-future so Fix 1's 24h gate doesn't skip the trade.
        cost = round(entry_price * qty, 4)
        return {
            "ticker": ticker,
            "side": side,
            "entry_price": entry_price,
            "quantity": qty,
            "cost": cost,
            "settled": False,
            "close_time": close_time,
        }

    def test_stop_triggers_when_yes_price_halves(self):
        """YES trade: price halved → loss = 50% of cost → stop fires (MULT=2)."""
        from paper import check_stop_losses

        trade = self._trade("T1", "yes", 0.60, 10)
        # current yes = 0.30 → loss = (0.30-0.60)*10 = -3.0; threshold = -cost/2 = -3.0
        # At exactly threshold it fires (strictly less would not, so use 0.29)
        prices = {"T1": 0.29}
        assert check_stop_losses([trade], _flat_prices(prices)) == ["T1"]

    def test_stop_not_triggered_within_range(self):
        """YES trade: small adverse move → no stop."""
        from paper import check_stop_losses

        trade = self._trade("T1", "yes", 0.60, 10)
        prices = {"T1": 0.50}  # lost $1 of $6 — well within threshold
        assert check_stop_losses([trade], _flat_prices(prices)) == []

    def test_stop_triggers_for_no_trade(self):
        """NO trade: YES price rises sharply → NO value drops → stop fires."""
        from paper import check_stop_losses

        # NO trade: entry_price = 0.40 (paid 40¢ per contract)
        trade = self._trade("T1", "no", 0.40, 10)
        # current yes = 0.85 → current NO = 0.15; loss = (0.15-0.40)*10 = -2.5
        # threshold = -cost/2 = -2.0  →  -2.5 < -2.0 → fires
        prices = {"T1": 0.85}
        assert check_stop_losses([trade], _flat_prices(prices)) == ["T1"]

    def test_stop_not_triggered_when_multiplier_zero(self):
        """STOP_LOSS_MULT=0 disables stop-losses entirely."""
        from unittest.mock import patch

        import utils
        from paper import check_stop_losses

        trade = self._trade("T1", "yes", 0.60, 10)
        prices = {"T1": 0.01}  # extreme loss
        with patch.object(utils, "STOP_LOSS_MULT", 0.0):
            assert check_stop_losses([trade], _flat_prices(prices)) == []

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
        result = check_stop_losses([t1, t2], _flat_prices(prices))
        assert result == ["T1"]

    def test_stop_loss_result_wires_to_close_paper_early(self, tmp_path, monkeypatch):
        """Full chain: stop fires → close_paper_early settles the trade and updates balance."""
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        # Reload so the module re-reads the patched DATA_PATH for balance/trades state.
        import importlib

        importlib.reload(paper)
        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

        # Place a trade: 10 contracts at $0.60 → cost $6.00, balance $994.00
        trade = paper.place_paper_order(
            "T_INTEGRATION",
            "yes",
            10,
            0.60,
            close_time="2099-01-01T00:00:00Z",
        )

        # Price drops to 0.29 → unrealized PnL = (0.29 - 0.60) * 10 = -$3.10
        # stop_threshold = -(cost / MULT) = -(6.0 / 2) = -$3.00 → breach
        prices = {"T_INTEGRATION": 0.29}
        tickers = paper.check_stop_losses(paper.get_open_trades(), _flat_prices(prices))
        assert "T_INTEGRATION" in tickers, (
            "Stop should fire when loss exceeds threshold"
        )

        # Wire stop result to close_paper_early
        exit_price = prices["T_INTEGRATION"]
        paper.close_paper_early(trade["id"], exit_price)

        assert paper.get_open_trades() == [], "Trade must be closed after early exit"
        # balance: started 1000 − cost(6.00) + proceeds(0.29 * 10 = 2.90) = 996.90
        assert paper.get_balance() == pytest.approx(996.90, abs=0.01)


def test_portfolio_expected_value_positive_for_winning_trades(monkeypatch):
    """get_portfolio_expected_value sums cost * net_edge across open positions."""
    import paper

    trades = [
        {
            "ticker": "T1",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "cost": 5.00,
            "net_edge": 0.15,
            "settled": False,
            "won": None,
        },
        {
            "ticker": "T2",
            "side": "yes",
            "entry_price": 0.55,
            "quantity": 5,
            "cost": 2.75,
            "net_edge": 0.20,
            "settled": False,
            "won": None,
        },
    ]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)

    ev = paper.get_portfolio_expected_value()
    # T1: cost=$5.00, EV=5.00*0.15=$0.75
    # T2: cost=$2.75, EV=2.75*0.20=$0.55
    expected_total_profit = 0.75 + 0.55  # = 1.30
    assert abs(ev["expected_profit_dollars"] - expected_total_profit) < 0.01
    assert ev["open_position_count"] == 2
    assert ev["total_cost_dollars"] == pytest.approx(7.75, abs=0.01)


def test_portfolio_expected_value_does_not_crash_on_explicit_none_net_edge(
    monkeypatch,
):
    """#8: a trade with net_edge explicitly None (not absent) — e.g. a
    dashboard order with no net_edge in the POST body — must not crash
    get_portfolio_expected_value(). float(t.get("net_edge", 0.0)) only
    applies its default when the key is missing, not when it's None."""
    import paper

    trades = [
        {
            "ticker": "T1",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "cost": 5.00,
            "net_edge": None,
            "settled": False,
            "won": None,
        },
        {
            "ticker": "T2",
            "side": "yes",
            "entry_price": 0.55,
            "quantity": 5,
            "cost": 2.75,
            "net_edge": 0.20,
            "settled": False,
            "won": None,
        },
    ]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)

    ev = paper.get_portfolio_expected_value()  # must not raise

    # T1 contributes 0 EV (net_edge treated as 0.0), T2 contributes 2.75*0.20=0.55
    assert ev["expected_profit_dollars"] == pytest.approx(0.55, abs=0.01)
    assert ev["open_position_count"] == 2


class TestUndoLastTradePeakBalance:
    """#9: undo_last_trade's peak_balance recompute replayed each trade's
    entry AND settlement together at the trade's entered_at, instead of at
    their real, separate timestamps — misordering the replay relative to
    other trades whenever a trade settled after some other trade's entry."""

    def test_peak_recompute_uses_true_chronological_order(self, tmp_path, monkeypatch):
        import paper

        p = tmp_path / "paper_trades.json"
        monkeypatch.setattr(paper, "DATA_PATH", p)

        now = datetime.now(UTC)

        def _iso(**delta):
            from datetime import timedelta

            return (now - timedelta(**delta)).isoformat()

        # Trade A: entered 10 days ago, cost $100, settled 2 days ago with a
        # big win (pnl=+200, payout $300). Trade C: entered 5 days ago
        # (between A's entry and settlement), cost $50, still open. Trade B:
        # entered just now (within undo's 5-min window), cost $30 — this is
        # the one undone; it's removed before the recompute, so only A/C
        # participate in the peak replay below.
        #
        # True chronological balance path (STARTING_BALANCE=$1000):
        #   -10d A enters:  1000-100 = 900
        #    -5d C enters:   900-50  = 850
        #   -2d A settles:   850+300 = 1150
        # True peak ever reached = max(1000, 900, 850, 1150) = 1150.
        #
        # The old code (sorted by entered_at, settlement applied AT entry)
        # applied A's +300 payout immediately at -10d (before C's -5d entry
        # cost is ever subtracted): 1000-100+300=1200 — a peak that never
        # actually existed in the true timeline.
        trade_a = {
            "id": 1,
            "ticker": "A",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 200,
            "cost": 100.0,
            "settled": True,
            "entered_at": _iso(days=10),
            "settled_at": _iso(days=2),
            "pnl": 200.0,
        }
        trade_c = {
            "id": 3,
            "ticker": "C",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 100,
            "cost": 50.0,
            "settled": False,
            "entered_at": _iso(days=5),
        }
        trade_b = {
            "id": 2,
            "ticker": "B",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 60,
            "cost": 30.0,
            "settled": False,
            "entered_at": now.isoformat(),  # within undo's 5-min window
        }
        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": 820.0,
            "peak_balance": 1000.0,
            "trades": [trade_a, trade_c, trade_b],
        }
        p.write_text(json.dumps(data))

        undone = paper.undo_last_trade(max_minutes=5)

        assert undone is not None and undone["id"] == 2
        result = paper._load()
        assert result["peak_balance"] == pytest.approx(1150.0), (
            f"expected the true chronological peak (1150), got "
            f"{result['peak_balance']} (1200 would indicate the old "
            f"entry-time-only replay bug)"
        )


class TestGetDailyPnlNoneSettledAt:
    """Deep-review followup: t.get("settled_at", "") only covers a MISSING
    key -- a settled record with settled_at explicitly None (a real state;
    see the M-9 comment above get_daily_pnl) returns None, and None[:10]
    raised TypeError directly on is_daily_loss_halted()'s path -- an
    uncaught exception on a safety gate."""

    def test_none_settled_at_does_not_crash(self, tmp_path, monkeypatch):
        import paper

        p = tmp_path / "paper_trades.json"
        monkeypatch.setattr(paper, "DATA_PATH", p)
        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": 900.0,
            "peak_balance": 1000.0,
            "trades": [
                {
                    "id": 1,
                    "ticker": "T1",
                    "side": "yes",
                    "settled": True,
                    "settled_at": None,
                    "pnl": -50.0,
                }
            ],
        }
        p.write_text(json.dumps(data))

        # Must not raise.
        result = paper.get_daily_pnl()
        assert result == 0.0, "a None settled_at record must be excluded, not crash"


# ── Correctness tests for previously-untested functions ─────────────────────
# validate_paper_trades_integrity, get_rolling_sharpe, get_factor_exposure,
# get_unrealized_pnl_paper had zero correctness coverage despite being live-used
# (health-check endpoint, dashboard risk metrics, mark-to-market P&L).


class TestValidatePaperTradesIntegrity:
    def test_clean_state_reports_no_errors(self):
        import paper

        settled_pnl = 50.0
        open_cost = 100.0
        actual_balance = paper.STARTING_BALANCE + settled_pnl - open_cost
        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": actual_balance,
            "peak_balance": paper.STARTING_BALANCE,
            "trades": [
                {
                    "id": 1,
                    "ticker": "T1",
                    "side": "yes",
                    "settled": True,
                    "settled_at": "2026-07-01T00:00:00Z",
                    "pnl": settled_pnl,
                    "cost": 40.0,
                },
                {
                    "id": 2,
                    "ticker": "T2",
                    "side": "yes",
                    "settled": False,
                    "cost": open_cost,
                },
            ],
        }
        paper.DATA_PATH.write_text(json.dumps(data))

        errors = paper.validate_paper_trades_integrity()
        assert errors == []

    def test_corrupted_balance_is_detected(self):
        """A balance field that doesn't match computed
        (start + settled_pnl - open_cost) must be flagged as balance drift."""
        import paper

        settled_pnl = 50.0
        open_cost = 100.0
        correct_balance = paper.STARTING_BALANCE + settled_pnl - open_cost
        corrupted_balance = correct_balance + 999.0  # deliberately wrong
        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": corrupted_balance,
            "peak_balance": paper.STARTING_BALANCE,
            "trades": [
                {
                    "id": 1,
                    "ticker": "T1",
                    "side": "yes",
                    "settled": True,
                    "settled_at": "2026-07-01T00:00:00Z",
                    "pnl": settled_pnl,
                    "cost": 40.0,
                },
                {
                    "id": 2,
                    "ticker": "T2",
                    "side": "yes",
                    "settled": False,
                    "cost": open_cost,
                },
            ],
        }
        paper.DATA_PATH.write_text(json.dumps(data))

        errors = paper.validate_paper_trades_integrity()
        assert len(errors) == 1
        assert "balance drift" in errors[0]


class TestGetRollingSharpe:
    def test_known_daily_pnl_produces_expected_sharpe(self):
        """5 days of known P&L -> exact annualized Sharpe (sqrt(252))."""
        import paper

        now = datetime.now(UTC)
        pnls = [10.0, -5.0, 20.0, -10.0, 15.0]
        trades = []
        for i, pnl in enumerate(pnls):
            day = (now - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            trades.append(
                {
                    "id": i + 1,
                    "ticker": f"T{i}",
                    "settled": True,
                    "entered_at": f"{day}T00:00:00Z",
                    "settled_at": f"{day}T00:00:00Z",
                    "pnl": pnl,
                }
            )
        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": paper.STARTING_BALANCE,
            "peak_balance": paper.STARTING_BALANCE,
            "trades": trades,
        }
        paper.DATA_PATH.write_text(json.dumps(data))

        result = paper.get_rolling_sharpe(window_days=30)
        # mean=6.0, sample stdev=12.942179105544785 -> mean/stdev*sqrt(252)
        assert result == pytest.approx(7.3594, abs=1e-4)

    def test_fewer_than_five_days_returns_none(self):
        import paper

        now = datetime.now(UTC)
        trades = []
        for i, pnl in enumerate([10.0, -5.0, 20.0]):
            day = (now - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            trades.append(
                {
                    "id": i + 1,
                    "ticker": f"T{i}",
                    "settled": True,
                    "entered_at": f"{day}T00:00:00Z",
                    "settled_at": f"{day}T00:00:00Z",
                    "pnl": pnl,
                }
            )
        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": paper.STARTING_BALANCE,
            "peak_balance": paper.STARTING_BALANCE,
            "trades": trades,
        }
        paper.DATA_PATH.write_text(json.dumps(data))

        assert paper.get_rolling_sharpe(window_days=30) is None

    def test_zero_variance_returns_none(self):
        """Identical daily P&L -> stdev=0 -> must not divide by zero."""
        import paper

        now = datetime.now(UTC)
        trades = []
        for i in range(5):
            day = (now - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            trades.append(
                {
                    "id": i + 1,
                    "ticker": f"T{i}",
                    "settled": True,
                    "entered_at": f"{day}T00:00:00Z",
                    "settled_at": f"{day}T00:00:00Z",
                    "pnl": 5.0,
                }
            )
        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": paper.STARTING_BALANCE,
            "peak_balance": paper.STARTING_BALANCE,
            "trades": trades,
        }
        paper.DATA_PATH.write_text(json.dumps(data))

        assert paper.get_rolling_sharpe(window_days=30) is None


class TestGetFactorExposure:
    def _write_open_trades(self, trades):
        import paper

        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": paper.STARTING_BALANCE,
            "peak_balance": paper.STARTING_BALANCE,
            "trades": trades,
        }
        paper.DATA_PATH.write_text(json.dumps(data))

    def test_yes_heavy_above_060(self):
        import paper

        self._write_open_trades(
            [
                {
                    "id": 1,
                    "ticker": "A",
                    "side": "yes",
                    "cost": 70.0,
                    "city": "NYC",
                    "settled": False,
                },
                {
                    "id": 2,
                    "ticker": "B",
                    "side": "no",
                    "cost": 30.0,
                    "city": "LAX",
                    "settled": False,
                },
            ]
        )
        result = paper.get_factor_exposure()
        assert result["net_bias"] == "YES-heavy"
        assert result["yes_count"] == 1
        assert result["no_count"] == 1
        assert result["yes_cost"] == 70.0
        assert result["no_cost"] == 30.0
        assert result["cities_long_yes"] == ["NYC"]
        assert result["cities_long_no"] == ["LAX"]

    def test_no_heavy_below_040(self):
        import paper

        self._write_open_trades(
            [
                {
                    "id": 1,
                    "ticker": "A",
                    "side": "yes",
                    "cost": 20.0,
                    "city": "NYC",
                    "settled": False,
                },
                {
                    "id": 2,
                    "ticker": "B",
                    "side": "no",
                    "cost": 80.0,
                    "city": "LAX",
                    "settled": False,
                },
            ]
        )
        result = paper.get_factor_exposure()
        assert result["net_bias"] == "NO-heavy"

    def test_exact_060_boundary_is_balanced(self):
        """yes_frac == 0.6 exactly must NOT count as YES-heavy (strict >)."""
        import paper

        self._write_open_trades(
            [
                {
                    "id": 1,
                    "ticker": "A",
                    "side": "yes",
                    "cost": 60.0,
                    "city": "NYC",
                    "settled": False,
                },
                {
                    "id": 2,
                    "ticker": "B",
                    "side": "no",
                    "cost": 40.0,
                    "city": "LAX",
                    "settled": False,
                },
            ]
        )
        result = paper.get_factor_exposure()
        assert result["net_bias"] == "Balanced"

    def test_exact_040_boundary_is_balanced(self):
        """yes_frac == 0.4 exactly must NOT count as NO-heavy (strict <)."""
        import paper

        self._write_open_trades(
            [
                {
                    "id": 1,
                    "ticker": "A",
                    "side": "yes",
                    "cost": 40.0,
                    "city": "NYC",
                    "settled": False,
                },
                {
                    "id": 2,
                    "ticker": "B",
                    "side": "no",
                    "cost": 60.0,
                    "city": "LAX",
                    "settled": False,
                },
            ]
        )
        result = paper.get_factor_exposure()
        assert result["net_bias"] == "Balanced"

    def test_no_open_trades_is_balanced_with_zero_costs(self):
        import paper

        self._write_open_trades([])
        result = paper.get_factor_exposure()
        assert result["net_bias"] == "Balanced"
        assert result["yes_count"] == 0
        assert result["no_count"] == 0


class _FakeMarketClient:
    """Minimal stub of the Kalshi client's get_market(ticker) surface."""

    def __init__(self, markets: dict):
        self._markets = markets

    def get_market(self, ticker):
        return self._markets[ticker]


class TestGetUnrealizedPnlPaper:
    def _write_open_trades(self, trades):
        import paper

        data = {
            "_version": paper._SCHEMA_VERSION,
            "balance": paper.STARTING_BALANCE,
            "peak_balance": paper.STARTING_BALANCE,
            "trades": trades,
        }
        paper.DATA_PATH.write_text(json.dumps(data))

    def test_yes_side_marks_at_bid(self):
        """YES holder can only realize the bid — mark_pnl = (bid - entry) * qty."""
        import paper

        self._write_open_trades(
            [
                {
                    "id": 1,
                    "ticker": "YES-TICK",
                    "side": "yes",
                    "entry_price": 0.40,
                    "quantity": 10,
                    "settled": False,
                }
            ]
        )
        client = _FakeMarketClient({"YES-TICK": {"yes_bid": 0.55, "yes_ask": 0.60}})
        result = paper.get_unrealized_pnl_paper(client)
        assert result["n"] == 1
        assert result["by_trade"][0]["current_price"] == pytest.approx(0.55)
        assert result["by_trade"][0]["mark_pnl"] == pytest.approx(1.50)
        assert result["total_unrealized"] == pytest.approx(1.50)

    def test_no_side_marks_at_one_minus_ask(self):
        """NO holder can only realize (1 - yes_ask) — mark_pnl = ((1-ask) - entry) * qty."""
        import paper

        self._write_open_trades(
            [
                {
                    "id": 2,
                    "ticker": "NO-TICK",
                    "side": "no",
                    "entry_price": 0.30,
                    "quantity": 10,
                    "settled": False,
                }
            ]
        )
        client = _FakeMarketClient({"NO-TICK": {"yes_bid": 0.20, "yes_ask": 0.25}})
        result = paper.get_unrealized_pnl_paper(client)
        assert result["n"] == 1
        assert result["by_trade"][0]["current_price"] == pytest.approx(0.75)  # 1 - 0.25
        assert result["by_trade"][0]["mark_pnl"] == pytest.approx(
            4.50
        )  # (0.75-0.30)*10
        assert result["total_unrealized"] == pytest.approx(4.50)

    def test_mixed_yes_and_no_sides_sum_correctly(self):
        import paper

        self._write_open_trades(
            [
                {
                    "id": 1,
                    "ticker": "YES-TICK",
                    "side": "yes",
                    "entry_price": 0.40,
                    "quantity": 10,
                    "settled": False,
                },
                {
                    "id": 2,
                    "ticker": "NO-TICK",
                    "side": "no",
                    "entry_price": 0.30,
                    "quantity": 10,
                    "settled": False,
                },
            ]
        )
        client = _FakeMarketClient(
            {
                "YES-TICK": {"yes_bid": 0.55, "yes_ask": 0.60},
                "NO-TICK": {"yes_bid": 0.20, "yes_ask": 0.25},
            }
        )
        result = paper.get_unrealized_pnl_paper(client)
        assert result["n"] == 2
        assert result["total_unrealized"] == pytest.approx(6.00)  # 1.50 + 4.50

    def test_no_open_trades_returns_zero(self):
        import paper

        self._write_open_trades([])
        client = _FakeMarketClient({})
        result = paper.get_unrealized_pnl_paper(client)
        assert result == {"total_unrealized": 0.0, "by_trade": [], "n": 0}

    def test_client_none_returns_zero_even_with_open_trades(self):
        import paper

        self._write_open_trades(
            [
                {
                    "id": 1,
                    "ticker": "YES-TICK",
                    "side": "yes",
                    "entry_price": 0.40,
                    "quantity": 10,
                    "settled": False,
                }
            ]
        )
        result = paper.get_unrealized_pnl_paper(None)
        assert result == {"total_unrealized": 0.0, "by_trade": [], "n": 0}
