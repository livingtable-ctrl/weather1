"""Tests for batch-49 item 2's read-only queue-position instrumentation in
order_executor.py: logging at maker-order placement (_place_live_order) and
once per poll pass for resting orders (_poll_pending_orders, via the bulk
endpoint -- rate-budget constraint: once per pass, not per order).

Explicitly NOT tested here (out of scope for this batch, per its own
constraint): anything reading this data back into a reprice/chase decision
-- that wiring doesn't exist yet (see backlog.txt).

Setup/teardown mirrors TestPlaceLiveOrder/TestPollPendingOrdersExtended in
test_live_execution.py (temp execution_log DB per test).
"""

from __future__ import annotations

import gc
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import execution_log
import order_executor


class _TempDbMixin:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        execution_log.DB_PATH = Path(self._tmp.name)
        execution_log._initialized = False

    def teardown_method(self):
        execution_log._initialized = False
        self._tmp.close()
        gc.collect()
        Path(self._tmp.name).unlink(missing_ok=True)


class TestPlacementQueuePositionLogging(_TempDbMixin):
    def _place(self, mock_client):
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
            patch("trading_gates.pre_live_trade_check", return_value=None),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch.object(order_executor, "_count_open_live_orders", return_value=0),
        ):
            return order_executor._place_live_order(
                ticker="KXHIGH-25MAY15-T75",
                side="yes",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

    def test_successful_placement_logs_queue_position(self):
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_test",
            "status": "resting",
        }
        mock_client.get_order_queue_position.return_value = 7.0

        placed, cost = self._place(mock_client)

        assert placed is True
        mock_client.get_order_queue_position.assert_called_once_with("ord_test")
        history = execution_log.get_queue_position_history("ord_test")
        assert len(history) == 1
        assert history[0]["queue_position"] == 7.0
        assert history[0]["source"] == "placement"
        assert history[0]["ticker"] == "KXHIGH-25MAY15-T75"

    def test_placement_logs_the_correct_local_order_row_id(self):
        """Opus review follow-up: order_row_id must be THIS placement's own
        execution_log row (log_id from the pre-log write), not None/wrong
        -- verified by cross-referencing against get_recent_orders()'s own
        row id for the same ticker."""
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_test",
            "status": "resting",
        }
        mock_client.get_order_queue_position.return_value = 7.0

        self._place(mock_client)

        orders = execution_log.get_recent_orders(limit=10)
        assert len(orders) == 1
        real_row_id = orders[0]["id"]
        history = execution_log.get_queue_position_history("ord_test")
        assert history[0]["order_row_id"] == real_row_id

    def test_queue_position_lookup_failure_does_not_break_placement(self):
        """Isolation requirement: instrumentation must never risk the
        trading-critical placement path it's observing (same reasoning as
        the bookkeeping write and market_mid_at_fill lookup elsewhere in
        this function)."""
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_test",
            "status": "resting",
        }
        mock_client.get_order_queue_position.side_effect = ConnectionError("boom")

        placed, cost = self._place(mock_client)

        assert placed is True, "a queue-position lookup failure must not fail placement"
        assert cost > 0.0
        assert execution_log.get_queue_position_history("ord_test") == []

    def test_none_queue_position_still_logs_a_row(self):
        """get_order_queue_position() returns None on a response-shape
        drift (fail-soft, never raises) -- that observation is still worth
        logging."""
        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_test",
            "status": "resting",
        }
        mock_client.get_order_queue_position.return_value = None

        placed, _cost = self._place(mock_client)

        assert placed is True
        history = execution_log.get_queue_position_history("ord_test")
        assert len(history) == 1
        assert history[0]["queue_position"] is None


