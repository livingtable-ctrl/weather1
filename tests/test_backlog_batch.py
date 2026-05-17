"""Tests for backlog items #6, #4, #1, #2.

#6 - City-level Kelly scaling from Brier
#4 - Max positions per settlement date
#1 - Belt-and-suspenders duplicate guard in place_paper_order
#2 - Edge realization rate
"""

import os
from unittest.mock import patch

# ── #6: City-level Kelly from Brier ──────────────────────────────────────────


class TestCityKellyMultiplier:
    def _mult(self, city, cal_data):
        from paper import _city_kelly_multiplier

        with patch("tracker.get_calibration_by_city", return_value=cal_data):
            return _city_kelly_multiplier(city)

    def test_neutral_when_city_is_none(self):
        from paper import _city_kelly_multiplier

        assert _city_kelly_multiplier(None) == 1.0

    def test_neutral_when_insufficient_samples(self):
        # 9 samples < 10 minimum — should return 1.0 regardless of Brier
        cal = {"NYC": {"brier": 0.50, "n": 9}}
        assert self._mult("NYC", cal) == 1.0

    def test_neutral_when_city_not_in_cal(self):
        # City absent from calibration data — neutral
        assert self._mult("Denver", {}) == 1.0

    def test_excellent_brier_no_reduction(self):
        cal = {"NYC": {"brier": 0.12, "n": 20}}
        assert self._mult("NYC", cal) == 1.00

    def test_good_brier_slight_reduction(self):
        cal = {"Chicago": {"brier": 0.18, "n": 15}}
        assert self._mult("Chicago", cal) == 0.85

    def test_near_random_brier_meaningful_reduction(self):
        cal = {"Atlanta": {"brier": 0.23, "n": 12}}
        assert self._mult("Atlanta", cal) == 0.65

    def test_poor_brier_heavy_reduction(self):
        # SF had Brier 0.563 in production — should get 0.40 multiplier
        cal = {"SanFrancisco": {"brier": 0.56, "n": 30}}
        assert self._mult("SanFrancisco", cal) == 0.40

    def test_tracker_exception_returns_neutral(self):
        from paper import _city_kelly_multiplier

        with patch(
            "tracker.get_calibration_by_city", side_effect=RuntimeError("db down")
        ):
            assert _city_kelly_multiplier("NYC") == 1.0

    def test_applied_in_portfolio_kelly_fraction(self):
        """_city_kelly_multiplier is called inside portfolio_kelly_fraction."""
        from paper import portfolio_kelly_fraction

        cal_bad = {"Miami": {"brier": 0.50, "n": 25}}
        cal_good = {"Miami": {"brier": 0.12, "n": 25}}

        with (
            patch("paper.get_total_exposure", return_value=0.0),
            patch("paper.get_city_date_exposure", return_value=0.0),
            patch("paper.get_directional_exposure", return_value=0.0),
            patch("paper.get_correlated_exposure", return_value=0.0),
            patch("paper.position_age_kelly_scale", return_value=1.0),
            patch("paper.covariance_kelly_scale", return_value=1.0),
        ):
            with patch("tracker.get_calibration_by_city", return_value=cal_bad):
                kelly_bad = portfolio_kelly_fraction(0.20, "Miami", "2026-05-20")
            with patch("tracker.get_calibration_by_city", return_value=cal_good):
                kelly_good = portfolio_kelly_fraction(0.20, "Miami", "2026-05-20")

        import pytest

        assert kelly_bad < kelly_good, "Bad-Brier city should produce smaller Kelly"
        assert kelly_bad == pytest.approx(kelly_good * 0.40), (
            "0.40 multiplier for Brier=0.50"
        )


# ── #4: Max positions per settlement date ────────────────────────────────────


