"""Tests for live execution path in main.py."""

import pytest


class TestMidpointPrice:
    def test_midpoint_yes_side(self):
        from main import _midpoint_price

        market = {"yes_bid": 45, "yes_ask": 55}
        assert _midpoint_price(market, "yes") == pytest.approx(0.50)

    def test_midpoint_no_side(self):
        from main import _midpoint_price

        market = {"yes_bid": 45, "yes_ask": 55}
        # no_bid = 100 - yes_ask = 45; no_ask = 100 - yes_bid = 55 → midpoint = 0.50
        assert _midpoint_price(market, "no") == pytest.approx(0.50)


class TestLoadLiveConfig:
    def test_creates_default_if_missing(self, tmp_path, monkeypatch):
        import main

        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", tmp_path / "live_config.json")
        cfg = main._load_live_config()
        assert cfg["max_trade_dollars"] == 50
        assert cfg["daily_loss_limit"] == 200
        assert cfg["max_open_positions"] == 10
        assert (tmp_path / "live_config.json").exists()


class TestPlaceLiveOrder:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_daily_loss_limit_blocks_after_db_loss(self):
        """Daily loss limit blocks order when DB-backed loss is at or above limit."""
        import execution_log
        import main

        # Seed today's loss at the limit
        execution_log.add_live_loss(100.0)

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 100,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        placed, cost = main._place_live_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            analysis={
                "kelly_quantity": 2,
                "implied_prob": 0.55,
                "market": {"yes_bid": 50, "yes_ask": 60},
            },
            config=config,
            client=None,
            cycle="12z",
        )
        assert placed is False
        assert cost == 0.0

    def test_daily_live_spend_cap_blocks_across_cycles(self, monkeypatch):
        """Deep-review followup: F7 removed placement-time add_live_loss(cost)
        (correctly, it double-counted with settlement-time add_live_loss(-pnl)),
        but that call had also been the only cross-cycle brake on live spend --
        _daily_paper_spend()/_daily_sameday_spend() never see live orders.
        A long-running `watch --auto --live` session (5-min loop) would
        otherwise reset its live-spend view to $0 every cycle. Confirm a
        prior cycle's already-logged live spend (simulating an earlier
        iteration of the same session) blocks a new placement that would
        otherwise succeed, via the dedicated spend counter -- and that the
        API is never even called once the cap is reached. Bypasses every
        OTHER gate (trading gate, cycle dedup, open-position count) so the
        new spend cap is the sole thing under test -- proven by first
        confirming the identical setup places successfully with the cap
        raised."""
        from unittest.mock import MagicMock, patch

        import execution_log
        import order_executor

        # Simulate a live order placed in an earlier watch cycle this same
        # UTC day: 20 contracts @ $0.55 = $11.00.
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T70",
            side="yes",
            quantity=20,
            price=0.55,
            status="filled",
            live=True,
        )

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_test",
            "status": "resting",
        }
        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 1000,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        analysis = {
            "kelly_quantity": 2,
            "implied_prob": 0.55,
            "market": {"yes_bid": 50, "yes_ask": 60},
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch.object(order_executor, "_count_open_live_orders", return_value=0),
        ):
            # Control: with a cap well above the already-logged $11.00, this
            # exact setup must succeed -- proves the block below is really
            # the spend cap, not some other gate this test forgot to mock.
            monkeypatch.setattr(
                order_executor, "MAX_DAILY_SPEND", 1000.0, raising=False
            )
            placed_ok, cost_ok = order_executor._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )
            assert placed_ok is True, "control case must place — setup is broken"
            assert cost_ok > 0.0

            mock_client.reset_mock()
            monkeypatch.setattr(order_executor, "MAX_DAILY_SPEND", 10.0, raising=False)
            placed, cost = order_executor._place_live_order(
                ticker="KXHIGH-25MAY15-T76",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert placed is False
        assert cost == 0.0
        mock_client.place_order.assert_not_called()

    def test_daily_loss_limit_blocks_without_keyerror_when_key_missing(self):
        """F10: config['daily_loss_limit'] was bare-indexed in the print on
        the same branch as a .get()-defaulted comparison — reachable when
        get_today_live_loss() fails closed to inf (degraded-DB path) and the
        config has no daily_loss_limit key at all. Must skip cleanly, not
        raise KeyError."""
        import execution_log
        import main

        # _degraded_flag_path() is DB_PATH.parent / "..." — DB_PATH.parent is
        # the shared system temp dir here, so this flag must be cleared even
        # on assertion failure or it leaks into unrelated tests.
        execution_log._set_degraded_flag("test")  # forces get_today_live_loss() -> inf
        try:
            config = {
                "max_trade_dollars": 50,
                "max_open_positions": 10,
                "gtc_cancel_hours": 24,
            }
            placed, cost = main._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis={
                    "kelly_quantity": 2,
                    "implied_prob": 0.55,
                    "market": {"yes_bid": 50, "yes_ask": 60},
                },
                config=config,
                client=None,
                cycle="12z",
            )
            assert placed is False
            assert cost == 0.0
        finally:
            execution_log._clear_degraded_flag()

    def test_max_trade_dollars_caps_size(self):
        """Kelly wants 10 contracts at $0.55 = $5.50/contract → $55 total, capped to $50."""
        from unittest.mock import MagicMock, patch

        import main

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_abc123",
            "status": "resting",
        }

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        analysis = {
            "kelly_quantity": 10,
            "implied_prob": 0.55,
            "market": {"yes_bid": 50, "yes_ask": 60},
            "edge": 0.25,
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch("execution_log.log_order", return_value=1),
            patch.object(main, "_count_open_live_orders", return_value=0),
        ):
            placed, cost = main._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert placed is True
        # price = midpoint(50, 60) = 0.55; Kelly qty 10 × $0.55 = $5.50 < $50 cap → 10 contracts
        assert mock_client.place_order.called
        assert cost > 0.0
        call_args = mock_client.place_order.call_args
        assert call_args.kwargs["price"] == pytest.approx(0.55)


class TestAutoPlaceTradesCycleCheck:
    def test_cycle_dedup_skips_already_ordered(self, monkeypatch):
        """If was_ordered_this_cycle returns True, no paper or live order is placed."""
        from unittest.mock import patch

        import main

        # Construct opp with the real field names _auto_place_trades checks:
        # net_signal must contain "STRONG", time_risk must not be "HIGH",
        # ci_adjusted_kelly must be large enough to produce qty >= 1,
        # market_prob used as entry_price.
        opp = {
            "ticker": "KXHIGH-25MAY15-T75",
            "net_signal": "STRONG_BUY",
            "time_risk": "LOW",
            "recommended_side": "yes",
            "ci_adjusted_kelly": 0.50,
            "market_prob": 0.55,
            "_city": "Houston",
            "_date": None,
        }

        mock_open_trades = []

        with (
            patch("paper.get_open_trades", return_value=mock_open_trades),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.kelly_quantity", return_value=2),
            patch("paper.portfolio_kelly_fraction", return_value=0.10),
            patch("execution_log.was_ordered_this_cycle", return_value=True),
            patch("main.place_paper_order") as mock_paper,
            patch("main._place_live_order") as mock_live,
        ):
            main._auto_place_trades([opp], client=None, live=False, live_config=None)

        mock_paper.assert_not_called()
        mock_live.assert_not_called()


