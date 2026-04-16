"""Tests for Kalshi WebSocket client."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestParseOrderbookMessage:
    def test_parse_snapshot_message(self):
        """parse_message returns structured snapshot from orderbook_snapshot type."""
        from kalshi_ws import parse_message

        msg = {
            "type": "orderbook_snapshot",
            "msg": {
                "market_ticker": "KXHIGHNY-26APR17-T72",
                "yes": [["0.6500", 100], ["0.6400", 50]],
                "no": [["0.3500", 80]],
            },
        }
        result = parse_message(msg)
        assert result is not None
        assert result["type"] == "orderbook_snapshot"
        assert result["ticker"] == "KXHIGHNY-26APR17-T72"
        assert result["best_yes_bid"] == pytest.approx(0.65, abs=0.001)

    def test_parse_ticker_message(self):
        """parse_message extracts mid-price from ticker message."""
        from kalshi_ws import parse_message

        msg = {
            "type": "ticker",
            "msg": {
                "market_ticker": "KXHIGHNY-26APR17-T72",
                "yes_bid": "0.6300",
                "yes_ask": "0.6700",
                "last_price": "0.6400",
            },
        }
        result = parse_message(msg)
        assert result is not None
        assert result["type"] == "ticker"
        assert result["mid_price"] == pytest.approx(0.65, abs=0.001)

    def test_parse_unknown_type_returns_none(self):
        """Unknown message types return None (ignored)."""
        from kalshi_ws import parse_message

        result = parse_message({"type": "unknown_event", "msg": {}})
        assert result is None

    def test_parse_empty_msg_returns_none(self):
        from kalshi_ws import parse_message

        assert parse_message({}) is None
        assert parse_message({"type": "ticker", "msg": {}}) is None


class TestOrderbookCache:
    def test_update_and_read_cache(self, tmp_path, monkeypatch):
        """update_orderbook_cache writes and read_orderbook_cache reads back."""
        import kalshi_ws

        cache_path = tmp_path / "orderbook_cache.json"
        monkeypatch.setattr(kalshi_ws, "_CACHE_PATH", cache_path)

        from kalshi_ws import read_orderbook_cache, update_orderbook_cache

        update_orderbook_cache("TICKER-A", {"mid_price": 0.65, "type": "ticker"})
        cache = read_orderbook_cache()

        assert "TICKER-A" in cache
        assert cache["TICKER-A"]["mid_price"] == pytest.approx(0.65)

    def test_cache_missing_returns_empty(self, tmp_path, monkeypatch):
        """read_orderbook_cache returns {} if file does not exist."""
        import kalshi_ws

        monkeypatch.setattr(kalshi_ws, "_CACHE_PATH", tmp_path / "nonexistent.json")

        from kalshi_ws import read_orderbook_cache

        assert read_orderbook_cache() == {}


class TestBuildSubscribeMessage:
    def test_subscribe_message_structure(self):
        """build_subscribe_message returns a valid Kalshi WS subscribe payload."""
        from kalshi_ws import build_subscribe_message

        msg = build_subscribe_message(
            cmd_id=1,
            channels=["orderbook_delta", "ticker"],
            market_tickers=["KXHIGHNY-26APR17-T72"],
        )
        assert msg["id"] == 1
        assert msg["cmd"] == "subscribe"
        assert "params" in msg
        assert "channels" in msg["params"]
        assert "orderbook_delta" in msg["params"]["channels"]