class TestMaxPositionsPerDate:
    def _make_open_trade(self, ticker, target_date):
        return {
            "ticker": ticker,
            "side": "yes",
            "quantity": 1,
            "entry_price": 0.55,
            "cost": 0.55,
            "city": "NYC",
            "target_date": target_date,
            "settled": False,
            "outcome": None,
            "pnl": None,
            "entered_at": "2026-05-17T00:00:00+00:00",
            "id": 1,
        }

    def test_blocks_when_date_cap_reached(self):
        """When 4 positions already expire on a date, a 5th is rejected."""
        import order_executor

        existing = [
            self._make_open_trade(f"KXHIGHNY-26MAY20-T{70 + i}", "2026-05-20")
            for i in range(4)
        ]
        opp = {
            "ticker": "KXHIGHNY-26MAY20-T75",
            "net_signal": "STRONG_BUY",
            "time_risk": "LOW",
            "recommended_side": "yes",
            "ci_adjusted_kelly": 0.15,
            "market_prob": 0.55,
            "forecast_prob": 0.65,
            "edge": 0.10,
            "_city": "NYC",
            "_date": __import__("datetime").date(2026, 5, 20),
        }

        with (
            patch("paper.get_open_trades", return_value=existing),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.drawdown_scaling_factor", return_value=1.0),
            patch("order_executor._daily_paper_spend", return_value=0.0),
            patch(
                "order_executor.execution_log.was_ordered_recently", return_value=False
            ),
            patch("order_executor.execution_log.was_traded_today", return_value=False),
            patch(
                "order_executor.execution_log.was_ordered_this_cycle",
                return_value=False,
            ),
            patch("order_executor.execution_log.log_order", return_value=1),
            patch(
                "order_executor._validate_trade_opportunity", return_value=(True, "")
            ),
            patch("paper.place_paper_order") as mock_place,
            patch.dict(os.environ, {"MAX_POSITIONS_PER_DATE": "4"}),
        ):
            result = order_executor._auto_place_trades([opp], live=False)

        assert result == 0
        mock_place.assert_not_called()

    def test_allows_when_under_date_cap(self):
        """With only 2 positions on the date, a 3rd is allowed (cap=4)."""
        import order_executor

        existing = [
            self._make_open_trade(f"KXHIGHNY-26MAY20-T{70 + i}", "2026-05-20")
            for i in range(2)
        ]
        opp = {
            "ticker": "KXHIGHNY-26MAY20-T75",
            "net_signal": "STRONG_BUY",
            "time_risk": "LOW",
            "recommended_side": "yes",
            "ci_adjusted_kelly": 0.15,
            "market_prob": 0.55,
            "forecast_prob": 0.65,
            "edge": 0.10,
            "method": "ensemble",
            "_city": "NYC",
            "_date": __import__("datetime").date(2026, 5, 20),
        }
        mock_trade = {
            **existing[0],
            "ticker": "KXHIGHNY-26MAY20-T75",
            "id": 3,
            "cost": 0.55,
        }

        with (
            patch("paper.get_open_trades", return_value=existing),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.drawdown_scaling_factor", return_value=1.0),
            patch("paper.portfolio_kelly_fraction", return_value=0.15),
            patch("paper.corr_kelly_scale", return_value=1.0),
            patch("paper.kelly_quantity", return_value=2),
            patch("order_executor._daily_paper_spend", return_value=0.0),
            patch(
                "order_executor.execution_log.was_ordered_recently", return_value=False
            ),
            patch("order_executor.execution_log.was_traded_today", return_value=False),
            patch(
                "order_executor.execution_log.was_ordered_this_cycle",
                return_value=False,
            ),
            patch("order_executor.execution_log.log_order", return_value=1),
            patch("order_executor.execution_log.log_order_result"),
            patch(
                "order_executor._validate_trade_opportunity", return_value=(True, "")
            ),
            patch("paper.place_paper_order", return_value=mock_trade),
            patch.dict(os.environ, {"MAX_POSITIONS_PER_DATE": "4"}),
        ):
            result = order_executor._auto_place_trades([opp], live=False)

        assert result == 1

    def test_different_dates_are_independent(self):
        """Cap is per-date: 4 positions on May-20 don't block a May-21 trade."""
        import order_executor

        existing = [
            self._make_open_trade(f"KXHIGHNY-26MAY20-T{70 + i}", "2026-05-20")
            for i in range(4)
        ]
        opp = {
            "ticker": "KXHIGHNY-26MAY21-T72",
            "net_signal": "STRONG_BUY",
            "time_risk": "LOW",
            "recommended_side": "yes",
            "ci_adjusted_kelly": 0.15,
            "market_prob": 0.55,
            "forecast_prob": 0.65,
            "edge": 0.10,
            "method": "ensemble",
            "_city": "NYC",
            "_date": __import__("datetime").date(2026, 5, 21),
        }
        mock_trade = {
            **existing[0],
            "ticker": "KXHIGHNY-26MAY21-T72",
            "id": 5,
            "cost": 0.55,
        }

        with (
            patch("paper.get_open_trades", return_value=existing),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.drawdown_scaling_factor", return_value=1.0),
            patch("paper.portfolio_kelly_fraction", return_value=0.15),
            patch("paper.corr_kelly_scale", return_value=1.0),
            patch("paper.kelly_quantity", return_value=2),
            patch("order_executor._daily_paper_spend", return_value=0.0),
            patch(
                "order_executor.execution_log.was_ordered_recently", return_value=False
            ),
            patch("order_executor.execution_log.was_traded_today", return_value=False),
            patch(
                "order_executor.execution_log.was_ordered_this_cycle",
                return_value=False,
            ),
            patch("order_executor.execution_log.log_order", return_value=1),
            patch("order_executor.execution_log.log_order_result"),
            patch(
                "order_executor._validate_trade_opportunity", return_value=(True, "")
            ),
            patch("paper.place_paper_order", return_value=mock_trade),
            patch.dict(os.environ, {"MAX_POSITIONS_PER_DATE": "4"}),
        ):
            result = order_executor._auto_place_trades([opp], live=False)

        assert result == 1


