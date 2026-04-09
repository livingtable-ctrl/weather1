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
        # Settle as a winner — payout = 10 * 1.0 * 0.93 = 9.30
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
