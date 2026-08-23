"""Tests for early exit threshold and hold-time guards."""

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


class TestPassesExitGates:
    """Tests for paper._passes_exit_gates, the shared timing-gate helper
    extracted from check_stop_losses/check_breakeven_stops/check_model_exits
    (paper.py) and _check_early_exits/_check_live_model_exits (order_executor.py).
    """

    def test_no_gates_requested_passes(self):
        from paper import _passes_exit_gates

        assert _passes_exit_gates(ticker="X", log_tag="[T]") is True

    def test_hold_gate_blocks_when_too_soon(self):
        from paper import _passes_exit_gates

        entered_at = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                entered_at=entered_at,
                min_hold_hours=12,
            )
            is False
        )

    def test_hold_gate_passes_when_past_threshold(self):
        from paper import _passes_exit_gates

        entered_at = (datetime.now(UTC) - timedelta(hours=13)).isoformat()
        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                entered_at=entered_at,
                min_hold_hours=12,
            )
            is True
        )

    def test_hold_gate_fails_open_on_missing_entered_at(self):
        """Preserves the original inline behavior: a missing entered_at does NOT
        block the exit (fail-open — we cannot assess hold time)."""
        from paper import _passes_exit_gates

        assert (
            _passes_exit_gates(
                ticker="X", log_tag="[T]", entered_at="", min_hold_hours=12
            )
            is True
        )

    def test_hold_gate_fails_open_on_unparseable_entered_at(self):
        from paper import _passes_exit_gates

        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                entered_at="not-a-date",
                min_hold_hours=12,
            )
            is True
        )

    def test_settlement_gate_blocks_within_window(self):
        from paper import _passes_exit_gates

        close_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                close_time=close_time,
                settlement_gate_hours=24,
            )
            is False
        )

    def test_settlement_gate_passes_outside_window(self):
        from paper import _passes_exit_gates

        close_time = (datetime.now(UTC) + timedelta(hours=48)).isoformat()
        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                close_time=close_time,
                settlement_gate_hours=24,
            )
            is True
        )

    def test_settlement_gate_fails_closed_on_missing_close_time(self, caplog):
        """Preserves the original inline behavior: a missing close_time DOES block
        the exit (fail-closed — silently bypassing risks a settlement-convergence
        price), and logs a warning tagged with the caller's log_tag."""
        from paper import _passes_exit_gates

        with caplog.at_level("WARNING"):
            result = _passes_exit_gates(
                ticker="KXTEST-1",
                log_tag="[StopLoss]",
                close_time=None,
                settlement_gate_hours=24,
            )
        assert result is False
        assert "[StopLoss]" in caplog.text
        assert "KXTEST-1" in caplog.text

    def test_settlement_gate_fails_closed_on_unparseable_close_time(self):
        from paper import _passes_exit_gates

        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                close_time="not-a-date",
                settlement_gate_hours=24,
            )
            is False
        )

    def test_both_gates_hold_blocks_even_if_settlement_would_pass(self):
        from paper import _passes_exit_gates

        entered_at = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
        close_time = (datetime.now(UTC) + timedelta(hours=48)).isoformat()
        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                entered_at=entered_at,
                close_time=close_time,
                min_hold_hours=12,
                settlement_gate_hours=24,
            )
            is False
        )

    def test_both_gates_settlement_blocks_even_if_hold_would_pass(self):
        from paper import _passes_exit_gates

        entered_at = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        close_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                entered_at=entered_at,
                close_time=close_time,
                min_hold_hours=12,
                settlement_gate_hours=24,
            )
            is False
        )

    def test_both_gates_pass_together(self):
        from paper import _passes_exit_gates

        entered_at = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        close_time = (datetime.now(UTC) + timedelta(hours=48)).isoformat()
        assert (
            _passes_exit_gates(
                ticker="X",
                log_tag="[T]",
                entered_at=entered_at,
                close_time=close_time,
                min_hold_hours=12,
                settlement_gate_hours=24,
            )
            is True
        )