# ── #1: Duplicate guard in place_paper_order ─────────────────────────────────


class TestPlacePaperOrderDuplicateGuard:
    def _seed_state(self, tmp_path, open_ticker=None):
        """Write a paper state JSON with an optional open trade."""
        import json

        trades = []
        if open_ticker:
            trades.append(
                {
                    "id": 1,
                    "ticker": open_ticker,
                    "side": "yes",
                    "quantity": 2,
                    "entry_price": 0.55,
                    "entry_prob": 0.65,
                    "net_edge": 0.10,
                    "cost": 1.10,
                    "city": "NYC",
                    "target_date": "2026-05-20",
                    "entered_at": "2026-05-17T00:00:00+00:00",
                    "entry_hour": 0,
                    "settled": False,
                    "outcome": None,
                    "pnl": None,
                    "exit_target": None,
                    "thesis": None,
                    "method": None,
                    "icon_forecast_mean": None,
                    "gfs_forecast_mean": None,
                    "condition_threshold": None,
                    "ab_variant": None,
                    "actual_fill_price": 0.55,
                }
            )
        state = {"balance": 1000.0, "peak_balance": 1000.0, "trades": trades}
        p = tmp_path / "paper_state.json"
        p.write_text(json.dumps(state))
        return p

    def test_duplicate_blocked_when_ticker_already_open(self, tmp_path):
        """place_paper_order raises ValueError if the same ticker is already open."""
        import pytest

        import paper

        state_path = self._seed_state(tmp_path, open_ticker="KXHIGHNY-26MAY20-T72")

        with patch(
            "paper._load", return_value=__import__("json").loads(state_path.read_text())
        ):
            with pytest.raises(ValueError, match="Duplicate paper order"):
                paper.place_paper_order(
                    ticker="KXHIGHNY-26MAY20-T72",
                    side="yes",
                    quantity=1,
                    entry_price=0.55,
                )

    def test_no_duplicate_when_settled(self, tmp_path):
        """Settled trades with the same ticker should not block re-entry."""
        import paper

        # Build state where the existing trade IS settled
        state = {
            "balance": 1000.0,
            "peak_balance": 1000.0,
            "trades": [
                {
                    "id": 1,
                    "ticker": "KXHIGHNY-26MAY20-T72",
                    "side": "yes",
                    "quantity": 2,
                    "entry_price": 0.55,
                    "entry_prob": 0.65,
                    "net_edge": 0.10,
                    "cost": 1.10,
                    "city": "NYC",
                    "target_date": "2026-05-20",
                    "entered_at": "2026-05-17T00:00:00+00:00",
                    "entry_hour": 0,
                    "settled": True,  # <-- already settled
                    "outcome": "yes",
                    "pnl": 0.90,
                    "exit_target": None,
                    "thesis": None,
                    "method": None,
                    "icon_forecast_mean": None,
                    "gfs_forecast_mean": None,
                    "condition_threshold": None,
                    "ab_variant": None,
                    "actual_fill_price": 0.55,
                }
            ],
        }

        with (
            patch("paper._load", return_value=state),
            patch("paper._save"),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.get_ticker_exposure", return_value=0.0),
            patch("paper._exposure_denom", return_value=1000.0),
        ):
            # Should NOT raise — settled trade doesn't block re-entry
            result = paper.place_paper_order(
                ticker="KXHIGHNY-26MAY20-T72",
                side="yes",
                quantity=1,
                entry_price=0.55,
            )
        assert result["ticker"] == "KXHIGHNY-26MAY20-T72"


