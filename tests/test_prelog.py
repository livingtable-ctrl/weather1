"""P0-6: execution log entry must be written BEFORE the live order is placed."""

from unittest.mock import MagicMock, patch


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

    def test_status_updated_to_placed_on_success(self, tmp_path, monkeypatch):
        """After a successful place_order, status must be updated to 'placed'."""
        import execution_log

        self._run_place(tmp_path, monkeypatch)

        orders = execution_log.get_recent_orders(limit=10)
        assert len(orders) == 1
        assert orders[0]["status"] == "placed"

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