class TestModelExitShiftPpIsConfigurable:
    """MODEL_EXIT_SHIFT_PP replaced a hardcoded 0.25 literal in both
    _check_early_exits and _check_live_model_exits — prove the constant is
    actually read (not a dead import) by overriding it and checking a shift
    that was previously below threshold now triggers, and vice versa."""

    def test_lowering_threshold_triggers_previously_subthreshold_shift(
        self, monkeypatch
    ):
        import order_executor

        monkeypatch.setattr(order_executor, "MODEL_EXIT_SHIFT_PP", 0.20)

        new_trade = _make_trade(entered_hours_ago=24, side="yes")
        far_future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        new_trade["close_time"] = far_future

        mock_market = {"ticker": "KXWT-24-T50-B3", "yes_bid": 30}
        # entry_prob=0.65, forecast_prob=0.42 -> shift=0.23: above the lowered
        # 0.20 threshold but below the original 0.25 default.
        mock_analysis = {"forecast_prob": 0.42, "net_edge": -0.10}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        with (
            patch("order_executor.get_weather_markets", return_value=[mock_market]),
            patch("order_executor.enrich_with_forecast", return_value=mock_market),
            patch("order_executor.analyze_trade", return_value=mock_analysis),
            patch("paper.get_open_trades", return_value=[new_trade]),
            patch("paper.close_paper_early", return_value={"pnl": -1.0}),
        ):
            closed = order_executor._check_early_exits(mock_client)

        assert closed == 1, (
            "shift=0.23 must trigger an exit once MODEL_EXIT_SHIFT_PP is "
            "lowered to 0.20 — proves the constant is read live, not hardcoded"
        )

    def test_default_threshold_does_not_trigger_same_shift(self):
        """Sanity companion to the above: the same 0.23 shift must NOT exit
        under the real default (0.25) — proves the prior test's trigger really
        came from the lowered threshold, not from something else."""
        import order_executor

        assert order_executor.MODEL_EXIT_SHIFT_PP == pytest.approx(0.25)

        new_trade = _make_trade(entered_hours_ago=24, side="yes")
        far_future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        new_trade["close_time"] = far_future

        mock_market = {"ticker": "KXWT-24-T50-B3", "yes_bid": 30}
        mock_analysis = {"forecast_prob": 0.42, "net_edge": -0.10}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        with (
            patch("order_executor.get_weather_markets", return_value=[mock_market]),
            patch("order_executor.enrich_with_forecast", return_value=mock_market),
            patch("order_executor.analyze_trade", return_value=mock_analysis),
            patch("paper.get_open_trades", return_value=[new_trade]),
        ):
            closed = order_executor._check_early_exits(mock_client)

        assert closed == 0