class TestOpenTradesListLivePath:
    """F6: _open_trades_list.append(trade) only ever ran on the paper branch.
    A live placement earlier in the same cron cycle was invisible to later
    candidates' VaR/correlation checks — each got scored as if it were the
    first position in the portfolio."""

    def test_live_placement_appends_to_open_trades_list(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        import main
        import order_executor

        monkeypatch.setattr(order_executor, "MAX_VAR_DOLLARS", 1000.0, raising=False)

        var_calls: list[list] = []

        def _fake_portfolio_var(trades):
            var_calls.append(list(trades))
            return 0.0  # well under the cap — never blocks placement

        import time as _time

        def _opp(ticker: str, city: str) -> dict:
            return {
                "ticker": ticker,
                "net_signal": "STRONG_BUY",
                "time_risk": "LOW",
                "recommended_side": "yes",
                "ci_adjusted_kelly": 0.50,
                "market_prob": 0.55,
                "forecast_prob": 0.70,
                "net_edge": 0.20,
                "edge": 0.20,
                "model_consensus": True,
                "data_fetched_at": _time.time(),
                "yes_bid": 53,
                "yes_ask": 57,
                "_city": city,
                "_date": None,
                # Same-day (METAR lock-in) trades skip _in_gfs_update_window() --
                # without this, the test's outcome depends on the real wall-clock
                # UTC minute vs. order_executor's GFS update hours, making it
                # spuriously fail whenever it happens to run inside that window.
                "days_out": 0,
            }

        opp1 = _opp("KXHIGH-A", "Houston")
        opp2 = _opp("KXHIGH-B", "Austin")
        live_config = {
            "daily_loss_limit": 500,
            "max_open_positions": 10,
            "max_trade_dollars": 100,
        }
        client = MagicMock()
        client.get_market.side_effect = ConnectionError("no live fetch in test")

        with (
            patch("paper.get_open_trades", return_value=[]),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.kelly_quantity", return_value=2),
            patch("paper.portfolio_kelly_fraction", return_value=0.10),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch("monte_carlo.portfolio_var", side_effect=_fake_portfolio_var),
            patch.object(order_executor, "_resolve_live_balance", return_value=0.0),
            patch.object(order_executor, "_place_live_order", return_value=(True, 5.0)),
        ):
            main._auto_place_trades(
                [opp1, opp2], client=client, live=True, live_config=live_config
            )

        assert len(var_calls) == 2, (
            f"expected one VaR check per opp, got {len(var_calls)}"
        )
        assert len(var_calls[1]) == len(var_calls[0]) + 1, (
            "the second opp's VaR check must see the first live trade placed "
            "earlier this same cycle — it was invisible before this fix"
        )


class TestVarGateFailsClosed:
    """F5: a portfolio_var() exception used to be swallowed at DEBUG and the
    trade placed anyway — the flash-crash check in this same file explicitly
    fails closed on its own internal errors; the VaR gate now matches."""

    def test_var_computation_error_skips_the_trade(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        import main
        import order_executor

        monkeypatch.setattr(order_executor, "MAX_VAR_DOLLARS", 1000.0, raising=False)

        import time as _time

        opp = {
            "ticker": "KXHIGH-A",
            "net_signal": "STRONG_BUY",
            "time_risk": "LOW",
            "recommended_side": "yes",
            "ci_adjusted_kelly": 0.50,
            "market_prob": 0.55,
            "forecast_prob": 0.70,
            "net_edge": 0.20,
            "edge": 0.20,
            "model_consensus": True,
            "data_fetched_at": _time.time(),
            "yes_bid": 53,
            "yes_ask": 57,
            "_city": "Houston",
            "_date": None,
        }

        placed = []
        with (
            patch("paper.get_open_trades", return_value=[]),
            patch("paper.is_paused_drawdown", return_value=False),
            patch("paper.is_daily_loss_halted", return_value=False),
            patch("paper.is_streak_paused", return_value=False),
            patch("paper.kelly_quantity", return_value=2),
            patch("paper.portfolio_kelly_fraction", return_value=0.10),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch(
                "monte_carlo.portfolio_var",
                side_effect=RuntimeError("simulation blew up"),
            ),
            patch.object(
                order_executor,
                "place_paper_order",
                side_effect=lambda *a, **kw: placed.append(1) or {"id": 1},
            ),
        ):
            main._auto_place_trades([opp], client=MagicMock(), live=False)

        assert not placed, (
            "a VaR computation error must skip the trade (fail closed), not "
            "place it as if the check had passed"
        )


class TestRecoverPendingOrders:
    """2026-07-09: Kalshi's real order-status enum is resting/canceled/executed
    -- there is no "filled" or "expired". _recover_pending_orders previously
    checked api_status in ("filled", "canceled", "expired"), so a genuinely
    executed order fell through to the "unknown API status -- leaving
    pending" branch and was never resolved."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_executed_order_resolves_to_internal_filled_status(self):
        """A pending row whose order actually executed must resolve to this
        bot's internal 'filled' term, not be left stuck on 'pending'."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc123"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_abc123",
            "status": "executed",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"

    def test_canceled_order_resolves_to_canceled(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_xyz"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_xyz",
            "status": "canceled",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "canceled"

    def test_partial_fill_then_cancel_resolves_to_filled(self):
        """F9: Kalshi has no distinct 'partially filled' status -- an order
        that fills some contracts and then gets canceled for the remainder
        reports status="canceled" with a nonzero fill_count_fp. That must
        resolve to 'filled' (not 'canceled') so it still reaches
        get_filled_unsettled_live_orders() and gets settled; otherwise a
        real, live exchange position is silently dropped and never counted
        toward P&L."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_partial"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_partial",
            "status": "canceled",
            "fill_count_fp": "2.00",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"
        assert row["fill_quantity"] == 2

    def test_resting_order_resolves_to_pending(self):
        """A resting order must land on status='pending' — the only status
        every downstream consumer (fill polling, GTC cancel, max_open_positions,
        PnL summary) actually filters on. F1: 'placed' was a dead-end status
        invisible to all of them."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_rest"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_rest",
            "status": "resting",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "pending"

    def test_resting_order_recovery_preserves_response_for_fill_polling(self):
        """Deep-review followup: log_order_result() does an unconditional
        column UPDATE, so a resting->pending recovery call that omits
        response= overwrites the stored order_id with NULL.
        _poll_pending_orders' own pending-row filter requires
        o.get("response") (line ~350) -- without it, a crash-recovered
        resting order becomes permanently invisible to fill polling,
        pre-close cancel, and the GTC-age cancel, silently re-orphaning the
        exact order this recovery path exists to reattach to the
        lifecycle."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _poll_pending_orders, _recover_pending_orders

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_rest2"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_rest2",
            "status": "resting",
        }

        _recover_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["response"] is not None, (
            "response was wiped to NULL by the recovery UPDATE, erasing order_id"
        )

        # Now confirm the row is actually still reachable by fill polling.
        mock_client.get_order.return_value = {
            "order_id": "ord_rest2",
            "status": "executed",
            "fill_count_fp": "2.00",
        }
        _poll_pending_orders(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled", (
            "order became invisible to _poll_pending_orders after recovery "
            "nulled its response/order_id"
        )


class TestFinalizeCancel:
    """F9 followup: _finalize_cancel() is the shared post-cancel_order()
    fill-check used by both the pre-close cancel and GTC-age cancel paths in
    _poll_pending_orders -- covering it directly here exercises both call
    sites without duplicating the trigger machinery for each."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_zero_fill_cancel_stays_canceled(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        _finalize_cancel(mock_client, "ord_1", row_id)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "canceled"

    def test_partial_fill_cancel_promotes_to_filled(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "4.00",
        }

        _finalize_cancel(mock_client, "ord_2", row_id)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "filled"
        assert row["fill_quantity"] == 4

    def test_get_order_failure_falls_back_to_plain_canceled(self):
        """The cancel itself already happened -- a failed follow-up query
        must not leave the row stuck on 'pending' or raise; it must still
        record the cancel, just without fill-count enrichment."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        _finalize_cancel(mock_client, "ord_3", row_id)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "canceled"


class TestPollPendingOrders:
    def test_filled_order_updates_status(self, monkeypatch):
        """_poll_pending_orders updates a pending live order to 'filled' when API returns filled."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        import execution_log
        import main

        # Use a fresh temp DB
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        monkeypatch.setattr(execution_log, "DB_PATH", Path(tmp.name))
        monkeypatch.setattr(execution_log, "_initialized", False)

        # Log a pending live order — response uses the real Kalshi API envelope shape
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc123"},
        )

        # Mock client that returns Kalshi's real "executed" status (not "filled" --
        # that's this bot's own internal term, translated by
        # _kalshi_status_to_internal; Kalshi's actual enum is
        # resting/canceled/executed).
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_abc123",
            "status": "executed",
            # F9: Kalshi's real field is "fill_count_fp" (fixed-point string),
            # not "fill_quantity" -- confirmed against the same shape main.py
            # already reads fill_count_fp from.
            "fill_count_fp": "2.00",
        }

        main._poll_pending_orders(mock_client)

        # Verify the order was updated
        orders = execution_log.get_recent_orders(limit=10)
        assert orders[0]["status"] == "filled"
        # F9: fill_quantity must be parsed from fill_count_fp, not left None
        # (which would silently fall back to the full requested quantity at
        # settlement instead of the true fill count).
        assert orders[0]["fill_quantity"] == pytest.approx(2.0)

        import gc

        gc.collect()
        execution_log._initialized = False
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)


