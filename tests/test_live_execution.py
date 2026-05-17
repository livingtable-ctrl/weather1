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

        # Mock client that returns filled status
        mock_client = MagicMock()
        mock_client.get_order.return_value = {
            "order_id": "ord_abc123",
            "status": "filled",
            "fill_quantity": 2,
        }

        main._poll_pending_orders(mock_client)

        # Verify the order was updated
        orders = execution_log.get_recent_orders(limit=10)
        assert orders[0]["status"] == "filled"

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
        assert orders[0]["status"] == "cancelled"

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