class TestPollPassQueuePositionLogging(_TempDbMixin):
    def _log_pending(self, ticker: str, order_id: str) -> int:
        return execution_log.log_order(
            ticker=ticker,
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": order_id},
        )

    def test_bulk_endpoint_called_once_per_pass_not_per_order(self):
        """Rate-budget constraint: 'bulk queue-position once per poll pass,
        not per order' -- 2 distinct pending orders must still yield
        exactly ONE get_bulk_queue_positions call."""
        self._log_pending("KXHIGH-25MAY15-T75", "ord_1")
        self._log_pending("KXHIGH-25MAY15-T76", "ord_2")

        mock_client = MagicMock()
        mock_client.get_bulk_queue_positions.return_value = [
            {"order_id": "ord_1", "queue_position_fp": "3.00"},
            {"order_id": "ord_2", "queue_position_fp": "9.00"},
        ]
        mock_client.get_order.return_value = {
            "status": "resting",
            "fill_count_fp": "0.00",
        }

        order_executor._poll_pending_orders(mock_client)

        mock_client.get_bulk_queue_positions.assert_called_once()
        # Opus review follow-up: assert the actual market_tickers argument,
        # not just that the call happened -- both distinct pending tickers
        # must be passed through, deduped/sorted.
        assert mock_client.get_bulk_queue_positions.call_args.kwargs[
            "market_tickers"
        ] == ["KXHIGH-25MAY15-T75", "KXHIGH-25MAY15-T76"]
        assert (
            execution_log.get_queue_position_history("ord_1")[0]["queue_position"]
            == 3.0
        )
        assert (
            execution_log.get_queue_position_history("ord_2")[0]["queue_position"]
            == 9.0
        )
        assert execution_log.get_queue_position_history("ord_1")[0]["source"] == "poll"

    def test_canceled_this_pass_order_still_gets_its_last_observation_logged(self):
        """Opus review follow-up: the queue-position log happens BEFORE the
        pre-close/GTC-age cancel checks (which `continue` past the rest of
        the loop iteration), so an order canceled during this exact poll
        pass must still have its final observation recorded -- it was still
        resting at bulk-call time."""
        from datetime import UTC, datetime, timedelta

        row_id = self._log_pending("KXHIGH-25MAY15-T75", "ord_1")
        old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        with execution_log._conn() as con:
            con.execute(
                "UPDATE orders SET placed_at = ? WHERE id = ?", (old_time, row_id)
            )

        mock_client = MagicMock()
        mock_client.get_bulk_queue_positions.return_value = [
            {"order_id": "ord_1", "queue_position_fp": "4.00"}
        ]
        mock_client.cancel_order.return_value = {}

        order_executor._poll_pending_orders(mock_client, config={"gtc_cancel_hours": 1})

        mock_client.cancel_order.assert_called_once_with("ord_1")
        history = execution_log.get_queue_position_history("ord_1")
        assert len(history) == 1
        assert history[0]["queue_position"] == 4.0

    def test_no_pending_orders_skips_bulk_call_entirely(self):
        mock_client = MagicMock()

        order_executor._poll_pending_orders(mock_client)

        mock_client.get_bulk_queue_positions.assert_not_called()

    def test_bulk_call_failure_does_not_break_fill_status_polling(self):
        """Isolation requirement: a queue-position API hiccup must never
        block/skip the real fill-status polling loop."""
        self._log_pending("KXHIGH-25MAY15-T75", "ord_1")

        mock_client = MagicMock()
        mock_client.get_bulk_queue_positions.side_effect = ConnectionError("boom")
        mock_client.get_order.return_value = {
            "status": "executed",
            "fill_count_fp": "2.00",
        }

        order_executor._poll_pending_orders(mock_client)  # must not raise

        orders = execution_log.get_recent_orders(limit=10)
        assert orders[0]["status"] == "filled", (
            "fill-status polling must still complete despite the queue-"
            "position bulk call failing"
        )

    def test_order_missing_from_bulk_response_logs_nothing_for_it(self):
        """An order that's no longer resting (e.g. filled between polls)
        can legitimately be absent from the bulk response -- no log row,
        not an error."""
        self._log_pending("KXHIGH-25MAY15-T75", "ord_1")

        mock_client = MagicMock()
        mock_client.get_bulk_queue_positions.return_value = []
        mock_client.get_order.return_value = {
            "status": "resting",
            "fill_count_fp": "0.00",
        }

        order_executor._poll_pending_orders(mock_client)

        assert execution_log.get_queue_position_history("ord_1") == []

    def test_unparseable_bulk_entry_logs_none(self):
        self._log_pending("KXHIGH-25MAY15-T75", "ord_1")

        mock_client = MagicMock()
        mock_client.get_bulk_queue_positions.return_value = [
            {"order_id": "ord_1", "queue_position_fp": "garbage"}
        ]
        mock_client.get_order.return_value = {
            "status": "resting",
            "fill_count_fp": "0.00",
        }

        order_executor._poll_pending_orders(mock_client)

        history = execution_log.get_queue_position_history("ord_1")
        assert len(history) == 1
        assert history[0]["queue_position"] is None
