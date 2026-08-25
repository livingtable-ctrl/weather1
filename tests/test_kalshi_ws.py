"""Tests for Kalshi WebSocket client."""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
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

    def test_orderbook_delta_does_not_refresh_mid_price_timestamp(
        self, tmp_path, monkeypatch
    ):
        """A delta message must not bump `ts` (or touch mid_price) -- only a
        "ticker"-type message actually refreshes mid_price, and bumping `ts`
        on every delta would make a frozen mid_price look "fresh" forever as
        long as deltas keep arriving, defeating get_cached_mid_price()'s
        staleness gate on this safety-critical input (feeds
        order_executor.py's flash-crash circuit breaker check)."""
        import kalshi_ws

        monkeypatch.setattr(kalshi_ws, "_CACHE_PATH", tmp_path / "orderbook_cache.json")
        monkeypatch.setattr(kalshi_ws, "_orderbook", {})

        from kalshi_ws import update_orderbook_cache

        update_orderbook_cache(
            "TICKER-A",
            {"type": "ticker", "mid_price": 0.65, "ts": "2020-01-01T00:00:00+00:00"},
        )
        original_entry = dict(kalshi_ws._orderbook["TICKER-A"])

        update_orderbook_cache(
            "TICKER-A",
            {
                "type": "orderbook_delta",
                "delta": {"some": "delta"},
                "ts": "2099-01-01T00:00:00+00:00",  # a much "fresher" ts
            },
        )
        updated_entry = kalshi_ws._orderbook["TICKER-A"]

        assert updated_entry["mid_price"] == original_entry["mid_price"]
        assert updated_entry["ts"] == original_entry["ts"], (
            "delta must not overwrite ts with a fresher timestamp -- mid_price "
            "wasn't actually refreshed"
        )
        assert updated_entry["last_delta"] == {"some": "delta"}

    def test_ticker_message_feeds_flash_crash_breaker(self, tmp_path, monkeypatch):
        """2026-07-12: a 'ticker'-type message must feed flash_crash_cb.check()
        on every live tick -- this is what makes the breaker able to observe a
        genuine sub-5-minute crash at all, since order_executor.py's own
        per-scan-cycle check() call can't (see FlashCrashCB's docstring)."""
        import kalshi_ws
        from circuit_breaker import flash_crash_cb

        monkeypatch.setattr(kalshi_ws, "_CACHE_PATH", tmp_path / "orderbook_cache.json")
        monkeypatch.setattr(kalshi_ws, "_orderbook", {})

        from kalshi_ws import update_orderbook_cache

        update_orderbook_cache("KXTEST", {"type": "ticker", "mid_price": 0.60})
        assert flash_crash_cb.is_in_cooldown("KXTEST") is False

        # Same-ticker 40% drop, well past the 20% default threshold.
        update_orderbook_cache("KXTEST", {"type": "ticker", "mid_price": 0.20})
        assert flash_crash_cb.is_in_cooldown("KXTEST") is True

    def test_delta_message_does_not_feed_flash_crash_breaker(
        self, tmp_path, monkeypatch
    ):
        """An orderbook_delta carries no real mid_price -- it must not reach
        flash_crash_cb.check() at all (a stale/zero price would either be a
        no-op or, worse, a false reading)."""
        import kalshi_ws
        from circuit_breaker import flash_crash_cb

        monkeypatch.setattr(kalshi_ws, "_CACHE_PATH", tmp_path / "orderbook_cache.json")
        monkeypatch.setattr(kalshi_ws, "_orderbook", {})

        from kalshi_ws import update_orderbook_cache

        calls = []
        monkeypatch.setattr(
            flash_crash_cb, "check", lambda t, p: calls.append((t, p)) or False
        )

        update_orderbook_cache(
            "KXTEST", {"type": "orderbook_delta", "delta": {"some": "delta"}}
        )

        assert calls == []


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
        # get_cached_mid_price re-imports WS_CACHE_TTL_SECS from utils fresh on
        # every call (function-local import), so monkeypatching the attribute
        # directly is enough -- no need to reload the whole utils module (which
        # would rebind every other symbol in it, including is_trading_paused,
        # and diverge from main.py's frozen `from utils import ...` for the
        # rest of the test session; see backlog.txt's frozen-import entry).
        import utils

        monkeypatch.setattr(utils, "WS_CACHE_TTL_SECS", 900)
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