class TestPollPendingOrdersExtended:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        from pathlib import Path

        Path(self._tmp.name).unlink(missing_ok=True)

    def test_gtc_cancel_fires_for_old_pending_order(self):
        """Orders older than gtc_cancel_hours are cancelled via the API."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc"},
        )
        # Backdate placed_at to 2 hours ago
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", (old_time, row_id)
            )

        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}

        config = {"gtc_cancel_hours": 1}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_called_once_with("ord_abc")
        orders = execution_log.get_recent_orders(limit=10)
        # F8: unified to "canceled" (American, matching Kalshi's own API and
        # _kalshi_status_to_internal) — was the British "cancelled" spelling,
        # which was invisible to was_ordered_recently's NOT IN ('failed',
        # 'canceled') exclusion, wrongly blocking re-entry for 7 days.
        assert orders[0]["status"] == "canceled"

    def test_gtc_age_cancel_with_partial_fill_resolves_to_filled(self):
        """F9 followup: cancel_order() alone doesn't reveal whether the order
        partially filled right before cancellation -- Kalshi has no distinct
        "partially filled" status. _finalize_cancel() must query get_order()
        after cancelling and promote to "filled" with the real fill count
        when one exists, or the position silently never reaches settlement."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_partial_gtc"},
        )
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", (old_time, row_id)
            )

        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "order_id": "ord_partial_gtc",
            "status": "canceled",
            "fill_count_fp": "3.00",
        }

        config = {"gtc_cancel_hours": 1}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_called_once_with("ord_partial_gtc")
        orders = execution_log.get_recent_orders(limit=10)
        row = next(o for o in orders if o["id"] == row_id)
        assert row["status"] == "filled"
        assert row["fill_quantity"] == 3

    def test_gtc_cancel_skips_fresh_orders(self):
        """Orders younger than gtc_cancel_hours are not cancelled."""
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_fresh"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {"status": "resting"}

        config = {"gtc_cancel_hours": 999}
        main._poll_pending_orders(mock_client, config=config)

        mock_client.cancel_order.assert_not_called()

    def test_settlement_recorded_for_finalized_market(self):
        """When a filled YES order's market is finalized (YES wins), P&L is computed and recorded."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        assert order["outcome_yes"] == 1
        assert order["settled_at"] is not None
        # pnl = 2 * (1 - 0.55) * (1 - fee); live fills are always maker
        # (resting midpoint GTC limit), which pays $0 on this bot's markets —
        # see utils.KALSHI_MAKER_FEE_RATE. pnl = 2 * 0.45 * 1.0 = 0.90
        assert order["pnl"] == pytest.approx(0.90, rel=1e-3)

    def test_no_side_settlement_yes_wins(self):
        """NO bet loses when YES wins: pnl = -qty * price (NO contract cost)."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        # price stores the NO contract price: YES=0.40 market → NO costs 0.60
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="no",
            quantity=3,
            price=0.60,
            status="filled",
            live=True,
            fill_quantity=3,
        )

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",  # YES wins → NO loses
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        assert order["outcome_yes"] == 1
        assert order["settled_at"] is not None
        # pnl = -3 * 0.60 = -1.80
        assert order["pnl"] == pytest.approx(-1.80, rel=1e-3)

    def test_no_side_settlement_no_wins(self):
        """NO bet wins when NO wins: pnl = qty * (1 - price) * (1 - fee)."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        # price stores the NO contract price: YES=0.40 market → NO costs 0.60
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="no",
            quantity=3,
            price=0.60,
            status="filled",
            live=True,
            fill_quantity=3,
        )

        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "no",  # NO wins → NO bet pays out
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        orders = execution_log.get_recent_orders(limit=10)
        order = orders[0]
        assert order["outcome_yes"] == 0
        assert order["settled_at"] is not None
        # pnl = 3 * (1 - 0.60) * (1 - fee); maker fee is $0 on this bot's
        # markets — see utils.KALSHI_MAKER_FEE_RATE. pnl = 3 * 0.40 * 1.0 = 1.20
        assert order["pnl"] == pytest.approx(1.20, rel=1e-3)

    def test_settlement_loss_does_not_double_count(self):
        """F7: a losing settlement must add exactly the loss to the daily
        counter, not double it. Before the fix, add_live_loss(cost) at
        placement PLUS add_live_loss(-pnl) at settlement (pnl=-cost for a
        full loss) added the same cost twice."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )
        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "no",  # YES bet loses
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        # pnl = -2 * 0.55 = -1.10 -> add_live_loss(-pnl) adds exactly 1.10.
        # 2.20 (double) would indicate the old placement-time double-count.
        assert execution_log.get_today_live_loss() == pytest.approx(1.10, rel=1e-3)

    def test_settlement_win_credits_the_counter(self):
        """F7: a winning settlement must credit (reduce) the daily counter —
        under the old bug, a win left cost-minus-profit stuck as a phantom
        'loss' because the placement-time cost was never refunded."""
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock

        import execution_log
        import main

        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
            fill_quantity=2,
        )
        close_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        mock_client = MagicMock()
        mock_client.get_market.return_value = {
            "status": "finalized",
            "result": "yes",  # YES bet wins
            "close_time": close_time,
        }

        main._poll_pending_orders(mock_client, config={})

        # pnl = 2*(1-0.55)*(1-fee) = 0.90 (profit; maker fee is $0 on this
        # bot's markets — see utils.KALSHI_MAKER_FEE_RATE) -> add_live_loss(-pnl)
        # is a credit of -0.90, not a lingering positive "loss".
        assert execution_log.get_today_live_loss() == pytest.approx(-0.90, rel=1e-3)


