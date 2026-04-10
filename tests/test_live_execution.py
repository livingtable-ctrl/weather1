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
