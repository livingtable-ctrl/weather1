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


class TestCacheStaleness:
    def test_fresh_entry_returns_price(self, monkeypatch):
        """An entry timestamped <15 min ago is returned normally."""
        from datetime import UTC, datetime

        import kalshi_ws

        monkeypatch.setattr(
            kalshi_ws,
            "_orderbook",
            {
                "KXTEMP-25": {
                    "mid_price": 0.65,
                    "ts": datetime.now(UTC).isoformat(),
                }
            },
        )
        assert kalshi_ws.get_cached_mid_price("KXTEMP-25") == 0.65

    def test_stale_entry_returns_none(self, monkeypatch):
        """An entry timestamped >WS_CACHE_TTL_SECS ago returns None."""
        from datetime import UTC, datetime, timedelta

        import kalshi_ws

        old_ts = (datetime.now(UTC) - timedelta(seconds=1000)).isoformat()
        monkeypatch.setattr(
            kalshi_ws,
            "_orderbook",
            {
                "KXTEMP-25": {
                    "mid_price": 0.65,
                    "ts": old_ts,
                }
            },
        )
        monkeypatch.setenv("WS_CACHE_TTL_SECS", "900")
        import importlib

        import utils

        importlib.reload(utils)
        assert kalshi_ws.get_cached_mid_price("KXTEMP-25") is None

    def test_missing_ts_returns_none(self, monkeypatch):
        """An entry with no ts field is treated as stale."""
        import kalshi_ws

        monkeypatch.setattr(
            kalshi_ws,
            "_orderbook",
            {"KXTEMP-25": {"mid_price": 0.65}},  # no "ts"
        )
        assert kalshi_ws.get_cached_mid_price("KXTEMP-25") is None


class TestWsHealth:
    def test_get_ws_health_initially_not_alive(self):
        """Fresh import: ws not alive, no messages recorded."""
        import importlib

        import kalshi_ws

        importlib.reload(kalshi_ws)
        h = kalshi_ws.get_ws_health()
        assert h["alive"] is False
        assert h["idle_secs"] is None

    def test_get_ws_health_stale_flag(self, monkeypatch):
        """stale=True when idle > WS_CACHE_TTL_SECS."""
        import time

        import kalshi_ws

        kalshi_ws._ws_last_message_ts = time.monotonic() - 1000
        kalshi_ws._ws_alive = True
        monkeypatch.setenv("WS_CACHE_TTL_SECS", "900")
        h = kalshi_ws.get_ws_health()
        assert h["stale"] is True
