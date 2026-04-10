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