class TestPlaceLiveOrderDedup:
    """_place_live_order must return (False, 0.0) when the ticker was already
    ordered this cycle — testing the dedup check INSIDE the function itself,
    not the higher-level _auto_place_trades wrapper that mocks it away."""

    def test_returns_false_when_already_ordered_this_cycle(self):
        import os
        from unittest.mock import MagicMock, patch

        import order_executor

        ticker = "KXHIGHNY-26MAY17-T72"
        cycle = "18z"
        mock_client = MagicMock()

        analysis = {
            "market": {"yes_bid": 60, "yes_ask": 65, "no_bid": 35},
            "kelly_quantity": 3,
            "edge": 0.12,
        }
        config = {
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "max_trade_dollars": 50,
        }

        with (
            # Pass the env / gate checks
            patch("trading_gates.pre_live_trade_check", return_value=None),
            patch.dict(
                os.environ,
                {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "true"},
            ),
            # Daily loss and open-position checks pass
            patch("order_executor.execution_log.get_today_live_loss", return_value=0),
            patch("order_executor._count_open_live_orders", return_value=0),
            # Dedup: ticker already ordered this cycle
            patch(
                "order_executor.execution_log.was_ordered_this_cycle",
                return_value=True,
            ),
        ):
            placed, cost = order_executor._place_live_order(
                ticker=ticker,
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle=cycle,
            )

        assert placed is False, (
            "should not place when ticker already ordered this cycle"
        )
        assert cost == 0.0
        mock_client.place_order.assert_not_called()

    def test_places_order_when_not_yet_ordered(self):
        """Positive control: order fires when dedup finds no prior order this cycle."""
        import os
        from unittest.mock import MagicMock, patch

        import order_executor

        ticker = "KXHIGHNY-26MAY17-T72"
        cycle = "18z"
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order": {"id": "ord_abc", "status": "resting"}
        }

        analysis = {
            "market": {"yes_bid": 60, "yes_ask": 65, "no_bid": 35},
            "kelly_quantity": 3,
            "edge": 0.12,
        }
        config = {
            "daily_loss_limit": 200,
            "max_open_positions": 10,
            "max_trade_dollars": 50,
        }

        with (
            patch("trading_gates.pre_live_trade_check", return_value=None),
            patch.dict(
                os.environ,
                {"KALSHI_ENV": "prod", "LIVE_TRADING_ENABLED": "true"},
            ),
            patch("order_executor.execution_log.get_today_live_loss", return_value=0),
            patch("order_executor._count_open_live_orders", return_value=0),
            # Dedup: not yet ordered this cycle
            patch(
                "order_executor.execution_log.was_ordered_this_cycle",
                return_value=False,
            ),
            patch("order_executor.execution_log.log_order", return_value=1),
            patch("order_executor.execution_log.log_order_result"),
        ):
            placed, cost = order_executor._place_live_order(
                ticker=ticker,
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle=cycle,
            )

        assert placed is True
        mock_client.place_order.assert_called_once()


class TestFinalizeCancelReturnValue:
    """_finalize_cancel now returns (status, fill_count, raw_api_status) so
    reprice/taker-cross logic can decide whether it's safe to place a
    replacement order -- raw_api_status specifically so callers can tell a
    genuine Kalshi-confirmed "canceled" apart from an unrecognized/in-flight
    status (e.g. "resting") that resolved_status defaults to "canceled" too."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_returns_canceled_zero_on_clean_cancel(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_1", row_id
        )
        assert status == "canceled"
        assert fill_count == 0
        assert raw_api_status == "canceled"

    def test_returns_filled_with_count_on_partial_fill(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "4.00",
        }

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_2", row_id
        )
        assert status == "filled"
        assert fill_count == 4
        assert raw_api_status == "canceled"

    def test_returns_sentinel_negative_one_when_verification_query_fails(self):
        """Fill state genuinely unknown here -- callers must fail closed
        (never place a replacement) rather than assume fill_count=0."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_3", row_id
        )
        assert status == "canceled"
        assert fill_count == -1
        assert raw_api_status is None

    def test_raw_api_status_preserved_when_still_resting(self):
        """A cancel that hasn't propagated yet (Kalshi still reports
        "resting") must surface that in raw_api_status even though
        resolved_status collapses it to "canceled" for the pre-existing
        GTC/pre-close callers that don't need this distinction."""
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _finalize_cancel

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "resting",
            "fill_count_fp": "0.00",
        }

        status, fill_count, raw_api_status = _finalize_cancel(
            mock_client, "ord_4", row_id
        )
        assert status == "canceled"  # collapsed default, for existing callers
        assert raw_api_status == "resting"  # but the raw truth is preserved