class TestEarlyExitPricingConvention:
    """_check_early_exits must price a model-exit at the realizable bid/ask
    (_liquidation_price), not the bid/ask midpoint -- matching
    _check_live_model_exits' existing convention. Before this fix,
    _check_early_exits used _midpoint_price, which overvalues the position by
    half the bid-ask spread (see positions.liquidation_price's docstring)."""

    def _shifted_trade_and_analysis(self, side: str):
        trade = _make_trade(entered_hours_ago=24, side=side)
        far_future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        trade["close_time"] = far_future
        # entry_prob=0.65; shift a "yes" position via a low forecast_prob,
        # a "no" position via a high one -- either way, shift=0.35 > the
        # 0.25 default MODEL_EXIT_SHIFT_PP threshold.
        forecast_prob = 0.30 if side == "yes" else 1.0
        analysis = {"forecast_prob": forecast_prob, "net_edge": -0.10}
        return trade, analysis

    def test_exit_price_uses_liquidation_not_midpoint_yes_side(self):
        """yes_bid=20c/yes_ask=40c: liquidation (realizable) = 0.20 (the bid).
        The old midpoint convention would have booked 0.30 -- a $0.10/share
        overstatement that flows straight into pnl for every share held."""
        import order_executor

        trade, analysis = self._shifted_trade_and_analysis("yes")
        mock_market = {"ticker": trade["ticker"], "yes_bid": 20, "yes_ask": 40}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        captured = {}

        def _fake_close(trade_id, exit_price, reason=None):
            captured["exit_price"] = exit_price
            return {"pnl": 0.0}

        with (
            patch("order_executor.get_weather_markets", return_value=[mock_market]),
            patch("order_executor.enrich_with_forecast", return_value=mock_market),
            patch("order_executor.analyze_trade", return_value=analysis),
            patch("paper.get_open_trades", return_value=[trade]),
            patch("paper.close_paper_early", side_effect=_fake_close) as mock_close,
        ):
            closed = order_executor._check_early_exits(mock_client)

        assert closed == 1
        mock_close.assert_called_once()
        assert captured["exit_price"] == pytest.approx(0.20), (
            f"Expected the realizable bid (0.20), got {captured['exit_price']} "
            "-- the old midpoint convention would have produced 0.30"
        )

    def test_exit_price_uses_liquidation_not_midpoint_no_side(self):
        """yes_bid=60c/yes_ask=80c, held side NO: liquidation (realizable) =
        1 - yes_ask = 0.20. The old midpoint convention would have booked
        0.30 (midpoint of the NO market's own 0.20/0.40 bid-ask)."""
        import order_executor

        trade, analysis = self._shifted_trade_and_analysis("no")
        mock_market = {"ticker": trade["ticker"], "yes_bid": 60, "yes_ask": 80}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        captured = {}

        def _fake_close(trade_id, exit_price, reason=None):
            captured["exit_price"] = exit_price
            return {"pnl": 0.0}

        with (
            patch("order_executor.get_weather_markets", return_value=[mock_market]),
            patch("order_executor.enrich_with_forecast", return_value=mock_market),
            patch("order_executor.analyze_trade", return_value=analysis),
            patch("paper.get_open_trades", return_value=[trade]),
            patch("paper.close_paper_early", side_effect=_fake_close) as mock_close,
        ):
            closed = order_executor._check_early_exits(mock_client)

        assert closed == 1
        mock_close.assert_called_once()
        assert captured["exit_price"] == pytest.approx(0.20), (
            f"Expected the realizable NO price (1 - yes_ask = 0.20), got "
            f"{captured['exit_price']} -- the old midpoint convention would "
            "have produced 0.30"
        )

    def test_skips_cycle_on_missing_quote_not_fallback_to_entry_price(self, caplog):
        """A missing/invalid quote must skip this cycle (matching
        _check_live_model_exits' behavior), not fall back to entry_price --
        that fallback is the stop-loss/breakeven family's convention, a
        different function family with a different contract. Paired with a
        positive control: the debug skip message actually appearing proves
        the shift/hold/settlement gates were all passed and the code reached
        the price-computation branch, rather than the trade being filtered
        out earlier for an unrelated reason (which would make the "0 closed"
        assertion below pass vacuously)."""
        import order_executor

        trade, analysis = self._shifted_trade_and_analysis("yes")
        # No yes_bid/yes_ask fields at all -> coalesce_market_price returns
        # 0.0 for both -> liquidation_price returns None for the "yes" side.
        mock_market = {"ticker": trade["ticker"]}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        with (
            patch("order_executor.get_weather_markets", return_value=[mock_market]),
            patch("order_executor.enrich_with_forecast", return_value=mock_market),
            patch("order_executor.analyze_trade", return_value=analysis),
            patch("paper.get_open_trades", return_value=[trade]),
            patch("paper.close_paper_early") as mock_close,
            caplog.at_level("DEBUG"),
        ):
            closed = order_executor._check_early_exits(mock_client)

        assert closed == 0
        mock_close.assert_not_called()
        assert "could not compute exit price" in caplog.text, (
            "positive control: the skip-debug message must fire, proving the "
            "gates passed and the price-computation branch was actually "
            "reached (not blocked earlier by hold-time/settlement gates)"
        )

    def test_skips_cycle_when_no_side_liquidation_is_exactly_zero(self, caplog):
        """liquidation_price() returns 0.0 (NOT None) for a NO position when
        yes_ask=100c (1 - 1.0 = 0.0) -- only the `exit_price <= 0` half of the
        guard catches this, not `is None`. Without this test, mutating the
        guard to `if exit_price is None:` would still pass every other test
        in this class, since none of them exercise a non-None zero price."""
        import order_executor

        trade, analysis = self._shifted_trade_and_analysis("no")
        mock_market = {"ticker": trade["ticker"], "yes_ask": 100}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        with (
            patch("order_executor.get_weather_markets", return_value=[mock_market]),
            patch("order_executor.enrich_with_forecast", return_value=mock_market),
            patch("order_executor.analyze_trade", return_value=analysis),
            patch("paper.get_open_trades", return_value=[trade]),
            patch("paper.close_paper_early") as mock_close,
            caplog.at_level("DEBUG"),
        ):
            closed = order_executor._check_early_exits(mock_client)

        assert closed == 0
        mock_close.assert_not_called()
        assert "could not compute exit price" in caplog.text


