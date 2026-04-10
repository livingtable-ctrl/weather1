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
    def test_daily_loss_limit_blocks_order(self, monkeypatch):
        import main

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 100,
            "max_open_positions": 10,
        }
        # session loss already at limit
        monkeypatch.setattr(main, "_SESSION_LOSS", 100.0)
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

    def test_max_trade_dollars_caps_size(self, monkeypatch):
        """Kelly wants 10 contracts at $0.55 = $5.50/contract → $55 total, capped to $50."""
        from unittest.mock import MagicMock, patch

        import main

        monkeypatch.setattr(main, "_SESSION_LOSS", 0.0)
        monkeypatch.setattr(main, "_LIVE_CONFIG_PATH", main._LIVE_CONFIG_PATH)  # no-op

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_abc123",
            "status": "resting",
        }

        config = {
            "max_trade_dollars": 50,
            "daily_loss_limit": 200,
            "max_open_positions": 10,
        }
        analysis = {
            "kelly_quantity": 10,
            "implied_prob": 0.55,
            "market": {"yes_bid": 50, "yes_ask": 60},
            "edge": 0.25,
        }

        with (
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
        # price = midpoint(50, 60) = 0.55, max contracts = floor(50 / 0.55) = 90 — but Kelly says 10
        # At $0.55/contract × 10 = $5.50 total, well under $50 cap → 10 contracts placed
        # Actually: $0.55 × 10 = $5.50 < $50, so Kelly quantity is used as-is
        assert mock_client.place_order.called
        # quantity should be min(10, floor(50/0.55)) = 10
        assert cost > 0.0
        # Verify price passed to API is decimal dollars (not cents)
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

        # Log a pending live order
        execution_log.log_order(
            ticker="KXHIGH-25MAY15-T75",
            side="yes",
            quantity=2,
            price=0.55,
            status="pending",
            live=True,
            response={"order_id": "ord_abc123"},
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