class TestGetCurrentBook:
    def test_uses_ws_cache_when_fresh_and_complete(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        with patch(
            "kalshi_ws.get_cached_book",
            return_value={"yes_bid": 0.40, "yes_ask": 0.45, "mid_price": 0.425},
        ):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book == {"yes_bid": 0.40, "yes_ask": 0.45}
        mock_client.get_market.assert_not_called()

    def test_falls_back_to_rest_when_ws_cache_missing(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.return_value = {"yes_bid": 0.38, "yes_ask": 0.42}
        with patch("kalshi_ws.get_cached_book", return_value=None):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book == {"yes_bid": 0.38, "yes_ask": 0.42}
        mock_client.get_market.assert_called_once()

    def test_falls_back_to_rest_when_ws_entry_one_sided(self):
        """A one-sided WS book (no real ask) must not be treated as usable --
        falls through to REST. kalshi_ws.parse_message's ticker branch
        defaults a missing side to 0.0, not None
        (yes_ask_str = inner.get("yes_ask") or "0") -- this is the real
        sentinel production actually produces, not None."""
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.return_value = {"yes_bid": 0.38, "yes_ask": 0.42}
        with patch(
            "kalshi_ws.get_cached_book",
            return_value={"yes_bid": 0.40, "yes_ask": 0.0, "mid_price": 0.40},
        ):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book == {"yes_bid": 0.38, "yes_ask": 0.42}

    def test_returns_none_when_both_sources_unavailable(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.side_effect = ConnectionError("down")
        with patch("kalshi_ws.get_cached_book", return_value=None):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book is None

    def test_returns_none_when_rest_market_has_no_quote(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _get_current_book

        mock_client = MagicMock()
        mock_client.get_market.return_value = {}
        with patch("kalshi_ws.get_cached_book", return_value=None):
            book = _get_current_book(mock_client, "KXHIGH-25MAY15-T75")

        assert book is None


class TestLiveMinEdge:
    def test_defaults_to_min_edge_constant(self, monkeypatch):
        import order_executor
        from order_executor import _live_min_edge

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        assert _live_min_edge({}) == 0.07

    def test_uses_confidence_tier_when_spread_present(self):
        from unittest.mock import patch

        from order_executor import _live_min_edge

        with patch("utils.get_min_edge_for_confidence", return_value=0.20) as mock_tier:
            result = _live_min_edge({"ensemble_spread": 3.5})

        assert result == 0.20
        mock_tier.assert_called_once_with(3.5, is_live=True)

    def test_falls_back_to_min_edge_on_tier_exception(self, monkeypatch):
        import order_executor
        from order_executor import _live_min_edge

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        from unittest.mock import patch

        with patch(
            "utils.get_min_edge_for_confidence", side_effect=RuntimeError("boom")
        ):
            result = _live_min_edge({"ensemble_spread": 3.5})

        assert result == 0.07


class TestClearsTakerFee:
    """_clears_taker_fee recomputes net_edge with the real taker fee instead
    of the maker fee analyze_trade() actually used -- deciding whether
    crossing as taker (guaranteed fill, real fee) beats continuing to wait."""

    def test_true_for_strong_edge(self, monkeypatch):
        import order_executor
        from order_executor import _clears_taker_fee

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        # net_ev = 0.85*0.50*0.93 - 0.15*0.50 = 0.32025; /0.50 = 0.6405 >> 0.07
        assert _clears_taker_fee(analysis) is True

    def test_false_for_thin_edge(self, monkeypatch):
        import order_executor
        from order_executor import _clears_taker_fee

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        # net_ev = 0.53*0.50*0.93 - 0.47*0.50 = 0.01145; /0.50 = 0.0229 < 0.07
        assert _clears_taker_fee(analysis) is False

    def test_no_side_computed_correctly(self, monkeypatch):
        import order_executor
        from order_executor import _clears_taker_fee

        monkeypatch.setattr(order_executor, "MIN_EDGE", 0.07)
        analysis = {
            "forecast_prob": 0.15,  # P(NO wins) = 0.85
            "entry_price": 0.50,
            "recommended_side": "no",
        }
        assert _clears_taker_fee(analysis) is True

    def test_missing_entry_price_returns_false(self):
        from order_executor import _clears_taker_fee

        assert (
            _clears_taker_fee({"forecast_prob": 0.8, "recommended_side": "yes"})
            is False
        )

    def test_missing_forecast_prob_returns_false(self):
        from order_executor import _clears_taker_fee

        assert (
            _clears_taker_fee({"entry_price": 0.5, "recommended_side": "yes"}) is False
        )

    def test_invalid_side_returns_false(self):
        from order_executor import _clears_taker_fee

        assert (
            _clears_taker_fee(
                {
                    "forecast_prob": 0.8,
                    "entry_price": 0.5,
                    "recommended_side": "maybe",
                }
            )
            is False
        )


class TestCancelAndVerifySafeToReplace:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _seed_row(self):
        import execution_log

        return execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=5,
            price=0.55,
            status="pending",
            live=True,
        )

    def test_true_when_confirmed_unfilled(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_1", row_id) is True
        mock_client.cancel_order.assert_called_once_with("ord_1")

    def test_false_when_partial_fill_detected(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "3.00",
        }

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_2", row_id) is False

    def test_false_when_cancel_call_itself_raises(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.cancel_order.side_effect = ConnectionError("down")

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_3", row_id) is False

    def test_false_when_post_cancel_verification_query_fails(self):
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.side_effect = ConnectionError("network blip")

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_4", row_id) is False

    def test_false_when_order_still_resting_despite_zero_fill_count(self):
        """A cancel that hasn't propagated yet (Kalshi still reports
        "resting", zero fills so far) must NOT be treated as safe to
        replace -- a taker-cross replacement placed while the original is
        still genuinely resting would silently no-op against Kalshi's
        self_trade_prevention_type="taker_at_cross" rather than fill.
        fill_count==0 alone isn't proof the order is actually gone."""
        from unittest.mock import MagicMock

        from order_executor import _cancel_and_verify_safe_to_replace

        row_id = self._seed_row()
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "resting",
            "fill_count_fp": "0.00",
        }

        assert _cancel_and_verify_safe_to_replace(mock_client, "ord_5", row_id) is False


class TestReplaceLiveOrder:
    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_gate_blocked_returns_false_and_places_nothing(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _replace_live_order

        mock_client = MagicMock()
        with patch(
            "trading_gates.pre_live_trade_check",
            side_effect=RuntimeError("TRADING_PAUSED"),
        ):
            result = _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "good_till_canceled",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        assert result is False
        mock_client.place_order.assert_not_called()

    def test_success_logs_replaces_order_id(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"order_id": "ord_new"}
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "good_till_canceled",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        assert result is True
        rows = execution_log.get_recent_orders(limit=10)
        new_row = next(r for r in rows if r["price"] == pytest.approx(0.52))
        assert new_row["replaces_order_id"] == 99
        assert new_row["status"] == "pending"
        assert new_row["order_type"] == "limit"

    def test_place_order_failure_logs_failed_status(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.side_effect = ConnectionError("down")
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.52,
                "good_till_canceled",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        assert result is False
        rows = execution_log.get_recent_orders(limit=10)
        new_row = next(r for r in rows if r["replaces_order_id"] == 99)
        assert new_row["status"] == "failed"

    def test_taker_cross_logged_as_market_order_type(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _replace_live_order

        mock_client = MagicMock()
        mock_client.place_order.return_value = {"order_id": "ord_taker"}
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            _replace_live_order(
                "KXHIGH-25MAY15-T75",
                "yes",
                5,
                0.60,
                "immediate_or_cancel",
                mock_client,
                "2026-05-15_12z",
                99,
                None,
            )

        rows = execution_log.get_recent_orders(limit=10)
        new_row = next(r for r in rows if r["replaces_order_id"] == 99)
        assert new_row["order_type"] == "market"


class TestFillInstrumentation:
    """_poll_pending_orders must capture filled_at/market_mid_at_fill the
    moment a fill is first detected, for fill-latency/adverse-selection
    analysis (backlog: 'log fill latency and post-fill price drift per
    order')."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_fill_captures_latency_and_mid_price(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_fill"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "status": "executed",
            "fill_count_fp": "2.00",
        }

        with patch(
            "order_executor._get_current_book",
            return_value={"yes_bid": 0.58, "yes_ask": 0.62},
        ):
            main._poll_pending_orders(mock_client, config={})

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "filled"
        assert row["filled_at"] is not None
        assert row["market_mid_at_fill"] == pytest.approx(0.60)

    def test_non_fill_status_leaves_instrumentation_null(self):
        from unittest.mock import MagicMock

        import execution_log
        import main

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_resting"},
        )

        mock_client = MagicMock()
        mock_client.get_order.return_value = {"status": "resting"}

        main._poll_pending_orders(mock_client, config={})

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["status"] == "pending"
        assert row["filled_at"] is None
        assert row["market_mid_at_fill"] is None

    def test_log_order_result_coalesce_never_nulls_out_prior_fill_data(self):
        """A later log_order_result() call on an already-instrumented row
        (e.g. from an unrelated code path) must not wipe filled_at/
        market_mid_at_fill back to NULL."""
        import execution_log

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(
            row_id,
            status="filled",
            fill_quantity=2,
            filled_at="2026-05-15T12:00:00+00:00",
            market_mid_at_fill=0.60,
        )

        # Unrelated later update -- omits the instrumentation fields.
        execution_log.log_order_result(row_id, status="filled", fill_quantity=2)

        row = next(
            o for o in execution_log.get_recent_orders(limit=10) if o["id"] == row_id
        )
        assert row["filled_at"] == "2026-05-15T12:00:00+00:00"
        assert row["market_mid_at_fill"] == pytest.approx(0.60)


class TestRepriceOrCancelPendingOrders:
    """The core reprice-or-cancel policy: cancel on edge decay, cancel+
    replace as taker when edge clears the real taker fee, cancel+replace as
    an improved maker price when the market has moved, else leave resting."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _seed_pending(self, ticker="KXHIGH-25MAY15-T75", price=0.50, age_minutes=10):
        from datetime import UTC, datetime, timedelta

        import execution_log

        row_id = execution_log.log_order(
            ticker=ticker,
            side="yes",
            quantity=5,
            price=price,
            status="pending",
            live=True,
            response={"order_id": "ord_orig"},
        )
        placed_at = (datetime.now(UTC) - timedelta(minutes=age_minutes)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", (placed_at, row_id)
            )
        return row_id

    def test_ticker_not_in_scan_leaves_order_untouched(self):
        from unittest.mock import MagicMock

        import execution_log
        from order_executor import _reprice_or_cancel_pending_orders

        self._seed_pending()
        mock_client = MagicMock()

        _reprice_or_cancel_pending_orders(
            mock_client, config={}, liquid_opps=[({"ticker": "OTHER"}, {})]
        )

        mock_client.cancel_order.assert_not_called()
        rows = execution_log.get_recent_orders(limit=10)
        assert rows[0]["status"] == "pending"

    def test_empty_liquid_opps_is_a_noop(self):
        from unittest.mock import MagicMock

        from order_executor import _reprice_or_cancel_pending_orders

        self._seed_pending()
        mock_client = MagicMock()

        _reprice_or_cancel_pending_orders(mock_client, config={}, liquid_opps=[])

        mock_client.cancel_order.assert_not_called()

    def test_validation_failure_cancels_without_replacing(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }

        with patch(
            "order_executor._validate_trade_opportunity",
            return_value=(False, "edge decayed"),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_called_once_with("ord_orig")
        mock_client.place_order.assert_not_called()
        rows = execution_log.get_recent_orders(limit=10)
        assert rows[0]["status"] == "canceled"

    def test_strong_edge_and_rested_crosses_as_taker(self):
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        # net_ev_taker = 0.85*0.50*0.93 - 0.15*0.50 = 0.32025; /0.50 = 0.64 >> MIN_EDGE
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }
        mock_client.place_order.return_value = {"order_id": "ord_taker"}

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.48, "yes_ask": 0.52},
            ),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_called_once_with("ord_orig")
        mock_client.place_order.assert_called_once()
        _, kwargs = mock_client.place_order.call_args
        assert kwargs["time_in_force"] == "immediate_or_cancel"
        assert kwargs["price"] == pytest.approx(0.52)  # crosses at current yes_ask

    def test_order_younger_than_blanket_gate_is_untouched(self):
        """Younger than _MIN_REST_MINUTES_BEFORE_REPRICE (2 min) -> left
        resting regardless of edge strength or price movement -- blocked by
        the blanket gate before either branch is even considered (not by
        the taker-specific 4-min gate; see
        test_rested_past_blanket_gate_but_not_taker_gate_reprices_not_crosses
        for that narrower [2,4) window)."""
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=1)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }
        mock_client.place_order.return_value = {"order_id": "ord_new"}

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            # Fresh midpoint (0.55) differs from the resting price (0.50) --
            # would trigger a reprice if the blanket age gate weren't
            # blocking it first.
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_not_called()
        mock_client.place_order.assert_not_called()

    def test_rested_past_blanket_gate_but_not_taker_gate_reprices_not_crosses(self):
        """The [_MIN_REST_MINUTES_BEFORE_REPRICE, _MIN_REST_MINUTES_BEFORE_TAKER_CROSS)
        window: old enough to reprice-improve (cleared the 2-min blanket
        gate) but not old enough to taker-cross (hasn't cleared the
        stricter 4-min gate) -- even with a strong edge that would
        otherwise clear the taker fee, this must reprice as a new maker
        order, not cross as taker."""
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=3)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        # Strong edge -- would clear the taker fee if the order were old
        # enough (see test_strong_edge_and_rested_crosses_as_taker).
        analysis = {
            "forecast_prob": 0.85,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }
        mock_client.place_order.return_value = {"order_id": "ord_repriced"}

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_called_once_with("ord_orig")
        mock_client.place_order.assert_called_once()
        _, kwargs = mock_client.place_order.call_args
        assert (
            kwargs["time_in_force"] == "good_till_canceled"
        )  # reprice, not taker-cross
        assert kwargs["price"] == pytest.approx(0.55)  # fresh midpoint

    def test_price_moved_reprices_as_new_maker_order(self):
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        # Thin edge -- must NOT clear the taker fee, so this exercises the
        # reprice-improve branch, not the taker-cross branch.
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "0.00",
        }
        mock_client.place_order.return_value = {"order_id": "ord_repriced"}

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_called_once_with("ord_orig")
        mock_client.place_order.assert_called_once()
        _, kwargs = mock_client.place_order.call_args
        assert kwargs["time_in_force"] == "good_till_canceled"
        assert kwargs["price"] == pytest.approx(0.55)  # fresh midpoint

    def test_price_unchanged_leaves_order_resting(self):
        from unittest.mock import MagicMock, patch

        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.48, "yes_ask": 0.52}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                # Midpoint (0.48+0.52)/2 = 0.50, identical to the resting price.
                return_value={"yes_bid": 0.48, "yes_ask": 0.52},
            ),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_not_called()
        mock_client.place_order.assert_not_called()

    def test_fill_race_during_cancel_skips_replacement(self):
        """If the post-cancel verification shows the order actually filled
        (raced the cancel), never place a replacement -- would risk a
        duplicate position."""
        from unittest.mock import MagicMock, patch

        import execution_log
        import order_executor
        from order_executor import _reprice_or_cancel_pending_orders

        ticker = "KXHIGH-25MAY15-T75"
        self._seed_pending(ticker=ticker, price=0.50, age_minutes=10)
        market = {"ticker": ticker, "yes_bid": 0.53, "yes_ask": 0.57}
        analysis = {
            "forecast_prob": 0.53,
            "entry_price": 0.50,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.cancel_order.return_value = {}
        # The order actually filled (5 contracts) right before our cancel landed.
        mock_client.get_order.return_value = {
            "status": "canceled",
            "fill_count_fp": "5.00",
        }

        with (
            patch.object(order_executor, "MIN_EDGE", 0.07),
            patch(
                "order_executor._validate_trade_opportunity",
                return_value=(True, "ok"),
            ),
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.53, "yes_ask": 0.57},
            ),
        ):
            _reprice_or_cancel_pending_orders(
                mock_client, config={}, liquid_opps=[(market, analysis)]
            )

        mock_client.cancel_order.assert_called_once()
        mock_client.place_order.assert_not_called()
        rows = execution_log.get_recent_orders(limit=10)
        assert rows[0]["status"] == "filled"
        assert rows[0]["fill_quantity"] == 5


