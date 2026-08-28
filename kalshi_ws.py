"""
Kalshi WebSocket client — real-time order book and ticker data.

Runs as a background thread. Writes snapshots to data/orderbook_cache.json
for consumption by the main trading loop.

API: wss://api.elections.kalshi.com/trade-api/ws/v2 (prod)
     wss://demo-api.kalshi.co/trade-api/ws/v2 (demo)
     Selected per KALSHI_ENV, mirroring kalshi_client's REST base_url.
Auth: RSA-PSS signed (same key as REST API)

⚠️ March 12, 2026 migration: prices are dollar strings ("0.6500")
   Use yes_bid/yes_ask dollar string fields — NOT legacy integer cent fields.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
from datetime import UTC, datetime

from circuit_breaker import flash_crash_cb
from paths import ORDERBOOK_CACHE_PATH as _CACHE_PATH

_log = logging.getLogger(__name__)

# Batch-58 item 2 (backlog L25371): this module previously hardcoded the
# PROD host with no KALSHI_ENV read anywhere in the file, so a demo-mode run
# fed REAL production prices to every consumer of the cache
# (order_executor's reprice/chase logic via get_cached_book, and its
# flash-crash circuit-breaker check via get_cached_mid_price) -- and, most
# directly of all, to flash_crash_cb.check() itself, which
# update_orderbook_cache below calls IN-PROCESS on every tick. Opus review
# (batch-58, I1): that third consumer means a demo run's flash-crash breaker
# was being tripped by live prod ticks, not merely reading prod prices back
# out of a cache; the pre-fix blast radius was larger than first written.
#
# That made demo-mode dry runs quietly misleading rather than unsafe -- and
# specifically undercut the DEMO_BASE smoke test (backlog L6585) that is a
# hard prerequisite before ENABLE_MICRO_LIVE is ever flipped on: a demo
# smoke test reading prod prices does not validate what it claims to.
#
# Note for whoever runs that smoke test: there is only one credential pair
# in this repo (KALSHI_KEY_ID plus KALSHI_PRIVATE_KEY_PATH, with
# KALSHI_PRIVATE_KEY_PEM as an inline alternative; no demo variants),
# so a demo run using prod credentials will most likely fail auth against
# demo-api.kalshi.co and reconnect-loop rather than produce a feed at all.
# That is the correct direction -- no data beats wrong data, and
# _get_current_book has a REST fallback -- but it means the demo smoke test
# needs demo credentials to exercise the WS path (opus review, batch-58,
# I2). The demo REST client already had the same limitation.
#
# Two explicit constants selected by `PROD if env == "prod" else DEMO`,
# deliberately mirroring kalshi_client.PROD_BASE/DEMO_BASE and
# KalshiClient.__init__'s own selection polarity rather than inventing a
# second convention. The polarity matters: AUD-0015 fixed the inverted
# `DEMO if env == "demo" else PROD` form, which silently pointed any
# non-exact-'demo' string at PROD. Hosts mirror their REST siblings exactly
# (api.elections.kalshi.com / demo-api.kalshi.co) with the ws/v2 path.
PROD_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"


def _ws_url() -> str:
    """Return the WebSocket host for the current KALSHI_ENV.

    Resolved at import time is wrong (a module constant can't see a .env
    loaded later); resolved per-CONNECT is also wrong, and deliberately not
    what _ws_listener does -- see its own `ws_url` comment. This reads the
    env at call time; the caller decides when that is.

    Opus review (batch-58, M3): the first version of this docstring claimed
    per-connect freshness "for the same reason main._kalshi_env() does."
    That was backwards -- main.py goes out of its way to make KALSHI_ENV
    survive a mid-process .env reload unchanged (see its _preserved_
    kalshi_env snapshot/restore, and cmd_settings' outright refusal to edit
    KALSHI_ENV in-session), because a live client's base_url is frozen at
    build_client() and an env that could drift out from under it is the
    "M-25 desync" that machinery exists to prevent.
    """
    return PROD_WS_URL if os.getenv("KALSHI_ENV", "demo") == "prod" else DEMO_WS_URL


# Fix 6: mkdir moved out of import time — now called inside update_orderbook_cache

# In-memory order book state (ticker → snapshot)
_orderbook: dict[str, dict] = {}
_cache_lock = threading.Lock()

# ── Full-depth order book (batch-64 item 4 / panels A4 + A17) ────────────────
#
# orderbook_snapshot and orderbook_delta messages have been arriving all
# along and were being discarded: update_orderbook_cache kept only the single
# most recent delta under `last_delta`, overwritten by the next one, and
# get_cached_book()'s docstring says so outright. A4's ladder and its
# edge-as-you-fill walk, and A17's counterfactual replay, all need depth
# applied to a real book and snapshotted over time. This is forward-only --
# depth that was not recorded cannot be recovered.
#
# Structure: ticker -> {"yes": {price: qty}, "no": {price: qty},
#                       "seq": int|None, "ts": iso, "valid": bool}
#
# `valid` is the gap guard. A delta is a SIGNED change to one level, not an
# absolute quantity, so a single missed message leaves the book permanently
# and silently wrong. On a sequence gap the book is marked invalid and
# get_cached_depth() returns None until the next full snapshot rebuilds it --
# a cold book is a correct answer, a drifted one is not.
_depth_books: dict[str, dict] = {}
_depth_lock = threading.Lock()

# Last DB snapshot time per ticker (monotonic). A write per delta would put
# SQLite on the WS hot path; this throttles to one row per ticker per
# interval. tracker._conn() opens a fresh connection per call in WAL mode, so
# writing from this background thread is safe once throttled.
_depth_last_persist: dict[str, float] = {}

# Expected next sequence number per SUBSCRIPTION id, and which tickers belong
# to each sid. Kalshi's seq counts per subscription, not per market, so a
# per-ticker contiguity check is wrong: with N tickers on one sid, each
# ticker's own seq jumps by ~N between its messages and every book would be
# invalidated on its first delta and never recover. A gap on a sid means the
# stream lost a message for SOME market on that sid and we cannot tell which,
# so every book under it is invalidated.
_depth_seq_by_sid: dict[object, int] = {}
_depth_sid_tickers: dict[object, set[str]] = {}

# Prices are dollars in (0, 1) per Kalshi's spec (e.g. "0.0800"). A level
# outside that range means the feed changed representation -- a cents-scaled
# price would key alongside dollar-scaled ones and sort ABOVE every real
# level, fabricating a best bid out of nothing. Invalidate rather than serve
# a book that still reads as depth but is nonsense.
_DEPTH_PRICE_MIN = 0.0
_DEPTH_PRICE_MAX = 1.0

# Depth snapshots are handed to a dedicated writer thread rather than written
# inline. update_orderbook_cache is called synchronously from inside
# `async for raw in ws:`, so it runs ON the event loop -- an inline
# sqlite3.connect + PRAGMA + INSERT + commit + close blocks message reading.
# The throttle bounds the steady state to one write per ticker per interval,
# but not the subscribe burst: _depth_last_persist starts empty, and cron
# subscribes every scanned ticker at once, so the first snapshot for each of
# hundreds of tickers would write immediately, back to back, with nothing
# yielding to the loop. A stalled loop stops reading messages, which risks a
# ping timeout and a dropped connection -- degrading get_cached_mid_price,
# the flash-crash breaker's preferred input, as a side effect of a
# write-only observation.
#
# Bounded queue, drop-newest on overflow: losing a depth snapshot is a
# tolerable cost, blocking the feed is not.
_DEPTH_QUEUE_MAX = 512
_depth_write_queue: queue.Queue = queue.Queue(maxsize=_DEPTH_QUEUE_MAX)
_depth_writer_thread: threading.Thread | None = None
_depth_writer_lock = threading.Lock()
_depth_dropped_writes = 0


def _depth_writer_loop() -> None:
    """Drain the depth-snapshot queue, writing each row to tracker.

    Daemon thread: a pending depth snapshot must never keep the process
    alive. Every failure is swallowed and logged -- this is a write-only
    observation and must never disturb the feed.
    """
    while True:
        item = _depth_write_queue.get()
        try:
            if item is None:  # shutdown sentinel
                return
            import tracker as _tracker

            _tracker.log_orderbook_depth(**item)
        except Exception as exc:
            _log.warning("depth snapshot write failed: %s", exc)
        finally:
            _depth_write_queue.task_done()


def _ensure_depth_writer() -> None:
    """Start the writer thread on first use, once per process."""
    global _depth_writer_thread
    with _depth_writer_lock:
        if _depth_writer_thread is not None and _depth_writer_thread.is_alive():
            return
        _depth_writer_thread = threading.Thread(
            target=_depth_writer_loop, name="depth-writer", daemon=True
        )
        _depth_writer_thread.start()


def prune_depth_books(keep: set[str] | None = None) -> int:
    """Drop depth state for tickers outside `keep` (None = drop everything).

    Weather tickers are date-scoped and `cmd_cron()` is called repeatedly for
    the lifetime of a `watch` process, so without this the module globals
    accumulate a book per ticker per day forever. Called from subscribe().
    Returns the number of tickers dropped.
    """
    with _depth_lock:
        current = set(_depth_books)
        drop = current if keep is None else current - keep
        for t in drop:
            _depth_books.pop(t, None)
            _depth_last_persist.pop(t, None)
        for sid, tickers in list(_depth_sid_tickers.items()):
            tickers -= drop
            if not tickers:
                _depth_sid_tickers.pop(sid, None)
                _depth_seq_by_sid.pop(sid, None)
    if drop:
        _log.debug("prune_depth_books: dropped %d ticker(s)", len(drop))
    return len(drop)


def _depth_snapshot_interval() -> float:
    """Seconds between persisted depth snapshots per ticker.

    Read per call rather than captured at import, so a long-running process
    picks up a changed env var -- the same reason update_orderbook_cache
    reads KALSHI_ENV per write. 0 or negative disables persistence entirely
    (the in-memory book still works).
    """
    raw = os.getenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "60")
    try:
        return float(raw)
    except (TypeError, ValueError):
        _log.warning("DEPTH_SNAPSHOT_INTERVAL_SECS=%r is not a number — using 60", raw)
        return 60.0


def _coerce_price(raw) -> float | None:
    """Return a price/quantity as a float, or None if it is not a usable number.

    Kalshi's March 2026 migration moved prices to dollar strings ("0.6500")
    while other fields remain integer cents, and this module's snapshot
    branch already float()s whatever arrives. Accept both rather than
    assuming one: a wrong assumption here produces a book keyed on two
    incompatible price scales, which still reads as depth but is nonsense.
    Rejects bool explicitly -- it is an int subclass, so True would silently
    become price 1.0.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _levels_to_map(levels) -> dict[float, int]:
    """Convert [[price, qty], ...] into {price: qty}, skipping malformed rows."""
    out: dict[float, int] = {}
    if not isinstance(levels, list | tuple):
        return out
    for lvl in levels:
        if not isinstance(lvl, list | tuple) or len(lvl) < 2:
            continue
        price = _coerce_price(lvl[0])
        qty = _coerce_price(lvl[1])
        if price is None or qty is None or qty <= 0:
            continue
        out[price] = int(qty)
    return out