class TestPositionSourcing:
    """backlog.txt's dict-vs-Position sourcing entry (batch-18): check_model_
    exits/_check_early_exits now build a positions.Position for each open
    trade via the shared _trade_to_position adapter (the same one paper.
    check_paper_position_exits already uses) instead of reading raw trade-
    dict fields directly, closing via PaperPositionStore.exit() rather than
    calling paper.close_paper_early()/_paper.close_paper_early() inline."""

    def test_check_model_exits_returns_full_original_trade_dict(self):
        """positions.Position only carries a fixed subset of fields (see its
        own docstring) -- check_model_exits must still return the ORIGINAL
        trade dict (with fields Position doesn't carry, e.g. "thesis") in
        the "trade" key, not a Position-derived reconstruction. A mistaken
        `"trade": pos.__dict__`-style change would silently drop this field
        and this test would catch it."""
        from paper import check_model_exits

        fake_trade = _make_trade(entered_hours_ago=24)
        fake_trade["thesis"] = "NWS ensemble spread favors YES by 12F"

        mock_analysis = {
            "net_edge": -0.20,  # clears the model_flipped threshold
            "edge": -0.20,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": fake_trade["ticker"]}

        with (
            patch("paper.get_open_trades", return_value=[fake_trade]),
            patch("weather_markets.enrich_with_forecast", return_value={}),
            patch("weather_markets.analyze_trade", return_value=mock_analysis),
        ):
            recs = check_model_exits(mock_client)

        assert len(recs) == 1
        assert recs[0]["trade"]["thesis"] == "NWS ensemble spread favors YES by 12F", (
            "the returned 'trade' dict must be the full original record, "
            "not a Position-shaped reconstruction that drops extra fields"
        )
        assert recs[0]["trade"]["id"] == fake_trade["id"]

    def test_check_early_exits_closes_correct_trade_among_multiple_open(self):
        """Two open paper trades, only one's shift clears MODEL_EXIT_SHIFT_PP
        -- proves the Position-based sourcing (built once from get_open_
        trades(), not re-fetched via store.get_open()) still targets the
        right trade id when closing. A list/id misalignment bug in the
        refactor would either close the wrong trade or close both."""
        import order_executor

        far_future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        trade_flip = _make_trade(entered_hours_ago=24, side="yes")
        trade_flip["id"] = 101
        trade_flip["ticker"] = "KXWT-FLIP"
        trade_flip["close_time"] = far_future
        trade_hold = _make_trade(entered_hours_ago=24, side="yes")
        trade_hold["id"] = 102
        trade_hold["ticker"] = "KXWT-HOLD"
        trade_hold["close_time"] = far_future

        market_flip = {"ticker": "KXWT-FLIP", "yes_bid": 30, "yes_ask": 34}
        market_hold = {"ticker": "KXWT-HOLD", "yes_bid": 63, "yes_ask": 67}

        def _fake_analyze(enriched):
            # entry_prob=0.65 for both; FLIP shifts 0.35 (>0.25 threshold),
            # HOLD shifts only 0.05 (stays open).
            if enriched.get("ticker") == "KXWT-FLIP":
                return {"forecast_prob": 0.30}
            return {"forecast_prob": 0.60}

        mock_client = MagicMock()
        closed_ids = []

        def _fake_close(trade_id, exit_price, reason=None):
            closed_ids.append(trade_id)
            return {"pnl": 0.0}

        with (
            patch(
                "order_executor.get_weather_markets",
                return_value=[market_flip, market_hold],
            ),
            patch("order_executor.enrich_with_forecast", side_effect=lambda m: m),
            patch("order_executor.analyze_trade", side_effect=_fake_analyze),
            patch("paper.get_open_trades", return_value=[trade_flip, trade_hold]),
            patch("paper.close_paper_early", side_effect=_fake_close),
        ):
            closed = order_executor._check_early_exits(mock_client)

        assert closed == 1
        assert closed_ids == [101], (
            f"expected only trade #101 (FLIP) to close, got {closed_ids}"
        )

    def test_check_model_exits_one_malformed_trade_does_not_drop_others(self, caplog):
        """Opus review finding (batch-18): the Position adapter must be built
        per-trade inside the per-trade try/except, not via a list
        comprehension batched ahead of the loop -- a batched
        `[_trade_to_position(t) for t in open_trades]` would raise on the
        FIRST malformed trade (missing "id", which _trade_to_position
        subscripts unguarded) before the loop even starts, dropping every
        other -- otherwise perfectly fine -- trade for that whole cycle. A
        good trade placed AFTER the bad one in the list must still be
        processed. Also asserts the malformed trade was logged, not silently
        swallowed (round-2 opus review INFO finding)."""
        from paper import check_model_exits

        bad_trade = _make_trade(entered_hours_ago=24)
        del bad_trade["id"]  # triggers _trade_to_position's unguarded t["id"]
        good_trade = _make_trade(entered_hours_ago=24)
        good_trade["id"] = 55
        good_trade["ticker"] = "KXWT-GOOD"

        mock_analysis = {
            "net_edge": -0.20,  # clears the model_flipped threshold
            "edge": -0.20,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": "KXWT-GOOD"}

        with (
            patch("paper.get_open_trades", return_value=[bad_trade, good_trade]),
            patch("weather_markets.enrich_with_forecast", return_value={}),
            patch("weather_markets.analyze_trade", return_value=mock_analysis),
            caplog.at_level("WARNING"),
        ):
            recs = check_model_exits(mock_client)

        assert len(recs) == 1, (
            "the good trade (listed after the malformed one) must still be "
            "processed and recommended for exit"
        )
        assert recs[0]["trade"]["id"] == 55
        assert "check_model_exits" in caplog.text and "failed" in caplog.text, (
            "the malformed trade must be logged, not silently dropped"
        )

    def test_check_early_exits_one_malformed_trade_does_not_drop_others(self, caplog):
        """Same claim as the model_exits test above, for the paper-side
        early-exit function. Also asserts the malformed trade was logged."""
        import order_executor

        far_future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        bad_trade = _make_trade(entered_hours_ago=24, side="yes")
        del bad_trade["id"]
        good_trade = _make_trade(entered_hours_ago=24, side="yes")
        good_trade["id"] = 77
        good_trade["ticker"] = "KXWT-GOOD2"
        good_trade["close_time"] = far_future

        market_good = {"ticker": "KXWT-GOOD2", "yes_bid": 30, "yes_ask": 34}

        closed_ids = []

        def _fake_close(trade_id, exit_price, reason=None):
            closed_ids.append(trade_id)
            return {"pnl": 0.0}

        with (
            patch("order_executor.get_weather_markets", return_value=[market_good]),
            patch("order_executor.enrich_with_forecast", side_effect=lambda m: m),
            patch(
                "order_executor.analyze_trade",
                return_value={"forecast_prob": 0.30},  # shift 0.35 > threshold
            ),
            patch("paper.get_open_trades", return_value=[bad_trade, good_trade]),
            patch("paper.close_paper_early", side_effect=_fake_close),
            caplog.at_level("WARNING"),
        ):
            closed = order_executor._check_early_exits(MagicMock())

        assert closed == 1
        assert "[EarlyExit] Error checking" in caplog.text, (
            "the malformed trade must be logged, not silently dropped"
        )
        assert closed_ids == [77], (
            "the good trade (listed after the malformed one) must still be "
            f"closed, got {closed_ids}"
        )


class TestBreakevenStops:
    def test_check_breakeven_stops_fires_when_peak_met_and_price_falls(self):
        """check_breakeven_stops must return the ticker when peak was met and price fell back."""
        import paper
        from utils import BREAKEVEN_TRIGGER_PCT

        far_future = "2099-01-01T00:00:00+00:00"  # well outside the 24h settlement gate
        trade = {
            "id": 1,
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
            [paper._trade_to_position(trade)],
            current_prices={"KXHIGH-T70": {"bid": 0.48, "ask": 0.48}},
        )
        tickers = [p.ticker for p in exits]
        assert "KXHIGH-T70" in tickers, (
            f"check_breakeven_stops should fire when price falls below entry. Got: {tickers}"
        )

    def test_check_breakeven_stops_silent_before_peak_is_met(self):
        """check_breakeven_stops must NOT fire when peak_profit_pct is below the trigger."""
        import paper
        from utils import BREAKEVEN_TRIGGER_PCT

        far_future = "2099-01-01T00:00:00+00:00"
        trade = {
            "id": 1,
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
            [paper._trade_to_position(trade)],
            current_prices={"KXHIGH-T70": {"bid": 0.40, "ask": 0.40}},
        )
        assert exits == [], f"Should not fire when peak not yet met. Got: {exits}"

    def test_update_peak_profits_sets_peak_on_new_high(self, monkeypatch):
        """update_peak_profits must record a new peak when unrealized profit exceeds stored peak."""
        import paper
        from positions import update_peak_profits

        # PaperPositionStore.save_peak calls paper._load()/_save() internally.
        # Monkeypatch those to control the data without file I/O.
        trade = {
            "id": 1,
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

        store = paper.PaperPositionStore()
        # yes_bid = 0.65 → unrealized_profit_pct = (0.65 - 0.50) * 10 / 5.00 = 0.30 (30%)
        update_peak_profits(
            [paper._trade_to_position(trade)],
            current_prices={"KXHIGH-T70": {"bid": 0.65, "ask": 0.65}},
            save_peak=store.save_peak,
        )

        assert saved, "update_peak_profits must call _save when a new peak is found"
        updated_trade = saved[0]["trades"][0]
        assert updated_trade["peak_profit_pct"] == pytest.approx(0.30, abs=0.01), (
            f"Expected peak_profit_pct ≈ 0.30, got {updated_trade.get('peak_profit_pct')}"
        )