class _LiveDBTestBase:
    """Shared execution_log DB isolation for the live-position-protection
    test classes below, matching the pattern used by every other class in
    this file."""

    def setup_method(self):
        import tempfile
        from pathlib import Path

        import execution_log

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        import gc
        from pathlib import Path

        import execution_log

        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)


class TestGetLiveOpenPositions(_LiveDBTestBase):
    def test_builds_check_function_compatible_dicts(self):
        import execution_log
        from order_executor import _get_live_open_positions

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
            close_time="2026-05-16T12:00:00+00:00",
            entry_prob=0.62,
        )
        execution_log.log_order_result(row_id, status="filled", fill_quantity=10)

        positions = _get_live_open_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos["ticker"] == "KXHIGH-25MAY15-T75"
        assert pos["side"] == "yes"
        assert pos["entry_price"] == pytest.approx(0.40)
        assert pos["quantity"] == 10
        assert pos["cost"] == pytest.approx(4.0)
        assert pos["entry_prob"] == pytest.approx(0.62)
        assert pos["settled"] is False

    def test_excludes_already_early_exited_positions(self):
        import execution_log
        from order_executor import _get_live_open_positions

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.record_live_early_exit(row_id, 0.20, "stop_loss", -2.14)
        assert _get_live_open_positions() == []

    def test_prefers_filled_at_over_placed_at_for_entered_at(self):
        import execution_log
        from order_executor import _get_live_open_positions

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        execution_log.log_order_result(
            row_id,
            status="filled",
            fill_quantity=10,
            filled_at="2026-05-15T18:00:00+00:00",
        )
        positions = _get_live_open_positions()
        assert positions[0]["entered_at"] == "2026-05-15T18:00:00+00:00"