def _map_to_levels(book_side: dict[float, int]) -> list[list]:
    """Render {price: qty} as [[price, qty], ...], best-bid-first.

    Both sides of a Kalshi book are BIDS (yes bids and no bids), so both are
    best-first sorted high-to-low -- matching parse_message's own
    "Kalshi sends yes levels sorted best-bid-first per API spec" note.
    """
    return [
        [p, q] for p, q in sorted(book_side.items(), key=lambda kv: -kv[0]) if q > 0
    ]


def _apply_orderbook_snapshot(ticker: str, data: dict) -> None:
    """Rebuild a ticker's depth book from a full snapshot.

    A snapshot is the only thing that can make a book valid again after a
    sequence gap, which is why it resets `valid`.

    An all-empty snapshot does NOT produce a valid book. That case is not
    hypothetical: reading the wrong payload field names yielded exactly this
    -- an empty book marked confidently valid, which subsequent deltas then
    built up from nothing (every removal a no-op, every addition a phantom
    level) with no gap warning and no way to tell afterwards. "A cold book is
    a correct answer, a drifted one is not" only holds if an empty snapshot
    counts as cold.
    """
    yes_map = _levels_to_map(data.get("yes_levels"))
    no_map = _levels_to_map(data.get("no_levels"))
    seq = data.get("seq")
    sid = data.get("sid")

    with _depth_lock:
        _depth_books[ticker] = {
            "yes": yes_map,
            "no": no_map,
            "seq": seq,
            "sid": sid,
            "ts": data.get("ts"),
            "valid": bool(yes_map or no_map),
        }
        if sid is not None:
            _depth_sid_tickers.setdefault(sid, set()).add(ticker)
        if isinstance(seq, int) and not isinstance(seq, bool):
            _depth_seq_by_sid[sid] = seq