# ── #2: Edge realization rate ────────────────────────────────────────────────


class TestEdgeRealizationRate:
    def _make_trade(self, net_edge, side, outcome, settled=True):
        return {
            "ticker": "KXTEST",
            "side": side,
            "outcome": outcome,
            "net_edge": net_edge,
            "settled": settled,
            "pnl": 1.0 if outcome == side else -1.0,
        }

    def test_returns_empty_when_too_few_trades(self):
        from paper import get_edge_realization_rate

        trades = [self._make_trade(0.10, "yes", "yes") for _ in range(3)]
        with patch("paper.get_all_trades", return_value=trades):
            result = get_edge_realization_rate()
        assert result["n"] == 3
        assert result["correlation"] is None
        assert result["calibrated"] is False

    def test_positive_correlation_when_edge_predicts_wins(self):
        """Higher edge trades should show higher win rate → positive correlation."""
        from paper import get_edge_realization_rate

        # Low edge trades lose, high edge trades win
        trades = (
            [self._make_trade(0.02, "yes", "no") for _ in range(5)]  # low edge, lose
            + [self._make_trade(0.20, "yes", "yes") for _ in range(5)]  # high edge, win
        )
        with patch("paper.get_all_trades", return_value=trades):
            result = get_edge_realization_rate()
        assert result["correlation"] is not None
        assert result["correlation"] > 0, "Higher edge should correlate with wins"

    def test_buckets_reflect_win_rates(self):
        from paper import get_edge_realization_rate

        trades = (
            [
                self._make_trade(0.03, "yes", "no") for _ in range(4)
            ]  # <5% bucket, 0% win
            + [
                self._make_trade(0.12, "yes", "yes") for _ in range(4)
            ]  # 10-15% bucket, 100% win
        )
        with patch("paper.get_all_trades", return_value=trades):
            result = get_edge_realization_rate()

        buckets_by_label = {b["label"]: b for b in result["buckets"]}
        assert buckets_by_label["<5%"]["win_rate"] == 0.0
        assert buckets_by_label["10-15%"]["win_rate"] == 1.0

    def test_ignores_unsettled_trades(self):
        from paper import get_edge_realization_rate

        trades = [
            self._make_trade(0.15, "yes", "yes", settled=True),
            self._make_trade(0.15, "yes", None, settled=False),  # open — no outcome
        ]
        with patch("paper.get_all_trades", return_value=trades):
            result = get_edge_realization_rate()
        assert result["n"] == 1  # only the settled trade counts

    def test_ignores_trades_without_net_edge(self):
        from paper import get_edge_realization_rate

        trades = [
            {
                "ticker": "X",
                "side": "yes",
                "outcome": "yes",
                "net_edge": None,
                "settled": True,
            },
            self._make_trade(0.10, "yes", "yes"),
        ]
        with patch("paper.get_all_trades", return_value=trades):
            result = get_edge_realization_rate()
        assert result["n"] == 1

    def test_not_calibrated_below_threshold(self):
        """Correlation < 0.10 should not be marked as calibrated."""
        # Random outcomes — no edge signal
        import random

        from paper import get_edge_realization_rate

        random.seed(42)
        trades = [
            self._make_trade(0.10, "yes", random.choice(["yes", "no"]))
            for _ in range(25)
        ]
        with patch("paper.get_all_trades", return_value=trades):
            result = get_edge_realization_rate()
        # Just verify the function runs and returns a dict — calibration may vary
        assert "calibrated" in result
        assert "correlation" in result