class TestKalshiWebSocketLifecycle:
    def test_stop_cancels_task_and_thread_exits_cleanly(self, monkeypatch):
        """stop() must cancel the running task (not just stop the loop) so
        the async-with-websockets-connect cleanup actually runs and the
        background thread exits within the join timeout, instead of
        abandoning the connection and leaving the thread's loop.close()
        unconfirmed."""
        import asyncio

        import kalshi_ws

        async def _fake_listener(api_key, private_key_pem, tickers):
            kalshi_ws._set_ws_alive(True)
            try:
                await asyncio.sleep(100)
            finally:
                # Mirrors _ws_listener's real finally: _set_ws_alive(False) --
                # only runs if the task is actually cancelled (propagating
                # through this finally), not if the loop were merely stopped
                # out from under an abandoned coroutine.
                kalshi_ws._set_ws_alive(False)

        monkeypatch.setattr(kalshi_ws, "_ws_listener", _fake_listener)

        ws = kalshi_ws.KalshiWebSocket("key", "pem")
        ws.start()
        # Give the background thread a moment to create its event loop/task.
        for _ in range(50):
            if ws._task is not None:
                break
            time.sleep(0.02)
        assert ws._task is not None, "background thread never created its task"
        # Wait for _fake_listener to actually start running (sets alive=True)
        # before stopping, so the post-stop check proves the finally ran.
        for _ in range(50):
            if kalshi_ws.get_ws_health()["alive"]:
                break
            time.sleep(0.02)
        assert kalshi_ws.get_ws_health()["alive"] is True

        ws.stop(timeout=2.0)

        assert kalshi_ws.get_ws_health()["alive"] is False, (
            "the task's finally block must run on cancellation, proving the "
            "connection cleanup path executed rather than the coroutine "
            "being abandoned mid-flight"
        )

        assert not ws._thread.is_alive(), (
            "thread must exit promptly once its task is cancelled"
        )