def _apply_orderbook_delta(ticker: str, data: dict) -> None:
    """Apply one delta to a ticker's depth book.

    Kalshi's spec payload is {market_ticker, market_id, price_dollars,
    delta_fp, side}: `delta_fp` is a SIGNED change to the resting quantity at
    `price_dollars` on `side` (e.g. "-54.00" = 54 contracts removed), not a
    new absolute quantity. A level reaching zero is removed rather than kept
    at 0, so a depth walk never sees a hole.

    Two invariants, both chosen so the book is never confidently wrong:

    * The sequence cursor is keyed on `sid` (the subscription), not on the
      ticker, because that is what Kalshi counts. A gap invalidates every
      book on that subscription -- the lost message could have belonged to
      any market under it, and we cannot tell which.
    * A delta that arrives but cannot be applied -- unknown side, unparseable
      price or quantity, a price outside the (0, 1) dollar range -- also
      invalidates. We know the book changed and we know we failed to track
      it, so continuing to serve it would be serving a drifted book. The
      cursor still advances first, so the NEXT message is not additionally
      misreported as a gap.
    """
    seq = data.get("seq")
    if isinstance(seq, bool):  # bool is an int subclass
        seq = None
    sid = data.get("sid")

    with _depth_lock:
        # Cursor first, and unconditionally for any message carrying a seq --
        # including one we go on to reject -- so a rejected message costs one
        # honest invalidation rather than that plus a phantom gap afterwards.
        gapped = False
        if isinstance(seq, int):
            prev_seq = _depth_seq_by_sid.get(sid)
            _depth_seq_by_sid[sid] = seq
            gapped = isinstance(prev_seq, int) and seq != prev_seq + 1

        if gapped:
            affected = _depth_sid_tickers.get(sid) or {ticker}
            for t in affected:
                b = _depth_books.get(t)
                if b is not None:
                    b["valid"] = False
            _log.warning(
                "orderbook depth: sequence gap on sid=%s (%s -> %s) — "
                "invalidated %d book(s) until the next snapshot",
                sid,
                prev_seq,
                seq,
                len(affected),
            )
            return

        book = _depth_books.get(ticker)
        if book is None or not book.get("valid"):
            return

        def _reject(reason: str, *args) -> None:
            book["valid"] = False
            _log.warning(
                "orderbook depth: %s — unapplicable delta for %s; book "
                "invalidated until the next snapshot",
                reason % args if args else reason,
                ticker,
            )

        inner = data.get("delta")
        if not isinstance(inner, dict):
            _reject("payload is not an object")
            return

        side = inner.get("side")
        if side not in ("yes", "no"):
            _reject("unknown side %r", side)
            return

        # Spec names first (`price_dollars` / `delta_fp`); the bare
        # `price`/`delta` names do not appear in Kalshi's published schema
        # and are accepted only so an older capture still parses. Preferring
        # the spec names is load-bearing: reading only `delta` discarded
        # every real delta silently, which left the book frozen at its
        # snapshot and then invalidated on the following message.
        raw_price = inner.get("price_dollars")
        if raw_price is None:
            raw_price = inner.get("price")
        raw_change = inner.get("delta_fp")
        if raw_change is None:
            raw_change = inner.get("delta")

        price = _coerce_price(raw_price)
        change = _coerce_price(raw_change)
        if price is None or change is None:
            _reject("unparseable price %r / delta %r", raw_price, raw_change)
            return
        if not _DEPTH_PRICE_MIN < price < _DEPTH_PRICE_MAX:
            _reject("price %r outside (0, 1) — feed scale changed", price)
            return

        side_map = book[side]
        new_qty = int(side_map.get(price, 0) + change)
        # Evict an exhausted level rather than keeping it at 0. _map_to_levels
        # would filter a 0 out of the rendered book either way, so this is
        # about the book itself: retaining every price level ever touched on
        # every subscribed ticker is a slow leak in a long-lived WS process.
        if new_qty > 0:
            side_map[price] = new_qty
        else:
            side_map.pop(price, None)

        # Recorded as metadata only -- the gap cursor lives in
        # _depth_seq_by_sid, keyed by subscription.
        if seq is not None:
            book["seq"] = seq
        if data.get("ts"):
            book["ts"] = data["ts"]


