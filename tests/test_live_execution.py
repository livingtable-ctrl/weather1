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
            response={"order": {"order_id": "ord_abc123"}},
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
            response={"order": {"order_id": "ord_xyz"}},
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
            response={"order": {"order_id": "ord_partial"}},
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
            response={"order": {"order_id": "ord_rest"}},
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
            response={"order": {"order_id": "ord_rest2"}},
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
            response={"order": {"order_id": "ord_abc123"}},
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
            response={"order": {"order_id": "ord_abc"}},
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
            response={"order": {"order_id": "ord_partial_gtc"}},
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
            response={"order": {"order_id": "ord_fresh"}},
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
        # pnl = 2 * (1 - 0.55) * (1 - 0.07) = 2 * 0.45 * 0.93 = 0.837
        assert order["pnl"] == pytest.approx(0.837, rel=1e-3)

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
        # pnl = 3 * (1 - 0.60) * (1 - 0.07) = 3 * 0.40 * 0.93 = 1.116
        assert order["pnl"] == pytest.approx(1.116, rel=1e-3)

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

        # pnl = 2*(1-0.55)*(1-0.07) = 0.837 (profit) -> add_live_loss(-pnl)
        # is a credit of -0.837, not a lingering positive "loss".
        assert execution_log.get_today_live_loss() == pytest.approx(-0.837, rel=1e-3)


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
