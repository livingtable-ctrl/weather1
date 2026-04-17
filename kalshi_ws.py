"""
Kalshi WebSocket client — real-time order book and ticker data.

Runs as a background thread. Writes snapshots to data/orderbook_cache.json
for consumption by the main trading loop.

API: wss://api.elections.kalshi.com/trade-api/ws/v2
Auth: RSA-PSS signed (same key as REST API)

⚠️ March 12, 2026 migration: prices are dollar strings ("0.6500")
   Use yes_bid/yes_ask dollar string fields — NOT legacy integer cent fields.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger(__name__)

_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
_CACHE_PATH = Path(__file__).parent / "data" / "orderbook_cache.json"
# Fix 6: mkdir moved out of import time — now called inside update_orderbook_cache

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
        # Kalshi sends yes levels sorted best-bid-first per API spec
        best_yes_bid = float(yes_levels[0][0]) if yes_levels else None
        best_no_bid = float(no_levels[0][0]) if no_levels else None
        return {
            "type": "orderbook_snapshot",
            "ticker": ticker,
            "best_yes_bid": best_yes_bid,
            "best_no_bid": best_no_bid,
            "yes_levels": yes_levels,
            "no_levels": no_levels,
            "ts": datetime.now(UTC).isoformat(),
        }

    elif msg_type == "orderbook_delta":
        return {
            "type": "orderbook_delta",
            "ticker": ticker,
            "delta": inner,
            "ts": datetime.now(UTC).isoformat(),
        }

    elif msg_type == "ticker":
        yes_bid_str = inner.get("yes_bid") or inner.get("yes_dollars_fp") or "0"
        yes_ask_str = inner.get("yes_ask") or "0"
        try:
            yes_bid = float(yes_bid_str)
            yes_ask = float(yes_ask_str)
            mid = (yes_bid + yes_ask) / 2 if yes_ask > 0 else yes_bid
        except (ValueError, TypeError):
            yes_bid = 0.0
            yes_ask = 0.0
            mid = 0.0
        return {
            "type": "ticker",
            "ticker": ticker,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "mid_price": mid,
            "last_price": float(inner.get("last_price") or 0),
            "ts": datetime.now(UTC).isoformat(),
        }

    return None


# ── Order book cache ──────────────────────────────────────────────────────────


def update_orderbook_cache(ticker: str, data: dict) -> None:
    """Update in-memory and on-disk cache for a ticker."""
    import safe_io

    with _cache_lock:
        if data.get("type") == "orderbook_delta":
            # Merge delta into existing entry to preserve mid_price
            existing = _orderbook.get(ticker, {})
            existing["last_delta"] = data["delta"]
            existing["ts"] = data["ts"]
            _orderbook[ticker] = existing
            merged = existing
        else:
            _orderbook[ticker] = data
            merged = data
        try:
            cache = {}
            if _CACHE_PATH.exists():
                cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            cache[ticker] = merged
            cache["_updated_at"] = datetime.now(UTC).isoformat()
            # Fix 6: mkdir called here, just before the write
            _CACHE_PATH.parent.mkdir(exist_ok=True)
            safe_io.atomic_write_json(cache, _CACHE_PATH)
        except Exception as exc:
            _log.debug("update_orderbook_cache: %s", exc)


def read_orderbook_cache() -> dict:
    """Read the current order book cache from disk."""
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_cached_mid_price(ticker: str) -> float | None:
    """Return the cached mid-price for a ticker, or None if not cached."""
    # Try in-memory first (faster than disk read)
    with _cache_lock:
        entry = _orderbook.get(ticker)
    if entry and entry.get("mid_price") is not None:
        return entry["mid_price"]
    # Fall back to disk cache
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
        _log.error(
            "kalshi_ws: websockets package not installed. Run: pip install websockets>=12.0"
        )
        return

    import base64

    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        # Load the key once (expensive) — signing repeats each reconnect
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        _raw_key = serialization.load_pem_private_key(
            private_key_pem.encode()
            if isinstance(private_key_pem, str)
            else private_key_pem,
            password=None,
            backend=default_backend(),
        )
        if not isinstance(_raw_key, RSAPrivateKey):
            raise ValueError("kalshi_ws: private key must be RSA")
        private_key: RSAPrivateKey = _raw_key
    except Exception as exc:
        _log.error("kalshi_ws: key loading failed: %s", exc)
        return

    while True:
        try:
            # Recompute auth on every connect attempt (timestamp must be fresh)
            timestamp = str(int(time.time() * 1000))
            message_to_sign = f"{timestamp}GET/trade-api/ws/v2".encode()
            try:
                signature = private_key.sign(
                    message_to_sign,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH,
                    ),
                    hashes.SHA256(),
                )
                sig_b64 = base64.b64encode(signature).decode()
            except Exception as exc:
                _log.error("kalshi_ws: auth signing failed: %s", exc)
                await asyncio.sleep(10)
                continue

            headers = {
                "KALSHI-ACCESS-KEY": api_key,
                "KALSHI-ACCESS-SIGNATURE": sig_b64,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
            }

            async with websockets.connect(_WS_URL, additional_headers=headers) as ws:
                _log.info("kalshi_ws: connected to %s", _WS_URL)

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
        """Add tickers to subscribe to. Must be called before start()."""
        if self._running:
            raise RuntimeError("subscribe() must be called before start()")
        self._tickers = list(set(self._tickers + tickers))

    def start(self) -> None:
        """Start the WebSocket listener in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="KalshiWS")
        self._thread.start()
        _log.info("kalshi_ws: background thread started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the WebSocket listener."""
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=timeout)
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