def get_cached_depth(ticker: str) -> dict | None:
    """Return the full-depth order book for a ticker, or None.

    Shape: {"yes": [[price, qty], ...], "no": [...], "seq": int|None,
    "ts": iso}, both sides sorted best-bid-first.

    Returns None when no snapshot has been seen, when a sequence gap has
    invalidated the book, or when the newest message is older than
    WS_CACHE_TTL_SECS. A caller needing depth for a cold or stale ticker
    should fall back to kalshi_client.get_orderbook(), the on-demand REST
    fetch.

    Deliberately a SEPARATE accessor from get_cached_book(), whose return
    shape is unchanged: the reprice/chase path reads top-of-book only, its
    docstring's reasoning that "this bot's order sizes don't require walking
    multiple depth levels" still holds, and adding depth must not move what
    that path sees.
    """
    with _depth_lock:
        book = _depth_books.get(ticker)
        if book is None or not book.get("valid"):
            return None
        if not _is_fresh(book):
            return None
        return {
            "yes": _map_to_levels(book["yes"]),
            "no": _map_to_levels(book["no"]),
            "seq": book.get("seq"),
            "ts": book.get("ts"),
        }


def _maybe_persist_depth(ticker: str) -> bool:
    """Throttled hand-off of the current depth book to the writer thread.

    Returns True when a snapshot was ENQUEUED (not when it reached the DB --
    the write happens off the event loop, see _depth_writer_loop). Every
    failure is swallowed: this is a write-only observation for A4/A17 and
    must never disturb the feed.
    """
    interval = _depth_snapshot_interval()
    if interval <= 0:
        return False

    now = time.monotonic()
    with _depth_lock:
        last = _depth_last_persist.get(ticker)
        if last is not None and (now - last) < interval:
            return False
        book = _depth_books.get(ticker)
        if book is None or not book.get("valid"):
            return False
        yes_levels = _map_to_levels(book["yes"])
        no_levels = _map_to_levels(book["no"])
        if not yes_levels and not no_levels:
            # Checked BEFORE reserving the slot: an empty book has nothing
            # worth writing, and burning the slot here would block the first
            # real snapshot for a whole interval.
            return False
        snapshot_at = book.get("ts")
        # Reserve the slot before writing, still inside the lock, so a slow
        # or failing write can't let a second caller straight through.
        _depth_last_persist[ticker] = now

    global _depth_dropped_writes
    _ensure_depth_writer()
    try:
        _depth_write_queue.put_nowait(
            {
                "ticker": ticker,
                "yes_levels": yes_levels,
                "no_levels": no_levels,
                # Read here, at capture time, not in the writer thread: the
                # row's env must describe the host that actually produced the
                # book, and the queue can lag.
                "env": os.getenv("KALSHI_ENV", "demo"),
                "snapshot_at": snapshot_at,
            }
        )
        return True
    except queue.Full:
        _depth_dropped_writes += 1
        if _depth_dropped_writes % 100 == 1:
            _log.warning(
                "depth snapshot queue full — dropped %d snapshot(s) so far; "
                "the DB writer is not keeping up",
                _depth_dropped_writes,
            )
        return False


_ws_alive: bool = False
_ws_last_message_ts: float = 0.0
_ws_state_lock = threading.Lock()


def _set_ws_alive(alive: bool) -> None:
    global _ws_alive
    with _ws_state_lock:
        _ws_alive = alive


def _record_ws_message() -> None:
    global _ws_last_message_ts
    with _ws_state_lock:
        _ws_last_message_ts = __import__("time").monotonic()


