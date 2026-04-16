# Phase F: Kalshi WebSocket Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Kalshi WebSocket client that subscribes to real-time order book data, enabling microstructure signals, settlement lag automation, and faster price feeds.

**Architecture:** New `kalshi_ws.py` module with a `KalshiWebSocket` class. Runs as a background thread alongside the main cron loop. Writes order book snapshots to a shared `data/orderbook_cache.json` for consumption by the main trading loop. The WebSocket thread is optional — the bot continues to work without it.

**Tech Stack:** Python 3.12, `websockets` library (add to requirements), `asyncio`, `threading`, RSA-PSS signing (already in `kalshi_client.py`), pytest

**⚠️ API Note:** Since March 12, 2026, Kalshi prices are expressed as dollar strings with 4 decimal places (`"0.6500"`). Use `yes_dollars_fp`/`no_dollars_fp` fields — NOT legacy integer cents. Verify current field names in the Kalshi API docs before implementing.

---

## Task 1: Kalshi WebSocket Client

**Files:**
- Create: `kalshi_ws.py`
- Modify: `requirements.txt` (add `websockets>=12.0`)
- Create: `tests/test_kalshi_ws.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kalshi_ws.py`:

```python
"""Tests for Kalshi WebSocket client."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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

        from kalshi_ws import update_orderbook_cache, read_orderbook_cache

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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_kalshi_ws.py -v
```

Expected: `ModuleNotFoundError: No module named 'kalshi_ws'`

- [ ] **Step 3: Add `websockets` to requirements**

Check if `requirements.txt` exists:
```bash
cat requirements.txt
```

Add (or create `requirements.txt`):
```
websockets>=12.0
```

- [ ] **Step 4: Implement `kalshi_ws.py`**

Create `kalshi_ws.py`:

```python
"""
Kalshi WebSocket client — real-time order book and ticker data.

Runs as a background thread. Writes snapshots to data/orderbook_cache.json
for consumption by the main trading loop.

API: wss://api.elections.kalshi.com/trade-api/ws/v2
Auth: RSA-PSS signed (same key as REST API)

⚠️ March 12, 2026 migration: prices are dollar strings ("0.6500")
   Use yes_dollars_fp / no_dollars_fp — NOT legacy integer cent fields.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
_CACHE_PATH = Path(__file__).parent / "data" / "orderbook_cache.json"
_CACHE_PATH.parent.mkdir(exist_ok=True)

# In-memory order book state (ticker → snapshot)
_orderbook: dict[str, dict] = {}
_cache_lock = threading.Lock()


# ── Message parsing ───────────────────────────────────────────────────────────

def parse_message(msg: dict) -> dict | None:
    """
    Parse a Kalshi WebSocket message into a normalized dict.

    Returns None for unknown/empty message types.
    """
    msg_type = msg.get("type")
    inner = msg.get("msg", {})
    if not msg_type or not inner:
        return None

    ticker = inner.get("market_ticker")
    if not ticker:
        return None

    if msg_type == "orderbook_snapshot":
        yes_levels = inner.get("yes", [])  # [[price_str, qty], ...]
        no_levels = inner.get("no", [])
        best_yes_bid = float(yes_levels[0][0]) if yes_levels else None
        best_no_bid = float(no_levels[0][0]) if no_levels else None
        return {
            "type": "orderbook_snapshot",
            "ticker": ticker,
            "best_yes_bid": best_yes_bid,
            "best_no_bid": best_no_bid,
            "yes_levels": yes_levels,
            "no_levels": no_levels,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    elif msg_type == "orderbook_delta":
        # Delta updates: apply to existing snapshot (simplified — just record delta)
        return {
            "type": "orderbook_delta",
            "ticker": ticker,
            "delta": inner,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    elif msg_type == "ticker":
        yes_bid_str = inner.get("yes_bid") or inner.get("yes_dollars_fp") or "0"
        yes_ask_str = inner.get("yes_ask") or "0"
        try:
            yes_bid = float(yes_bid_str)
            yes_ask = float(yes_ask_str)
            mid = (yes_bid + yes_ask) / 2 if yes_ask > 0 else yes_bid
        except (ValueError, TypeError):
            mid = 0.0
        return {
            "type": "ticker",
            "ticker": ticker,
            "yes_bid": yes_bid if 'yes_bid' in locals() else 0.0,
            "yes_ask": yes_ask if 'yes_ask' in locals() else 0.0,
            "mid_price": mid,
            "last_price": float(inner.get("last_price") or 0),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    return None


# ── Order book cache ──────────────────────────────────────────────────────────

def update_orderbook_cache(ticker: str, data: dict) -> None:
    """Update in-memory and on-disk cache for a ticker."""
    with _cache_lock:
        _orderbook[ticker] = data
        try:
            cache = {}
            if _CACHE_PATH.exists():
                cache = json.loads(_CACHE_PATH.read_text())
            cache[ticker] = data
            cache["_updated_at"] = datetime.now(timezone.utc).isoformat()
            _CACHE_PATH.write_text(json.dumps(cache))
        except Exception as exc:
            _log.debug("update_orderbook_cache: %s", exc)


def read_orderbook_cache() -> dict:
    """Read the current order book cache from disk."""
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def get_cached_mid_price(ticker: str) -> float | None:
    """Return the cached mid-price for a ticker, or None if not cached."""
    cache = read_orderbook_cache()
    entry = cache.get(ticker)
    if not entry:
        return None
    return entry.get("mid_price")


# ── WebSocket subscription ────────────────────────────────────────────────────

def build_subscribe_message(
    cmd_id: int,
    channels: list[str],
    market_tickers: list[str],
) -> dict:
    """Build a Kalshi WebSocket subscribe command payload."""
    return {
        "id": cmd_id,
        "cmd": "subscribe",
        "params": {
            "channels": channels,
            "market_tickers": market_tickers,
        },
    }


async def _ws_listener(api_key: str, private_key_pem: str, tickers: list[str]) -> None:
    """
    Async WebSocket listener. Connects, authenticates, subscribes to tickers,
    and processes incoming messages indefinitely.
    """
    try:
        import websockets
    except ImportError:
        _log.error("kalshi_ws: websockets package not installed. Run: pip install websockets>=12.0")
        return

    import time as _time
    import hmac
    import base64

    # RSA-PSS authentication (same pattern as REST API)
    timestamp = str(int(_time.time() * 1000))
    message_to_sign = f"{timestamp}GET/trade-api/ws/v2".encode()

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend

        private_key = serialization.load_pem_private_key(
            private_key_pem.encode() if isinstance(private_key_pem, str) else private_key_pem,
            password=None,
            backend=default_backend(),
        )
        signature = private_key.sign(message_to_sign, padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ), hashes.SHA256())
        sig_b64 = base64.b64encode(signature).decode()
    except Exception as exc:
        _log.error("kalshi_ws: auth signing failed: %s", exc)
        return

    headers = {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }

    while True:
        try:
            async with websockets.connect(_WS_URL, additional_headers=headers) as ws:
                _log.info("kalshi_ws: connected to %s", _WS_URL)

                # Subscribe to ticker + orderbook for all requested markets
                sub_msg = build_subscribe_message(
                    cmd_id=1,
                    channels=["ticker", "orderbook_delta"],
                    market_tickers=tickers,
                )
                await ws.send(json.dumps(sub_msg))

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        parsed = parse_message(msg)
                        if parsed and parsed.get("ticker"):
                            update_orderbook_cache(parsed["ticker"], parsed)
                    except Exception as exc:
                        _log.debug("kalshi_ws: parse error: %s", exc)

        except Exception as exc:
            _log.warning("kalshi_ws: connection error: %s — reconnecting in 10s", exc)
            await asyncio.sleep(10)


class KalshiWebSocket:
    """
    Background WebSocket thread for real-time Kalshi order book data.

    Usage:
        ws = KalshiWebSocket(api_key, private_key_pem)
        ws.subscribe(["KXHIGHNY-26APR17-T72", ...])
        ws.start()
        # ... bot runs ...
        ws.stop()
    """

    def __init__(self, api_key: str, private_key_pem: str) -> None:
        self._api_key = api_key
        self._private_key_pem = private_key_pem
        self._tickers: list[str] = []
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    def subscribe(self, tickers: list[str]) -> None:
        """Add tickers to subscribe to."""
        self._tickers = list(set(self._tickers + tickers))

    def start(self) -> None:
        """Start the WebSocket listener in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="KalshiWS")
        self._thread.start()
        _log.info("kalshi_ws: background thread started")

    def stop(self) -> None:
        """Stop the WebSocket listener."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        _log.info("kalshi_ws: stopped")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(
                _ws_listener(self._api_key, self._private_key_pem, self._tickers)
            )
        except Exception as exc:
            _log.error("kalshi_ws: thread error: %s", exc)
        finally:
            self._loop.close()
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_kalshi_ws.py -v
```