class TestWsListenerCleanCloseReconnect:
    """AUD batch-23 #4: a clean disconnect (the async-for read loop simply
    ends with no exception -- e.g. a rejected auth/subscribe, or the server
    closing with a valid close frame) must clear _ws_alive and back off
    exactly like the except-Exception path already did, instead of
    reconnecting at full speed while get_ws_health() keeps reporting
    alive=True throughout the thrash."""

    def test_clean_close_clears_alive_and_backs_off_before_reconnecting(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        import kalshi_ws

        class _FakeConnection:
            """Models a clean close: `async for raw in ws` ends immediately
            with no messages and no exception -- NOT a raised exception,
            which is what the except-Exception branch already handled."""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            async def send(self, data):
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        fake_key = MagicMock(spec=RSAPrivateKey)
        fake_key.sign.return_value = b"fake-signature"

        # A single ordered event log (not separate counters) so the test can
        # assert WHEN alive went False relative to the second connect
        # attempt -- not just that it eventually went False somewhere (the
        # pre-fix code also clears it, just too late: only in the outer
        # `finally`, after CancelledError from the SECOND connect has
        # already unwound the loop).
        events = []
        real_set_alive = kalshi_ws._set_ws_alive

        def _spy_set_alive(value):
            real_set_alive(value)
            events.append(("alive", value))

        connect_calls = {"n": 0}

        def _fake_connect(url, additional_headers=None):
            connect_calls["n"] += 1
            events.append(("connect", connect_calls["n"]))
            if connect_calls["n"] >= 2:
                # Deterministically end the otherwise-infinite reconnect
                # loop once one full clean-close cycle has been observed.
                # CancelledError is a BaseException (not Exception), so it
                # is NOT swallowed by the `except Exception` branch -- it
                # propagates straight out, same as a real task cancellation.
                raise asyncio.CancelledError()
            return _FakeConnection()

        with (
            patch(
                "cryptography.hazmat.primitives.serialization.load_pem_private_key",
                return_value=fake_key,
            ),
            patch("websockets.connect", side_effect=_fake_connect),
            patch.object(kalshi_ws, "_set_ws_alive", side_effect=_spy_set_alive),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(kalshi_ws._ws_listener("key", "pem", ["TICKER"]))

        assert events[0] == ("connect", 1)
        assert events[1] == ("alive", True)
        # The clean close must clear alive=False BEFORE the second connect
        # attempt fires -- not merely "eventually" via the outer `finally`
        # once the whole loop has already unwound. Find each event's index
        # explicitly rather than assuming a fixed slice position.
        first_false_idx = events.index(("alive", False))
        second_connect_idx = events.index(("connect", 2))
        assert first_false_idx < second_connect_idx, (
            f"_ws_alive must go False before the reconnect attempt, not "
            f"after: events={events}"
        )

        # The clean-close path must back off exactly like the exception
        # path already did -- one 10s sleep between the clean close and the
        # second connect attempt.
        mock_sleep.assert_awaited_once_with(10)

        # Positive control: it DID actually reconnect after backing off
        # (not stuck) -- the second connect call is what raised
        # CancelledError to end this test.
        assert connect_calls["n"] == 2


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
        import utils

        # Use a small offset so last_msg is always > 0 on any machine/CI runner,
        # then set TTL to 1 s so 5 s of idle always exceeds it.
        monkeypatch.setattr(kalshi_ws, "_ws_last_message_ts", time.monotonic() - 5)
        monkeypatch.setattr(kalshi_ws, "_ws_alive", True)
        monkeypatch.setattr(utils, "WS_CACHE_TTL_SECS", 1.0)
        h = kalshi_ws.get_ws_health()
        assert h["stale"] is True


class TestWebSocketHostSelection:
    """Batch-58 item 2 (backlog L25371): kalshi_ws.py hardcoded the PROD
    WebSocket host with no KALSHI_ENV read anywhere in the file, so a
    demo-mode run fed REAL production prices to order_executor's
    reprice/chase logic and the flash-crash circuit breaker."""

    def test_prod_env_selects_the_prod_host(self, monkeypatch):
        from kalshi_ws import PROD_WS_URL, _ws_url

        monkeypatch.setenv("KALSHI_ENV", "prod")
        assert _ws_url() == PROD_WS_URL
        assert "api.elections.kalshi.com" in PROD_WS_URL

    def test_demo_env_selects_the_demo_host(self, monkeypatch):
        from kalshi_ws import DEMO_WS_URL, _ws_url

        monkeypatch.setenv("KALSHI_ENV", "demo")
        assert _ws_url() == DEMO_WS_URL
        assert "demo-api.kalshi.co" in DEMO_WS_URL

    def test_unset_env_defaults_to_demo(self, monkeypatch):
        from kalshi_ws import DEMO_WS_URL, _ws_url

        monkeypatch.delenv("KALSHI_ENV", raising=False)
        assert _ws_url() == DEMO_WS_URL

    @pytest.mark.parametrize("value", ["PROD", "Prod", "production", "prod ", ""])
    def test_any_non_exact_prod_string_falls_back_to_demo(self, monkeypatch, value):
        """Polarity matters, and it is the polarity AUD-0015 fixed for the
        REST client: `PROD if env == "prod" else DEMO`. The inverted form
        (`DEMO if env == "demo" else PROD`) silently points every
        non-exact-'demo' string at PROD -- exactly the bug this mirrors away
        from. Failing toward DEMO is the safe direction."""
        from kalshi_ws import DEMO_WS_URL, _ws_url

        monkeypatch.setenv("KALSHI_ENV", value)
        assert _ws_url() == DEMO_WS_URL

    def test_the_two_hosts_are_actually_different(self, monkeypatch):
        """Positive control for the whole class: if a future edit collapsed
        both constants onto the same host, every assertion above would still
        pass while the bug was fully back."""
        from kalshi_ws import DEMO_WS_URL, PROD_WS_URL

        assert PROD_WS_URL != DEMO_WS_URL

    def test_ws_hosts_mirror_the_rest_bases(self, monkeypatch):
        """The two selections must not drift: each WS host is its REST
        sibling's origin with the ws/v2 path."""
        from kalshi_client import DEMO_BASE, PROD_BASE
        from kalshi_ws import DEMO_WS_URL, PROD_WS_URL

        for rest, ws in ((PROD_BASE, PROD_WS_URL), (DEMO_BASE, DEMO_WS_URL)):
            rest_host = rest.split("://", 1)[1].split("/", 1)[0]
            ws_host = ws.split("://", 1)[1].split("/", 1)[0]
            assert rest_host == ws_host
            assert ws.startswith("wss://")
            assert ws.endswith("/trade-api/ws/v2")

    def test_ws_url_reads_the_env_at_call_time_not_at_import(self, monkeypatch):
        """_ws_url() itself must not freeze a value at import time -- a
        module constant cannot see a .env loaded later. WHEN it is called is
        the caller's decision; _ws_listener calls it exactly once, before
        its reconnect loop (see
        test_the_host_is_frozen_for_the_listeners_lifetime)."""
        from kalshi_ws import DEMO_WS_URL, PROD_WS_URL, _ws_url

        monkeypatch.setenv("KALSHI_ENV", "prod")
        assert _ws_url() == PROD_WS_URL
        monkeypatch.setenv("KALSHI_ENV", "demo")
        assert _ws_url() == DEMO_WS_URL

    def _run_listener_capturing_urls(self, monkeypatch, env):
        """Drive the real _ws_listener far enough to capture the URL it
        actually connects to, then stop it deterministically.

        Mirrors TestWsAliveClearedOnCleanClose's harness: CancelledError is
        a BaseException, so it propagates out of the `except Exception`
        reconnect branch instead of being swallowed.
        """
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        import kalshi_ws

        fake_key = MagicMock(spec=RSAPrivateKey)
        fake_key.sign.return_value = b"fake-signature"

        urls = []

        def _fake_connect(url, additional_headers=None):
            urls.append(url)
            raise asyncio.CancelledError()

        monkeypatch.setenv("KALSHI_ENV", env)
        with (
            patch(
                "cryptography.hazmat.primitives.serialization.load_pem_private_key",
                return_value=fake_key,
            ),
            patch("websockets.connect", side_effect=_fake_connect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(kalshi_ws._ws_listener("key", "pem", ["TICKER"]))
        return urls

    def test_the_listener_actually_connects_to_the_selected_host(self, monkeypatch):
        """Opus review (batch-58, M2): this class's other tests all exercise
        _ws_url() in ISOLATION. The test that previously claimed to guard
        the real bug only asserted `"_ws_url()" in inspect.getsource(...)` --
        satisfied by the function's own `def` line, so a full revert of the
        connect site to `websockets.connect(PROD_WS_URL, ...)` passed it.
        Proven vacuous by executing that exact mutant. This asserts the URL
        _ws_listener hands to websockets.connect instead."""
        from kalshi_ws import DEMO_WS_URL, PROD_WS_URL

        assert self._run_listener_capturing_urls(monkeypatch, "demo") == [DEMO_WS_URL]
        assert self._run_listener_capturing_urls(monkeypatch, "prod") == [PROD_WS_URL]

    def test_the_host_is_frozen_for_the_listeners_lifetime(self, monkeypatch):
        """Opus review (batch-58, M3): the host is resolved ONCE, before the
        reconnect loop. A WS thread that re-read KALSHI_ENV per reconnect
        could start writing demo book data into the same orderbook cache a
        still-prod REST client trades against -- the "M-25 desync" class
        main.py's own KALSHI_ENV snapshot/restore exists to prevent.

        Flips the env between reconnect 1 and 2 and asserts BOTH connects
        used the original host."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        import kalshi_ws

        fake_key = MagicMock(spec=RSAPrivateKey)
        fake_key.sign.return_value = b"fake-signature"

        urls = []

        def _fake_connect(url, additional_headers=None):
            urls.append(url)
            if len(urls) == 1:
                # Flip the env mid-flight, then force a reconnect.
                import os

                os.environ["KALSHI_ENV"] = "prod"
                raise ConnectionError("dropped")
            raise asyncio.CancelledError()

        monkeypatch.setenv("KALSHI_ENV", "demo")
        with (
            patch(
                "cryptography.hazmat.primitives.serialization.load_pem_private_key",
                return_value=fake_key,
            ),
            patch("websockets.connect", side_effect=_fake_connect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(kalshi_ws._ws_listener("key", "pem", ["TICKER"]))

        assert len(urls) == 2, f"expected a reconnect, got {urls}"
        assert urls == [kalshi_ws.DEMO_WS_URL, kalshi_ws.DEMO_WS_URL], (
            "the second connect must reuse the host resolved at listener "
            f"start, not re-read KALSHI_ENV: {urls}"
        )
        # Positive control: _ws_url() itself DOES see the flipped env, so
        # the equality above is the freeze and not a broken monkeypatch.
        assert kalshi_ws._ws_url() == kalshi_ws.PROD_WS_URL


class TestOrderbookCacheEnvNamespacing:
    """Opus review (batch-58, L2): the on-disk orderbook cache is a single
    env-agnostic file keyed only by ticker. Without an env stamp, an
    operator who runs prod, stops, switches to KALSHI_ENV=demo and starts
    the L6585 demo smoke test within WS_CACHE_TTL_SECS (900s) gets the
    still-fresh PROD entries served from disk -- feeding prod prices to
    reprice/chase and the flash-crash breaker exactly as before item 2's
    fix, i.e. defeating the fix in the one scenario it exists for."""

    def _write_cache(self, tmp_path, monkeypatch, env):
        import kalshi_ws

        monkeypatch.setattr(kalshi_ws, "_CACHE_PATH", tmp_path / "orderbook.json")
        monkeypatch.setenv("KALSHI_ENV", env)
        with kalshi_ws._cache_lock:
            kalshi_ws._orderbook.clear()
        kalshi_ws.update_orderbook_cache(
            "KXHIGHNY-26APR17-T72",
            {
                "type": "ticker",
                "ticker": "KXHIGHNY-26APR17-T72",
                "yes_bid": 0.63,
                "yes_ask": 0.67,
                "mid_price": 0.65,
                "last_price": 0.64,
                "ts": datetime.now(UTC).isoformat(),
            },
        )
        # Drop the in-memory half so the disk fallback is what gets exercised
        # -- the in-memory cache cannot outlive the process that filled it,
        # so it is not the path this guard is about.
        with kalshi_ws._cache_lock:
            kalshi_ws._orderbook.clear()

    def test_the_env_is_stamped_on_the_cache_file(self, tmp_path, monkeypatch):
        import json

        self._write_cache(tmp_path, monkeypatch, "prod")
        cache = json.loads((tmp_path / "orderbook.json").read_text(encoding="utf-8"))
        assert cache["_env"] == "prod"

    def test_a_prod_cache_is_not_served_to_a_demo_run(self, tmp_path, monkeypatch):
        import kalshi_ws

        self._write_cache(tmp_path, monkeypatch, "prod")

        # Positive control FIRST: still in prod, the fresh entry IS served --
        # so the None below is the env mismatch, not an empty/stale cache.
        assert kalshi_ws.get_cached_mid_price("KXHIGHNY-26APR17-T72") == pytest.approx(
            0.65
        )

        monkeypatch.setenv("KALSHI_ENV", "demo")
        assert kalshi_ws.get_cached_mid_price("KXHIGHNY-26APR17-T72") is None
        assert kalshi_ws.get_cached_book("KXHIGHNY-26APR17-T72") is None

    def test_a_demo_cache_is_not_served_to_a_prod_run(self, tmp_path, monkeypatch):
        """Both directions -- a stale demo book reaching a real prod
        reprice/chase decision is the more dangerous of the two."""
        import kalshi_ws

        self._write_cache(tmp_path, monkeypatch, "demo")
        assert kalshi_ws.get_cached_mid_price("KXHIGHNY-26APR17-T72") == pytest.approx(
            0.65
        )

        monkeypatch.setenv("KALSHI_ENV", "prod")
        assert kalshi_ws.get_cached_mid_price("KXHIGHNY-26APR17-T72") is None

    def test_a_cache_predating_the_stamp_is_treated_as_stale(
        self, tmp_path, monkeypatch
    ):
        """Self-heals on the first write rather than being served blindly."""
        import json

        import kalshi_ws

        self._write_cache(tmp_path, monkeypatch, "prod")
        path = tmp_path / "orderbook.json"
        cache = json.loads(path.read_text(encoding="utf-8"))
        del cache["_env"]
        path.write_text(json.dumps(cache), encoding="utf-8")

        assert kalshi_ws.get_cached_mid_price("KXHIGHNY-26APR17-T72") is None