def get_ws_health() -> dict:
    """Return WS thread health info for monitoring."""
    import time

    from utils import WS_CACHE_TTL_SECS

    with _ws_state_lock:
        alive = _ws_alive
        last_msg = _ws_last_message_ts
    idle_secs = time.monotonic() - last_msg if last_msg > 0 else None
    return {
        "alive": alive,
        "idle_secs": round(idle_secs, 1) if idle_secs is not None else None,
        "stale": idle_secs is not None and idle_secs > WS_CACHE_TTL_SECS,
    }


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

    # batch-64 item 4: Kalshi stamps every orderbook_delta/snapshot with a
    # sequence number and a subscription id at the TOP level of the envelope
    # (beside "type"/"msg"), which this parser previously dropped. A depth
    # book rebuilt from deltas is only trustworthy if gaps are detectable --
    # one missed delta silently corrupts every level after it, with no
    # symptom.
    #
    # `seq` counts per SUBSCRIPTION (per `sid`), not per market: the
    # published AsyncAPI examples show sid=2/seq=2 for a snapshot and
    # sid=2/seq=3 for the following delta, and cron.py subscribes every
    # scanned ticker under a single subscribe message, so one sid spans
    # hundreds of markets. Both are carried through; the gap check keys on
    # sid (see _apply_orderbook_delta). None when absent.
    seq = msg.get("seq")
    sid = msg.get("sid")

    ticker = inner.get("market_ticker")
    if not ticker:
        return None

    if msg_type == "orderbook_snapshot":
        # Kalshi's published AsyncAPI spec names these `yes_dollars_fp` /
        # `no_dollars_fp`, e.g. [["0.0800", "300.00"], ["0.2200", "333.00"]]
        # -- dollar-string prices with fixed-point quantities. The bare
        # `yes`/`no` names this branch previously read do not appear in the
        # spec at all, which is why best_yes_bid/best_no_bid below have been
        # None in production since this was written (nothing consumed them,
        # so it went unnoticed). Both names are accepted: the new one first,
        # the legacy one as a fallback, so a capture in either shape works.
        yes_levels = inner.get("yes_dollars_fp") or inner.get("yes") or []
        no_levels = inner.get("no_dollars_fp") or inner.get("no") or []
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
            "seq": seq,
            "sid": sid,
            "ts": datetime.now(UTC).isoformat(),
        }

    elif msg_type == "orderbook_delta":
        return {
            "type": "orderbook_delta",
            "ticker": ticker,
            "delta": inner,
            "seq": seq,
            "sid": sid,
            "ts": datetime.now(UTC).isoformat(),
        }

    elif msg_type == "ticker":
        # Kalshi's ticker channel sends yes_bid_dollars / yes_ask_dollars /
        # price_dollars -- dollar strings, matching the _dollars_fp
        # convention the orderbook_snapshot branch above already handles.
        # The bare yes_bid/yes_ask/last_price names this branch read do NOT
        # appear on the wire: captured live 2026-08-28 across 32 ticker
        # messages from 30 real markets, yes_bid/yes_ask/last_price were
        # present in 0 of 32 while the _dollars names were present in 32 of
        # 32. So every parsed ticker came out {yes_bid: 0.0, yes_ask: 0.0,
        # mid_price: 0.0} against a real 0.47/0.48 book.
        #
        # That silently disabled every downstream consumer, each of which
        # guards on `> 0`: update_orderbook_cache never called
        # flash_crash_cb.check(), order_executor's breaker fell through to
        # the REST mid, and _get_current_book rejected the cache for
        # reprice/chase. Legacy names kept as a fallback so an older capture
        # or replay still parses.
        yes_bid_str = (
            inner.get("yes_bid_dollars")
            or inner.get("yes_bid")
            or inner.get("yes_dollars_fp")
            or "0"
        )
        yes_ask_str = inner.get("yes_ask_dollars") or inner.get("yes_ask") or "0"
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
            "last_price": float(
                inner.get("price_dollars") or inner.get("last_price") or 0
            ),
            "ts": datetime.now(UTC).isoformat(),
        }

    return None


# ── Order book cache ──────────────────────────────────────────────────────────


# Disk-cache write throttle. The in-memory _orderbook is updated on EVERY
# message and stays exact -- this bounds only how often that state is
# serialised to disk for OTHER processes to read. Consumers gate on
# WS_CACHE_TTL_SECS (900s), so a couple of seconds of lag is immaterial;
# a starved event loop is not.
_cache_disk_lock = threading.Lock()
_cache_last_disk_write = 0.0


def _cache_disk_interval() -> float:
    """Seconds between disk serialisations of the in-memory book cache.

    Read per call, not captured at import -- the same reason
    _depth_snapshot_interval() gives: a long-running process must pick up a
    changed env var. 0 or negative disables the throttle entirely (every
    message writes, the pre-2026-08-28 behaviour), which is what the tests
    that assert on file contents after a single message need.
    """
    raw = os.getenv("WS_CACHE_DISK_INTERVAL_SECS", "2.0")
    try:
        return float(raw)
    except (TypeError, ValueError):
        _log.warning("WS_CACHE_DISK_INTERVAL_SECS=%r is not a number — using 2.0", raw)
        return 2.0