Expected: all tests PASSED

- [ ] **Step 6: Commit**

```bash
git add kalshi_ws.py tests/test_kalshi_ws.py
git commit -m "feat(phase-f): add KalshiWebSocket client — real-time order book; parse/cache messages"
```

---

## Task 2: Wire WebSocket into Cron Loop (Optional)

**Files:**
- Modify: `main.py` (start WS thread at cron start, use cached prices)

This task is optional — the bot works without it. The WebSocket provides fresher prices than REST polling, enabling settlement lag automation and microstructure signals.

- [ ] **Step 1: Start WebSocket thread at cron startup**

In `cmd_cron()` in `main.py`, before the main loop:

```python
# Optional: start WebSocket for real-time price feeds
_ws = None
try:
    from kalshi_ws import KalshiWebSocket
    import os
    api_key = os.getenv("KALSHI_API_KEY", "")
    key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
    if api_key and key_pem:
        _ws = KalshiWebSocket(api_key, key_pem)
        # Subscribe to all active weather market tickers
        # _ws.subscribe(active_tickers)  # add after market scan
        _ws.start()
        _log.info("WebSocket thread started")
except Exception as exc:
    _log.debug("WebSocket not available: %s", exc)
```

- [ ] **Step 2: Use cached prices in `_validate_trade_opportunity`**

In `_validate_trade_opportunity`, before the REST API price check:

```python
# Try WebSocket cache for fresher price first
try:
    from kalshi_ws import get_cached_mid_price
    cached_mid = get_cached_mid_price(opp["ticker"])
    if cached_mid and cached_mid > 0:
        # Use cached price — it's more recent than REST poll
        opp["_ws_mid_price"] = cached_mid
except Exception:
    pass
```

- [ ] **Step 3: Run full test suite**

```
python -m pytest -x -q
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(phase-f): wire WebSocket into cron — use cached prices for faster trade validation"
```