class TestUpdateLivePeakProfits(_LiveDBTestBase):
    def test_records_new_peak_when_higher(self):
        import execution_log
        from order_executor import _update_live_peak_profits

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = {
            "id": row_id,
            "ticker": "KXHIGH-25MAY15-T75",
            "side": "yes",
            "entry_price": 0.40,
            "quantity": 10,
            "cost": 4.0,
            "peak_profit_pct": None,
        }
        current_prices = {"KXHIGH-25MAY15-T75": {"bid": 0.55, "ask": 0.60}}
        _update_live_peak_profits([position], current_prices)

        # unrealized_profit_pct = (0.55 - 0.40) * 10 / 4.0 = 0.375
        assert position["peak_profit_pct"] == pytest.approx(0.375)
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["peak_profit_pct"] == pytest.approx(0.375)

    def test_does_not_overwrite_a_higher_stored_peak(self):
        import execution_log
        from order_executor import _update_live_peak_profits

        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = {
            "id": row_id,
            "ticker": "KXHIGH-25MAY15-T75",
            "side": "yes",
            "entry_price": 0.40,
            "quantity": 10,
            "cost": 4.0,
            "peak_profit_pct": 0.50,  # already higher than the current tick
        }
        current_prices = {"KXHIGH-25MAY15-T75": {"bid": 0.45, "ask": 0.50}}
        _update_live_peak_profits([position], current_prices)

        assert position["peak_profit_pct"] == 0.50
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT peak_profit_pct FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        # Never written -- stayed NULL in the DB, not overwritten with a lower value.
        assert row["peak_profit_pct"] is None


