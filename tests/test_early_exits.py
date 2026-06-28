"""Tests for early exit threshold and hold-time guards."""

import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_trade(entered_hours_ago: float, side: str = "yes") -> dict:
    entered_at = (datetime.now(UTC) - timedelta(hours=entered_hours_ago)).isoformat()
    return {
        "id": 1,
        "ticker": "KXWT-24-T50-B3",
        "side": side,
        "entry_prob": 0.65,
        "quantity": 10,
        "cost": 3.0,
        "entered_at": entered_at,
    }


class TestCheckModelExitsThresholds:
    def test_edge_gone_threshold_is_negative(self):
        """check_model_exits must NOT exit a trade whose edge merely dropped from 8% to 2%.
        Only exit when edge is meaningfully negative (< -5%)."""
        from paper import check_model_exits

        fake_trade = _make_trade(entered_hours_ago=24)  # well past hold time

        mock_analysis = {
            "net_edge": 0.02,  # weak but still positive — should NOT exit
            "edge": 0.02,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": "KXWT-24-T50-B3"}

        with (
            patch("paper.get_open_trades", return_value=[fake_trade]),
            patch("weather_markets.enrich_with_forecast", return_value={}),
            patch("weather_markets.analyze_trade", return_value=mock_analysis),
        ):
            recs = check_model_exits(mock_client)

        assert len(recs) == 0, (
            "Should not exit a trade with net_edge=+2%; only exit when edge is negative"
        )

    def test_model_flipped_requires_10pct_net_edge(self):
        """check_model_exits model_flipped must require net_edge < -0.10 (not -0.05)."""
        from paper import check_model_exits

        fake_trade = _make_trade(entered_hours_ago=24)

        mock_analysis = {
            "net_edge": -0.07,  # between -5% and -10% — should NOT trigger flip
            "edge": -0.07,
            "recommended_side": "no",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": "KXWT-24-T50-B3"}

        with (
            patch("paper.get_open_trades", return_value=[fake_trade]),
            patch("weather_markets.enrich_with_forecast", return_value={}),
            patch("weather_markets.analyze_trade", return_value=mock_analysis),
        ):
            recs = check_model_exits(mock_client)

        assert len(recs) == 0, (
            "net_edge=-7% should NOT trigger model_flipped exit (threshold is -10%)"
        )

    def test_minimum_hold_time_prevents_early_exit(self):
        """check_model_exits must not exit a trade entered less than 12 hours ago."""
        from paper import check_model_exits

        new_trade = _make_trade(entered_hours_ago=6)  # only 6h old

        mock_analysis = {
            "net_edge": -0.20,  # clearly negative — would exit if not for hold time
            "edge": -0.20,
            "recommended_side": "no",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": "KXWT-24-T50-B3"}

        with (
            patch("paper.get_open_trades", return_value=[new_trade]),
            patch("weather_markets.enrich_with_forecast", return_value={}),
            patch("weather_markets.analyze_trade", return_value=mock_analysis),
        ):
            recs = check_model_exits(mock_client)

        assert len(recs) == 0, (
            "Trade entered 6h ago must not be exited — minimum hold time is 12h"
        )


class TestCheckEarlyExitsApiCallCount:
    def test_get_weather_markets_called_once_for_multiple_trades(self):
        """P1-20: get_weather_markets must be called once regardless of N open trades."""
        import main

        trades = [_make_trade(entered_hours_ago=24, side="yes") for _ in range(5)]
        for i, t in enumerate(trades):
            t["id"] = i + 1
            t["ticker"] = f"KXWT-T5{i}"

        markets = [{"ticker": f"KXWT-T5{i}", "yes_bid": 30} for i in range(5)]
        mock_analysis = {"forecast_prob": 0.65, "net_edge": 0.05}
        mock_client = MagicMock()

        with (
            patch(
                "order_executor.get_weather_markets", return_value=markets
            ) as mock_fetch,
            patch("order_executor.enrich_with_forecast", return_value={}),
            patch("order_executor.analyze_trade", return_value=mock_analysis),
            patch("paper.get_open_trades", return_value=trades),
        ):
            main._check_early_exits(mock_client)

        assert mock_fetch.call_count == 1, (
            f"get_weather_markets called {mock_fetch.call_count}× for 5 trades; "
            "must be called exactly once before the loop (P1-20)"
        )

    def test_get_weather_markets_not_called_when_no_open_trades(self):
        """P1-20: no API call at all when there are no open trades."""
        import main

        mock_client = MagicMock()

        with (
            patch("order_executor.get_weather_markets") as mock_fetch,
            patch("paper.get_open_trades", return_value=[]),
        ):
            result = main._check_early_exits(mock_client)

        assert result == 0
        mock_fetch.assert_not_called()


class TestCheckEarlyExitsHoldTime:
    def test_new_trade_not_exited_by_probability_shift(self):
        """_check_early_exits must not exit a trade entered less than 12 hours ago."""
        import main

        new_trade = _make_trade(entered_hours_ago=4)

        mock_market = {"ticker": "KXWT-24-T50-B3", "yes_bid": 30}
        mock_analysis = {"forecast_prob": 0.30, "net_edge": -0.20}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        with (
            patch("order_executor.get_weather_markets", return_value=[mock_market]),
            patch("order_executor.enrich_with_forecast", return_value=mock_market),
            patch("order_executor.analyze_trade", return_value=mock_analysis),
            patch("paper.get_open_trades", return_value=[new_trade]),
        ):
            closed = main._check_early_exits(mock_client)

        assert closed == 0, (
            "Trade entered 4h ago must not be exited — minimum hold time is 12h"
        )


class TestBreakevenStops:
    def test_check_breakeven_stops_fires_when_peak_met_and_price_falls(self):
        """check_breakeven_stops must return the ticker when peak was met and price fell back."""
        import paper
        from utils import BREAKEVEN_TRIGGER_PCT

        far_future = "2099-01-01T00:00:00+00:00"  # well outside the 24h settlement gate
        trade = {
            "ticker": "KXHIGH-T70",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "settled": False,
            "won": None,
            "peak_profit_pct": BREAKEVEN_TRIGGER_PCT + 0.01,  # peak was hit
            "close_time": far_future,
        }

        # Price has now fallen back below entry (0.48 < 0.50)
        exits = paper.check_breakeven_stops(
            [trade], current_yes_prices={"KXHIGH-T70": 0.48}
        )
        assert "KXHIGH-T70" in exits, (
            f"check_breakeven_stops should fire when price falls below entry. Got: {exits}"
        )

    def test_check_breakeven_stops_silent_before_peak_is_met(self):
        """check_breakeven_stops must NOT fire when peak_profit_pct is below the trigger."""
        import paper
        from utils import BREAKEVEN_TRIGGER_PCT

        far_future = "2099-01-01T00:00:00+00:00"
        trade = {
            "ticker": "KXHIGH-T70",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "settled": False,
            "won": None,
            "peak_profit_pct": BREAKEVEN_TRIGGER_PCT - 0.05,  # below trigger
            "close_time": far_future,
        }

        exits = paper.check_breakeven_stops(
            [trade], current_yes_prices={"KXHIGH-T70": 0.40}
        )
        assert exits == [], f"Should not fire when peak not yet met. Got: {exits}"

    def test_update_peak_profits_sets_peak_on_new_high(self, monkeypatch):
        """update_peak_profits must record a new peak when unrealized profit exceeds stored peak."""
        import paper

        # update_peak_profits calls _load() and _save() internally.
        # Monkeypatch _load and _save to control the data without file I/O.
        trade = {
            "ticker": "KXHIGH-T70",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,  # NOT qty — paper.py uses "quantity"
            "cost": 5.00,  # cost = 0.50 * 10
            "settled": False,
            "peak_profit_pct": None,
        }

        fake_data = {"trades": [trade], "balance": 1000.0}
        monkeypatch.setattr(paper, "_load", lambda: fake_data)
        saved = []
        monkeypatch.setattr(paper, "_save", lambda d: saved.append(d))

        # yes_ask = 0.65 → unrealized_profit_pct = (0.65 - 0.50) * 10 / 5.00 = 0.30 (30%)
        paper.update_peak_profits([trade], current_yes_prices={"KXHIGH-T70": 0.65})

        assert saved, "update_peak_profits must call _save when a new peak is found"
        updated_trade = saved[0]["trades"][0]
        assert updated_trade["peak_profit_pct"] == pytest.approx(0.30, abs=0.01), (
            f"Expected peak_profit_pct ≈ 0.30, got {updated_trade.get('peak_profit_pct')}"
        )


class TestPartialClose:
    def test_partial_close_splits_quantity_50pct(self, monkeypatch):
        """partial_close_position with close_pct=0.50 on a 10-unit trade must leave 5 open
        and mark a separate closed portion with quantity=5 and closed=True.

        Also verifies:
        - No two trades share the same id after the split (Bug 1).
        - The closed portion is NOT returned by get_open_trades() on the next call (Bug 2).
        """
        import paper

        # Trade IDs are integers — use an integer id matching the production schema.
        trade = {
            "id": 42,
            "ticker": "KXHIGH-T70",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "cost": 5.00,
            "settled": False,
            "closed": False,
        }

        # Monkeypatch _load/_save so the function never touches disk.
        fake_data = {"trades": [trade], "balance": 1000.0}
        monkeypatch.setattr(paper, "_load", lambda: fake_data)
        saved = []
        monkeypatch.setattr(paper, "_save", lambda d: saved.append(copy.deepcopy(d)))

        result = paper.partial_close_position(42, close_pct=0.50)

        # _save must have been called exactly once with the mutated data.
        assert saved, "partial_close_position must call _save"
        final_data = saved[0]

        trades = final_data["trades"]
        # After the split there should be 2 trade records: the remaining open portion
        # and the newly-appended closed portion.
        assert len(trades) == 2, (
            f"Expected 2 trade records after partial close, got {len(trades)}"
        )

        open_portion = next(
            (t for t in trades if not t.get("closed") and not t.get("settled")), None
        )
        closed_portion = next((t for t in trades if t.get("closed")), None)

        assert open_portion is not None, "Remaining open portion must still be present"
        assert closed_portion is not None, "Closed portion must be appended"

        assert open_portion["quantity"] == 5, (
            f"Remaining quantity must be 5 (50% of 10), got {open_portion['quantity']}"
        )
        assert closed_portion["quantity"] == 5, (
            f"Closed quantity must be 5 (50% of 10), got {closed_portion['quantity']}"
        )
        assert closed_portion["closed"] is True, "Closed portion must have closed=True"
        assert closed_portion.get("close_reason") == "partial_exit", (
            "Closed portion must carry close_reason='partial_exit'"
        )

        # The return value must be the closed portion.
        assert result is not None, (
            "partial_close_position must return the closed portion"
        )
        assert result["closed"] is True

        # Bug 1: no two trades may share the same id — validate_paper_trades_integrity
        # flags duplicate IDs as data corruption.
        all_ids = [t["id"] for t in trades]
        assert len(all_ids) == len(set(all_ids)), (
            f"Duplicate trade IDs detected after partial close: {all_ids}"
        )

        # Bug 2: the closed portion must NOT appear in get_open_trades() on the next
        # cron cycle.  get_open_trades() filters on settled only, so the closed portion
        # must be settled=True to be invisible to it.
        assert closed_portion.get("settled") is True, (
            "Closed portion must have settled=True so get_open_trades() does not re-surface it"
        )
        # Also verify directly via get_open_trades with the saved state.
        monkeypatch.setattr(paper, "_load", lambda: final_data)
        open_after = paper.get_open_trades()
        closed_ids_in_open = [t["id"] for t in open_after if t.get("closed")]
        assert not closed_ids_in_open, (
            f"Closed portion(s) leaked into get_open_trades(): {closed_ids_in_open}"
        )

    def test_partial_close_returns_none_for_missing_trade(self, monkeypatch):
        """partial_close_position must return None (not raise) when the trade id is not found."""
        import paper

        fake_data = {"trades": [], "balance": 1000.0}
        monkeypatch.setattr(paper, "_load", lambda: fake_data)
        monkeypatch.setattr(paper, "_save", lambda d: None)

        result = paper.partial_close_position(9999, close_pct=0.50)
        assert result is None, "Must return None when trade is not found"

    def test_partial_close_raises_on_invalid_pct(self, monkeypatch):
        """partial_close_position must raise ValueError for close_pct outside (0, 1]."""
        import paper

        fake_data = {"trades": [], "balance": 1000.0}
        monkeypatch.setattr(paper, "_load", lambda: fake_data)
        monkeypatch.setattr(paper, "_save", lambda d: None)

        with pytest.raises(ValueError):
            paper.partial_close_position(1, close_pct=0.0)

        with pytest.raises(ValueError):
            paper.partial_close_position(1, close_pct=1.5)


def test_take_profit_targets_for_yes_bet():
    from paper import get_take_profit_targets

    # Entry at 0.50 YES
    targets = get_take_profit_targets(entry_price=0.50, side="yes")
    assert len(targets) == 2
    # First rung: close 33% at entry * 1.25 = 0.625
    assert abs(targets[0]["price"] - 0.625) < 0.001
    assert targets[0]["close_pct"] == pytest.approx(0.333, abs=0.01)
    # Second rung: close 33% at entry * 1.45 = 0.725
    assert abs(targets[1]["price"] - 0.725) < 0.001
    assert targets[1]["close_pct"] == pytest.approx(0.333, abs=0.01)


# ---------------------------------------------------------------------------
# C3: Re-entry gate and eligibility tests
# ---------------------------------------------------------------------------


class TestReentryActive:
    def test_reentry_active_returns_false_when_settled_count_below_100(
        self, monkeypatch
    ):
        """_reentry_active() must return False when settled count < 100.

        Gate is DORMANT until both conditions are met — low count alone blocks it.
        """
        import order_executor

        # Reset cache so this test re-evaluates the gate from scratch.
        order_executor._reentry_state["active"] = None

        monkeypatch.setattr(
            "order_executor.count_settled_predictions", lambda: 80, raising=False
        )
        # Brier is good but count is not — gate must stay closed.
        monkeypatch.setattr(
            "order_executor._brier", lambda last_n=50: 0.20, raising=False
        )

        with (
            patch("tracker.count_settled_predictions", return_value=80),
            patch("tracker.brier_score", return_value=0.20),
        ):
            result = order_executor._reentry_active()

        assert result is False, (
            "_reentry_active must return False when settled count (80) < 100"
        )

        # Leave cache clean for other tests.
        order_executor._reentry_state["active"] = None

    def test_reentry_active_returns_true_and_notifies_when_both_conditions_met(self):
        """_reentry_active() must return True and call _notify_feature_activation
        exactly once when settled >= 100 AND Brier <= 0.23.
        """
        import order_executor

        order_executor._reentry_state["active"] = None

        notify_calls = []

        with (
            patch("tracker.count_settled_predictions", return_value=105),
            patch("tracker.brier_score", return_value=0.21),
            patch(
                "weather_markets._notify_feature_activation",
                side_effect=lambda key, msg, extra: notify_calls.append(
                    (key, msg, extra)
                ),
            ),
        ):
            result = order_executor._reentry_active()

        assert result is True, (
            "_reentry_active must return True when settled=105 and Brier=0.21"
        )
        assert len(notify_calls) == 1, (
            "_notify_feature_activation must be called exactly once on first activation"
        )
        assert notify_calls[0][0] == "c3_reentry", (
            "Notification key must be 'c3_reentry'"
        )

        order_executor._reentry_state["active"] = None


class TestReEntryEligible:
    def test_re_entry_eligible_returns_false_when_open_position_exists(
        self, monkeypatch
    ):
        """re_entry_eligible must return False when an open position exists on that ticker.

        Prevents doubling up if the close hasn't propagated yet or the function
        is called more than once in the same cron cycle.
        """
        import paper

        existing_trade = {
            "ticker": "KXHIGH-T70",
            "settled": False,
        }
        fake_data = {"trades": [existing_trade], "balance": 1000.0}
        monkeypatch.setattr(paper, "_load", lambda: fake_data)

        result = paper.re_entry_eligible("KXHIGH-T70")
        assert result is False, (
            "re_entry_eligible must return False when an open position exists on the ticker"
        )

    def test_re_entry_eligible_returns_true_when_no_open_position(self, monkeypatch):
        """re_entry_eligible must return True when no open position exists on the ticker."""
        import paper

        # Settled trade on the same ticker — should not block re-entry.
        settled_trade = {
            "ticker": "KXHIGH-T70",
            "settled": True,
        }
        fake_data = {"trades": [settled_trade], "balance": 1000.0}
        monkeypatch.setattr(paper, "_load", lambda: fake_data)

        result = paper.re_entry_eligible("KXHIGH-T70")
        assert result is True, (
            "re_entry_eligible must return True when the only trade on the ticker is settled"
        )
