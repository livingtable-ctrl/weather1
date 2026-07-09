"""P0-6: execution log entry must be written BEFORE the live order is placed."""

from unittest.mock import MagicMock, patch

import pytest


class TestPreLogPattern:
    """_place_live_order must pre-log with status='pending' before calling place_order."""

    def _run_place(self, tmp_path, monkeypatch, place_order_side_effect=None):
        """Helper: run _place_live_order with the gate open and capture log calls."""
        import execution_log
        import main

        monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
        monkeypatch.setattr(execution_log, "_initialized", False)

        mock_client = MagicMock()
        if place_order_side_effect:
            mock_client.place_order.side_effect = place_order_side_effect
        else:
            mock_client.place_order.return_value = {"order_id": "ord_test"}

        config = {
            "daily_loss_limit": 500,
            "max_open_positions": 10,
            "max_trade_dollars": 100,
        }
        analysis = {
            "kelly_quantity": 2,
            "market": {"yes_bid": 50, "yes_ask": 60},
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch("execution_log.get_today_live_loss", return_value=0.0),
            patch.object(main, "_count_open_live_orders", return_value=0),
        ):
            placed, cost = main._place_live_order(
                ticker="KXTEST-25JUN01-T70",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        return placed, cost, mock_client

    def test_pending_row_exists_before_api_call(self, tmp_path, monkeypatch):
        """A 'pending' log row must exist in the DB before place_order is called."""
        import execution_log
        import main

        monkeypatch.setattr(execution_log, "DB_PATH", tmp_path / "exec.db")
        monkeypatch.setattr(execution_log, "_initialized", False)

        rows_at_call_time = []

        def fake_place_order(**kwargs):
            # Capture DB state at the moment the API is called
            rows_at_call_time.extend(execution_log.get_recent_orders(limit=10))
            return {"order_id": "ord_test"}

        mock_client = MagicMock()
        mock_client.place_order.side_effect = fake_place_order

        config = {
            "daily_loss_limit": 500,
            "max_open_positions": 10,
            "max_trade_dollars": 100,
        }
        analysis = {
            "kelly_quantity": 2,
            "market": {"yes_bid": 50, "yes_ask": 60},
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch.object(main, "_count_open_live_orders", return_value=0),
        ):
            main._place_live_order(
                ticker="KXTEST-25JUN01-T70",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert len(rows_at_call_time) == 1, "pending row must exist before API call"
        assert rows_at_call_time[0]["status"] == "pending"

    def test_status_updated_to_pending_on_success(self, tmp_path, monkeypatch):
        """After a successful place_order, status must be updated to 'pending' —
        the status every downstream lifecycle consumer actually filters on
        (F1: 'placed' was a dead-end invisible to fill polling/GTC cancel/etc)."""
        import execution_log

        self._run_place(tmp_path, monkeypatch)

        orders = execution_log.get_recent_orders(limit=10)
        assert len(orders) == 1
        assert orders[0]["status"] == "pending"

    def test_placed_order_counts_toward_open_positions(self, tmp_path, monkeypatch):
        """F1 regression: a successfully-placed live order must actually be
        counted by _count_open_live_orders (the real max_open_positions gate),
        not just checked in isolation with that function mocked out."""
        from order_executor import _count_open_live_orders

        self._run_place(tmp_path, monkeypatch)

        assert _count_open_live_orders() == 1, (
            "a placed live order must count toward the open-position limit"
        )

    def test_status_updated_to_failed_on_exception(self, tmp_path, monkeypatch):
        """After place_order raises, status must be updated to 'failed'."""
        import execution_log

        placed, cost, _ = self._run_place(
            tmp_path, monkeypatch, place_order_side_effect=ConnectionError("timeout")
        )

        assert not placed
        assert cost == 0.0
        orders = execution_log.get_recent_orders(limit=10)
        assert len(orders) == 1
        assert orders[0]["status"] == "failed"

    def test_exactly_one_log_row_on_success(self, tmp_path, monkeypatch):
        """Exactly one DB row must be created (pre-log + in-place update, not two inserts)."""
        import execution_log

        self._run_place(tmp_path, monkeypatch)

        orders = execution_log.get_recent_orders(limit=10)
        assert len(orders) == 1

    def test_exactly_one_log_row_on_failure(self, tmp_path, monkeypatch):
        """Even on API failure, exactly one DB row must exist."""
        import execution_log

        self._run_place(
            tmp_path, monkeypatch, place_order_side_effect=RuntimeError("api down")
        )

        orders = execution_log.get_recent_orders(limit=10)
        assert len(orders) == 1


class TestResolveMicroLiveConfig:
    """F2: micro-live's daily-loss limit was silently disabled because it only
    ever runs from _auto_place_trades' paper branch, where live_config is
    always None — (None or {}).get("daily_loss_limit", 0.0) resolved to 0.0,
    and the check only fires when the configured limit is > 0."""

    def test_none_live_config_loads_real_config(self, tmp_path, monkeypatch):
        import main
        from order_executor import _resolve_micro_live_config

        live_config_path = tmp_path / "live_config.json"
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", live_config_path)

        resolved = _resolve_micro_live_config(None)

        assert resolved.get("daily_loss_limit", 0.0) > 0, (
            "must resolve to the real configured limit, not silently default to 0.0"
        )
        assert resolved == main._LIVE_CONFIG_DEFAULT

    def test_explicit_live_config_is_respected(self):
        from order_executor import _resolve_micro_live_config

        explicit = {"daily_loss_limit": 42.0}
        assert _resolve_micro_live_config(explicit) is explicit


class TestResolveLiveBalance:
    """F4: live_config never has a "balance" key, so the CR-4 override for
    live Kelly sizing was always inert — silently falling back to the paper
    balance for every live trade. Fetch the real balance from the client
    directly instead."""

    def test_fetches_real_balance_from_client(self):
        from order_executor import _resolve_live_balance

        client = MagicMock()
        client.get_balance.return_value = {"balance": 123456}  # cents

        assert _resolve_live_balance(client) == pytest.approx(1234.56)

    def test_client_error_falls_back_to_zero(self):
        """0.0 signals 'use the paper balance' to the caller — must not raise
        or block placement just because the balance fetch failed."""
        from order_executor import _resolve_live_balance

        client = MagicMock()
        client.get_balance.side_effect = ConnectionError("timeout")

        assert _resolve_live_balance(client) == 0.0

    def test_missing_balance_key_falls_back_to_zero(self):
        from order_executor import _resolve_live_balance

        client = MagicMock()
        client.get_balance.return_value = {}

        assert _resolve_live_balance(client) == 0.0