class TestExitLivePosition(_LiveDBTestBase):
    def _position(self, **overrides):
        base = {
            "id": 1,
            "ticker": "KXHIGH-25MAY15-T75",
            "side": "yes",
            "entry_price": 0.40,
            "quantity": 10,
            "cost": 4.0,
            "close_time": "2026-05-16T12:00:00+00:00",
        }
        base.update(overrides)
        return base

    def test_gate_blocked_returns_false_and_places_nothing(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _exit_live_position

        mock_client = MagicMock()
        with patch(
            "trading_gates.pre_live_trade_check",
            side_effect=RuntimeError("TRADING_PAUSED"),
        ):
            result = _exit_live_position(
                mock_client, self._position(), 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        mock_client.place_order.assert_not_called()

    def test_full_fill_records_fee_adjusted_pnl(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is True
        mock_client.place_order.assert_called_once()
        _, kwargs = mock_client.place_order.call_args
        assert kwargs["action"] == "sell"
        assert kwargs["time_in_force"] == "immediate_or_cancel"
        assert kwargs["price"] == pytest.approx(0.20)

        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at, exit_price, exit_reason, pnl, outcome_yes "
                "FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        # Loss case -> no fee discount (matches the natural-settlement
        # convention: fee only ever discounts a genuine gain).
        # gross_pnl = 10 * (0.20 - 0.40) = -2.00
        assert row["pnl"] == pytest.approx(-2.00)
        assert row["exit_price"] == pytest.approx(0.20)
        assert row["exit_reason"] == "stop_loss"
        assert row["outcome_yes"] is None
        assert row["settled_at"] is not None

    def test_gain_case_applies_fee_discount(self):
        """A genuine gain (exit_price > entry_price, e.g. a model-exit that
        fires on a favorable move) DOES get the taker-fee discount -- only a
        loss skips it, matching the natural-settlement win/loss asymmetry."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _exit_live_position(
                mock_client, position, 0.60, "model_exit", "2026-05-15_12z"
            )

        assert result is True
        # gross_pnl = 10 * (0.60 - 0.40) = 2.00; gain -> fee applies:
        # 2.00 * (1 - 0.07) = 1.86
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT pnl FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["pnl"] == pytest.approx(1.86)

    def test_ioc_no_fill_leaves_position_open(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "0.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        # Original position row must still read as open (settled_at untouched).
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["settled_at"] is None

    def test_partial_fill_logs_error_and_does_not_close_position(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "4.00",  # only 4 of 10 requested
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        # Deliberately not reconciled in this pass (see the function's
        # docstring) -- but must not silently mark the position fully closed
        # either, which would corrupt the ledger by claiming 10 contracts
        # exited when only 4 actually did.
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT settled_at FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["settled_at"] is None

    def test_place_order_exception_logs_failed_status(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.side_effect = ConnectionError("down")
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=10,
            price=0.40,
            status="filled",
            live=True,
        )
        position = self._position(id=row_id)
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _exit_live_position(
                mock_client, position, 0.20, "stop_loss", "2026-05-15_12z"
            )

        assert result is False
        rows = execution_log.get_recent_orders(limit=10)
        failed_row = next(r for r in rows if r["status"] == "failed")
        assert failed_row is not None

    def test_no_side_exit_pnl_uses_no_side_prices_directly(self):
        """entry_price/exit_price are already side-normalized (see
        _midpoint_price/_liquidation_price) -- the pnl formula must not
        re-derive a yes-price conversion for the "no" side."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _exit_live_position

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "5.00",
        }
        row_id = execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="no",
            quantity=5,
            price=0.30,
            status="filled",
            live=True,
        )
        position = self._position(
            id=row_id, side="no", entry_price=0.30, quantity=5, cost=1.5
        )
        with patch("trading_gates.pre_live_trade_check", return_value=None):
            result = _exit_live_position(
                mock_client, position, 0.15, "stop_loss", "2026-05-15_12z"
            )

        assert result is True
        # Loss case -> no fee discount. gross_pnl = 5 * (0.15 - 0.30) = -0.75
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT pnl FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["pnl"] == pytest.approx(-0.75)


class TestCheckLivePositionExits(_LiveDBTestBase):
    def _open_position_row(self, ticker="KXHIGH-25MAY15-T75", **overrides):
        from datetime import UTC, datetime, timedelta

        import execution_log

        defaults = dict(
            ticker=ticker,
            side="yes",
            quantity=10,
            price=0.50,
            status="filled",
            live=True,
            # Well beyond the 24h pre-settlement gate check_stop_losses/
            # check_breakeven_stops both apply.
            close_time=(datetime.now(UTC) + timedelta(days=10)).isoformat(),
        )
        defaults.update(overrides)
        row_id = execution_log.log_order(**defaults)
        execution_log.log_order_result(
            row_id, status="filled", fill_quantity=defaults["quantity"]
        )
        return row_id

    def test_no_open_positions_is_a_no_op(self):
        from unittest.mock import MagicMock

        from order_executor import _check_live_position_exits

        mock_client = MagicMock()
        _check_live_position_exits(mock_client)  # must not raise
        mock_client.place_order.assert_not_called()

    def test_stop_loss_breach_triggers_immediate_exit(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id = self._open_position_row(price=0.50, quantity=10)

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        # Loss > cost / STOP_LOSS_MULT (default 2.0) -> unrealized loss > 50% of cost.
        # cost = 5.0, bid=0.10 -> unrealized_pnl = (0.10-0.50)*10 = -4.0 < -2.5 -> fires.
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.10, "yes_ask": 0.15},
            ),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            _check_live_position_exits(mock_client)

        mock_client.place_order.assert_called_once()
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_reason, settled_at FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["exit_reason"] == "stop_loss"
        assert row["settled_at"] is not None

    def test_stop_loss_fires_on_rest_fallback_integer_cents_book(self):
        """Regression: _get_current_book's REST fallback returns the raw
        client.get_market() dict unchanged (integer cents, e.g. yes_bid=10,
        not the dollar float 0.10 the WS-cache path returns) -- this is the
        realistic shape for every cron run, since a fresh process starts
        with an empty WS cache. Reading it without normalizing through
        _coalesce_cents_or_dollars would treat 10 as a $10 price, making the
        position look wildly profitable and never trigger the stop."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id = self._open_position_row(price=0.50, quantity=10)

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        # Raw get_market()-shaped dict, integer cents -- the real REST-fallback
        # shape, not the pre-normalized dollar floats the other tests mock.
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 10, "yes_ask": 15},
            ),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            _check_live_position_exits(mock_client)

        mock_client.place_order.assert_called_once()
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_reason, settled_at FROM orders WHERE id = ?",
                (row_id,),
            ).fetchone()
        assert row["exit_reason"] == "stop_loss"
        assert row["settled_at"] is not None

    def test_healthy_position_is_left_alone(self):
        from unittest.mock import MagicMock, patch

        from order_executor import _check_live_position_exits

        self._open_position_row(price=0.50, quantity=10)

        mock_client = MagicMock()
        with patch(
            "order_executor._get_current_book",
            return_value={"yes_bid": 0.52, "yes_ask": 0.57},
        ):
            _check_live_position_exits(mock_client)

        mock_client.place_order.assert_not_called()

    def test_stop_loss_and_breakeven_are_mutually_exclusive_same_cycle(self):
        """A ticker that stop-loss-exits must not also be evaluated for a
        breakeven exit in the same call — it's already closed (or a real
        exit attempt already happened)."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id = self._open_position_row(price=0.50, quantity=10)
        # Simulate a pre-existing peak high enough to arm breakeven too.
        execution_log.update_live_peak_profit(row_id, 0.50)

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.10, "yes_ask": 0.15},
            ),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            _check_live_position_exits(mock_client)

        # Only the stop-loss exit should have fired, not a second breakeven exit.
        assert mock_client.place_order.call_count == 1

    def test_two_positions_on_same_ticker_both_get_exited(self):
        """Regression: two separate open live positions sharing a ticker
        (two distinct fills before either settles) must both be protected --
        a naive ticker-keyed dict would collapse them and silently leave one
        with zero protection."""
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_position_exits

        row_id_a = self._open_position_row(price=0.50, quantity=10)
        row_id_b = self._open_position_row(price=0.55, quantity=5)
        assert row_id_a != row_id_b

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        # bid=0.10 breaches stop-loss for both positions independently
        # (well past 50% of either position's cost).
        with (
            patch(
                "order_executor._get_current_book",
                return_value={"yes_bid": 0.10, "yes_ask": 0.15},
            ),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            _check_live_position_exits(mock_client)

        assert mock_client.place_order.call_count == 2
        with execution_log._conn() as con:
            rows = con.execute(
                "SELECT id, exit_reason, settled_at FROM orders WHERE id IN (?, ?)",
                (row_id_a, row_id_b),
            ).fetchall()
        for row in rows:
            assert row["exit_reason"] == "stop_loss"
            assert row["settled_at"] is not None


class TestCheckLiveModelExits(_LiveDBTestBase):
    def _open_position_row(self, ticker="KXHIGH-25MAY15-T75", **overrides):
        from datetime import UTC, datetime, timedelta

        import execution_log

        defaults = dict(
            ticker=ticker,
            side="yes",
            quantity=10,
            price=0.50,
            status="filled",
            live=True,
            # Well beyond the 24h pre-settlement gate.
            close_time=(datetime.now(UTC) + timedelta(days=10)).isoformat(),
            entry_prob=0.65,
        )
        defaults.update(overrides)
        row_id = execution_log.log_order(**defaults)
        # Backdate the fill past the 12h minimum-hold gate -- log_order_result
        # without an explicit filled_at leaves entered_at falling back to
        # placed_at, which log_order stamps at "now" (this test run), always
        # failing the 12h gate otherwise.
        execution_log.log_order_result(
            row_id,
            status="filled",
            fill_quantity=defaults["quantity"],
            filled_at=(datetime.now(UTC) - timedelta(hours=48)).isoformat(),
        )
        return row_id

    def test_no_client_returns_zero(self):
        from order_executor import _check_live_model_exits

        assert _check_live_model_exits(None) == 0

    def test_missing_entry_prob_is_skipped(self):
        from unittest.mock import MagicMock

        from order_executor import _check_live_model_exits

        self._open_position_row(entry_prob=None)
        mock_client = MagicMock()
        mock_client.get_markets.return_value = []
        assert _check_live_model_exits(mock_client) == 0
        mock_client.place_order.assert_not_called()

    def test_model_flip_beyond_threshold_triggers_exit(self):
        from unittest.mock import MagicMock, patch

        import execution_log
        from order_executor import _check_live_model_exits

        row_id = self._open_position_row(entry_prob=0.65)

        market = {
            "ticker": "KXHIGH-25MAY15-T75",
            "close_time": "2026-06-01T12:00:00+00:00",
            "yes_bid": "0.30",
            "yes_ask": "0.35",
        }
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_exit",
            "fill_count_fp": "10.00",
        }
        with (
            patch("order_executor.get_weather_markets", return_value=[market]),
            patch("order_executor.enrich_with_forecast", return_value={"_raw": market}),
            # entry_prob=0.65, current=0.35 -> shift = 0.65-0.35 = 0.30 > 0.25
            patch(
                "order_executor.analyze_trade",
                return_value={"forecast_prob": 0.35},
            ),
            patch("order_executor._get_current_book", return_value=None),
            patch("trading_gates.pre_live_trade_check", return_value=None),
        ):
            closed = _check_live_model_exits(mock_client)

        assert closed == 1
        with execution_log._conn() as con:
            row = con.execute(
                "SELECT exit_reason FROM orders WHERE id = ?", (row_id,)
            ).fetchone()
        assert row["exit_reason"] == "model_exit"

    def test_within_settlement_gate_skips_exit(self):
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock, patch

        from order_executor import _check_live_model_exits

        # close_time only 1 hour away -- inside the 24h pre-settlement gate.
        close_soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        self._open_position_row(
            entry_prob=0.65,
            close_time=close_soon,
        )
        market = {"ticker": "KXHIGH-25MAY15-T75"}
        mock_client = MagicMock()
        with (
            patch("order_executor.get_weather_markets", return_value=[market]),
            patch("order_executor.enrich_with_forecast", return_value={"_raw": market}),
            patch(
                "order_executor.analyze_trade",
                return_value={"forecast_prob": 0.35},
            ),
        ):
            closed = _check_live_model_exits(mock_client)

        assert closed == 0
        mock_client.place_order.assert_not_called()