def _maybe_write_cache_to_disk(force: bool = False) -> bool:
    """Serialise the in-memory book cache to disk, at most once per interval.

    Returns True when a write happened. `force=True` bypasses the throttle --
    used on shutdown so the final state is not left unwritten.

    Writes EVERY ticker in _orderbook, not just the one that triggered this
    call: with a throttle in place, per-ticker writes would drop whichever
    tickers were updated inside the throttle window. The file is still
    read-merged first so entries written by another process are preserved,
    which is the pre-throttle behaviour.
    """
    global _cache_last_disk_write
    import safe_io

    now = time.monotonic()
    with _cache_disk_lock:
        if not force and (now - _cache_last_disk_write) < _cache_disk_interval():
            return False
        # Reserve the slot before writing, inside the lock, so a slow write
        # cannot let a second caller straight through behind it.
        _cache_last_disk_write = now

    try:
        with _cache_lock:
            snapshot = dict(_orderbook)
        cache = {}
        if _CACHE_PATH.exists():
            cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        cache.update(snapshot)
        cache["_updated_at"] = datetime.now(UTC).isoformat()
        # Opus review (batch-58, L2): stamp which environment produced these
        # snapshots. The cache file is a single env-agnostic path keyed only
        # by ticker, so without this an operator who runs prod, stops,
        # switches KALSHI_ENV=demo and starts the L6585 demo smoke test
        # inside WS_CACHE_TTL_SECS (900s) would have _get_fresh_ticker_entry's
        # disk fallback serve the still-fresh PROD entries -- feeding prod
        # prices to reprice/chase and the flash-crash breaker exactly as
        # before item 2's fix, i.e. defeating the fix in the one scenario it
        # was written for.
        cache["_env"] = os.getenv("KALSHI_ENV", "demo")
        _CACHE_PATH.parent.mkdir(exist_ok=True)
        # emergency_copy=False: this is the disposable/re-fetchable JSON case
        # safe_io's own docstring names. With the default, a failed write
        # leaves an emergency copy that cron.check_emergency_copies() pages on
        # every cycle until someone deletes it by hand -- for a cache the next
        # connect rebuilds from scratch.
        safe_io.atomic_write_json(cache, _CACHE_PATH, emergency_copy=False)
        return True
    except Exception as exc:
        _log.warning("update_orderbook_cache: disk write failed: %s", exc)
        return False


def prune_orderbook_cache(keep: set[str] | None = None) -> int:
    """Drop in-memory ticker cache entries outside `keep`.

    The exact sibling of prune_depth_books, and needed for the same reason it
    gives: cmd_cron() runs repeatedly for the lifetime of a `watch`/`loop`
    process while these module globals survive, and weather tickers are
    date-scoped, so _orderbook otherwise accumulates an entry per ticker per
    day forever. That is worse here than for depth, because EVERY entry is
    re-serialised on every disk write -- unbounded growth turns into
    unbounded write cost (~600 new tickers/day compounds into a multi-MB
    rewrite within a week).
    """
    with _cache_lock:
        current = {t for t in _orderbook if not t.startswith("_")}
        drop = current if keep is None else current - keep
        for t in drop:
            _orderbook.pop(t, None)
    if drop:
        _log.debug("prune_orderbook_cache: dropped %d ticker(s)", len(drop))
    return len(drop)


def update_orderbook_cache(ticker: str, data: dict) -> None:
    """Update the in-memory cache for a ticker; disk write is throttled.

    See _maybe_write_cache_to_disk for why the disk half is no longer inline.
    """
    _msg_type = data.get("type")

    with _cache_lock:
        if _msg_type == "orderbook_delta":
            # Store the raw delta. Deliberately do NOT touch `ts` here:
            # get_cached_mid_price()'s freshness check (_is_fresh) reads this
            # entry's `ts` to gate mid_price staleness, and a delta doesn't
            # actually refresh mid_price -- bumping `ts` would make a frozen
            # mid_price look "fresh" indefinitely as long as deltas keep
            # arriving, defeating the staleness gate on a safety-critical
            # input (get_cached_mid_price feeds order_executor.py's
            # flash-crash circuit breaker check).
            #
            # batch-64 item 4: the delta is ALSO applied to the depth book
            # below, outside this lock. `last_delta` stays exactly as it was
            # -- the depth book is a separate structure with its own lock, so
            # nothing that reads this entry changes shape.
            existing = _orderbook.get(ticker, {})
            existing["last_delta"] = data["delta"]
            _orderbook[ticker] = existing
            merged = existing
        elif _msg_type == "orderbook_snapshot":
            # batch-64 item 4: MERGE rather than replace. This branch used to
            # fall into the wholesale `_orderbook[ticker] = data` below, so a
            # snapshot -- which carries no mid_price/yes_bid/yes_ask, only
            # levels -- wiped the fields a "ticker" tick had put there, and
            # get_cached_mid_price()/get_cached_book() went None until the
            # next tick arrived. That silently withheld readings from the
            # flash-crash breaker. Snapshots arrive on the orderbook_delta
            # channel (Kalshi sends one before its deltas), so this fired on
            # every (re)subscribe, not rarely.
            #
            # `ts` is preserved for the same reason the delta branch above
            # preserves it: a snapshot does not refresh mid_price either, so
            # it must not make a stale mid_price look fresh.
            #
            # Built as a NEW dict and rebound atomically rather than mutated
            # in place: _get_fresh_ticker_entry takes _cache_lock only to
            # fetch the reference and then evaluates _is_fresh() on the live
            # object outside the lock, so an in-place `update()` exposes a
            # window where the snapshot's fresh ts is already written but the
            # old mid_price has not yet been restored -- a stale mid_price
            # reading as fresh, on the input feeding the flash-crash breaker.
            # The pre-existing wholesale rebind had no such window and this
            # keeps it that way.
            existing = _orderbook.get(ticker, {})
            merged = {**existing, **data}
            _preserved_ts = existing.get("ts")
            if _preserved_ts is not None:
                merged["ts"] = _preserved_ts
            _orderbook[ticker] = merged
        else:
            _orderbook[ticker] = data
            merged = data
    # Disk write is THROTTLED and happens outside _cache_lock. It used to run
    # inline here on every single message: read the whole file, json.loads it,
    # json.dumps it back, temp-file + fsync + rename -- synchronously, on the
    # asyncio event loop, while holding _cache_lock.
    #
    # That is survivable at 3 tickers and fatal at real scale. Measured live
    # against prod at 596 tickers (the current KNOWN_WEATHER_SERIES count),
    # offered load ~300 msg/s: event-loop lag reached 28 SECONDS and the
    # connection died with "keepalive ping timeout", after which _ws_listener
    # sleeps 10s, reconnects, and replays the whole 596-message snapshot burst
    # -- forever. Isolated benchmark: 19 ms/message at 200 tickers, 52 ms at
    # 700, plus ~35-50 MB/s of sustained rewrite.
    #
    # This module had already solved exactly this for the DB write (see the
    # depth-writer comment above: "A stalled loop stops reading messages,
    # which risks a ping timeout and a dropped connection") and left the far
    # more expensive JSON write inline.
    _maybe_write_cache_to_disk()

    # Real-time flash-crash detection: only a "ticker"-type message carries a
    # genuine mid_price (see the comment on the delta branch above) -- feed it
    # to the breaker on every live tick, independent of scan cadence. This is
    # what makes FlashCrashCB able to actually observe a sub-5-minute move;
    # order_executor.py's own per-opportunity check() call remains as a
    # fallback for when this WS feed is unavailable or stale. Deliberately
    # outside the _cache_lock above -- flash_crash_cb guards its own state
    # with its own lock and doesn't need this one.
    if _msg_type == "ticker":
        mid = data.get("mid_price")
        if mid and mid > 0:
            try:
                flash_crash_cb.check(ticker, float(mid))
            except Exception as exc:
                _log.warning(
                    "update_orderbook_cache: flash-crash check failed: %s", exc
                )

    # batch-64 item 4: maintain the full-depth book and snapshot it. Kept
    # outside _cache_lock -- _depth_books has its own lock, and the throttled
    # DB write must not be holding the cache lock that every reader of
    # get_cached_mid_price()/get_cached_book() contends for. Fully guarded:
    # this is a write-only observation for A4/A17 and must never be able to
    # break the feed or change what any existing consumer reads.
    try:
        if _msg_type == "orderbook_snapshot":
            _apply_orderbook_snapshot(ticker, data)
        elif _msg_type == "orderbook_delta":
            _apply_orderbook_delta(ticker, data)
        if _msg_type in ("orderbook_snapshot", "orderbook_delta"):
            _maybe_persist_depth(ticker)
    except Exception as exc:
        _log.warning("update_orderbook_cache: depth book update failed: %s", exc)


def read_orderbook_cache() -> dict:
    """Read the current order book cache from disk."""
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Expected whenever no WebSocket connection has ever run (every cron
        # scan, or the first call of a fresh `watch` session) — not an error,
        # but still logged at debug so the file's absence doesn't just
        # disappear with zero trace if it's ever worth checking.
        _log.debug("read_orderbook_cache: cache file missing at %s", _CACHE_PATH)
        return {}
    except Exception as exc:
        _log.warning("read_orderbook_cache: failed to read cache: %s", exc)
        return {}


def _is_fresh(entry: dict) -> bool:
    from utils import WS_CACHE_TTL_SECS

    ts_str = entry.get("ts")
    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(ts_str)
        age = (datetime.now(UTC) - ts).total_seconds()
        return age < WS_CACHE_TTL_SECS
    except (ValueError, TypeError):
        return False


def _get_fresh_ticker_entry(ticker: str) -> dict | None:
    """Return the cached "ticker"-type message for a ticker if fresh, else None.

    Shared by get_cached_mid_price() and get_cached_book() — both read the
    same underlying cache entry, just different fields off it. Only a
    "ticker"-type message ever sets mid_price/yes_bid/yes_ask (see
    parse_message()'s ticker branch); an "orderbook_delta" entry has neither.
    """
    # Try in-memory first (faster than disk read)
    with _cache_lock:
        entry = _orderbook.get(ticker)
    if entry and _is_fresh(entry) and entry.get("mid_price") is not None:
        return entry

    # Fall back to disk cache.
    #
    # Opus review (batch-58, L2): a cache written under a DIFFERENT
    # KALSHI_ENV is treated as stale regardless of its age -- see
    # update_orderbook_cache's own `_env` comment. Only the disk half needs
    # this; the in-memory half above cannot outlive the process that filled
    # it, and the WS host is now frozen for a listener's lifetime. A cache
    # predating this stamp has no `_env` key and is also treated as stale,
    # which self-heals on the first write.
    cache = read_orderbook_cache()
    if cache.get("_env") != os.getenv("KALSHI_ENV", "demo"):
        return None
    entry = cache.get(ticker)
    if entry and _is_fresh(entry) and entry.get("mid_price") is not None:
        return entry
    return None


def get_cached_mid_price(ticker: str) -> float | None:
    """Return the cached mid-price for a ticker, or None if not cached or stale."""
    entry = _get_fresh_ticker_entry(ticker)
    return entry.get("mid_price") if entry else None


def get_cached_book(ticker: str) -> dict | None:
    """Return {"yes_bid", "yes_ask", "mid_price"} for a ticker from the live
    WS ticker-tick cache, or None if not cached or stale (see WS_CACHE_TTL_SECS).

    This is top-of-book only (best bid/ask from ticker ticks), not full
    depth — orderbook_delta messages are stored but not applied to a usable
    depth structure (see update_orderbook_cache's comment). Top-of-book is
    what reprice/chase decisions need; this bot's order sizes don't require
    walking multiple depth levels.
    """
    entry = _get_fresh_ticker_entry(ticker)
    if not entry:
        return None
    return {
        "yes_bid": entry.get("yes_bid"),
        "yes_ask": entry.get("yes_ask"),
        "mid_price": entry.get("mid_price"),
    }


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


async def _ws_listener(
    api_key: str, private_key_pem: str | bytes, tickers: list[str]
) -> None:
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

    # Opus review (batch-58, M3): resolved ONCE, before the reconnect loop,
    # not per connect attempt. The REST client's base_url is frozen at
    # build_client() for the life of the process, and this feed's snapshots
    # land in the same data/orderbook_cache.json that order_executor's
    # reprice/chase logic and flash-crash breaker read -- so a WS thread that
    # re-read KALSHI_ENV on every reconnect could silently start writing
    # demo book data into the cache a still-prod REST client is trading
    # against (or vice versa). Freezing it here makes the two agree for the
    # whole run, which is exactly the invariant main.py's own
    # KALSHI_ENV snapshot/restore protects on the REST side.
    ws_url = _ws_url()
    _log.info("kalshi_ws: using %s for this listener's lifetime", ws_url)

    try:
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

                async with websockets.connect(ws_url, additional_headers=headers) as ws:
                    _log.info("kalshi_ws: connected to %s", ws_url)
                    _set_ws_alive(True)

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
                                _record_ws_message()
                        except Exception as exc:
                            _log.warning("kalshi_ws: parse error: %s", exc)

                # AUD batch-23 #4: the `async with`/`async for` above exited
                # WITHOUT raising -- a clean close (e.g. a rejected auth or
                # subscribe, or the server ending the connection with a
                # valid close frame). This path is distinct from the
                # `except Exception` branch below; without clearing
                # _ws_alive and backing off here too, a clean-close reconnect
                # thrashes the connection at full speed while
                # get_ws_health() keeps reporting alive=True the entire time.
                _set_ws_alive(False)
                _log.warning(
                    "kalshi_ws: connection closed cleanly — reconnecting in 10s"
                )
                await asyncio.sleep(10)

            except Exception as exc:
                _set_ws_alive(False)
                _log.warning(
                    "kalshi_ws: connection error: %s — reconnecting in 10s", exc
                )
                await asyncio.sleep(10)
    finally:
        _set_ws_alive(False)


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

    def __init__(self, api_key: str, private_key_pem: str | bytes) -> None:
        # str | bytes because _ws_listener already accepts either (it encodes
        # a str before load_pem_private_key), and cron reads the key file with
        # read_bytes -- which is what load_pem_private_key wants and avoids a
        # locale-dependent decode. The annotation was narrower than the real
        # contract.
        self._api_key = api_key
        self._private_key_pem = private_key_pem
        self._tickers: list[str] = []
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
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
        # batch-64 item 4: drop depth state for tickers this listener is not
        # subscribing to. cron.py calls cmd_cron() repeatedly for the lifetime
        # of a `watch` process, constructing a fresh KalshiWebSocket each
        # cycle while these module globals survive — and weather tickers are
        # date-scoped, so without this a long-lived process accumulates a
        # book per ticker per day forever. Done at start(), not subscribe(),
        # because subscribe() may be called several times before the socket
        # opens and only the final set is the real subscription.
        try:
            prune_depth_books(keep=set(self._tickers))
            prune_orderbook_cache(keep=set(self._tickers))
        except Exception as exc:  # never block the listener starting
            _log.debug("prune on start skipped: %s", exc)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="KalshiWS")
        self._thread.start()
        _log.info("kalshi_ws: background thread started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the WebSocket listener.

        Cancels the running task (rather than just stopping the loop) so the
        `async with websockets.connect(...)` context manager's cleanup
        actually runs -- closing the connection with a proper close frame
        instead of abruptly abandoning it -- and so _ws_listener's own
        `finally: _set_ws_alive(False)` executes before the thread exits.
        """
        self._running = False
        if self._loop and not self._loop.is_closed():
            if self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)
            else:
                # Narrow window: stop() called between _run() setting
                # self._loop and it creating self._task a few lines later.
                # Fall back to stopping the loop directly so this doesn't
                # regress to "stop() does nothing" for that edge case.
                self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                # WARNING, not DEBUG: cmd_loop calls cmd_cron in-process every
                # few hours, so a thread that outlives its stop() is still
                # subscribed when the NEXT cycle starts another one, and the
                # subscriptions stack. Silent here meant the leak was
                # invisible.
                _log.warning(
                    "kalshi_ws: listener thread did not exit within %.1fs — "
                    "it stays subscribed and a later cycle will start another",
                    timeout,
                )
        # Final flush: the throttled writer may hold state that never reached
        # disk, and this is the last chance before the process or cycle ends.
        _maybe_write_cache_to_disk(force=True)
        _log.info("kalshi_ws: stopped")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._task = self._loop.create_task(
                _ws_listener(self._api_key, self._private_key_pem, self._tickers)
            )
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass  # expected when stop() cancels the task
        except Exception as exc:
            _log.error("kalshi_ws: thread error: %s", exc)
        finally:
            self._loop.close()
