"""
Execution log — SQLite-backed audit trail of every live order attempt.
Prevents duplicate orders and provides a full history of what was sent to Kalshi.

Usage:
    from execution_log import log_order, get_recent_orders, was_recently_ordered
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading as _el_threading
import time as _el_time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from paths import EXECUTION_LOG_DB_PATH
from utils import sql_normalize_iso_column

_log = logging.getLogger(__name__)

DB_PATH = EXECUTION_LOG_DB_PATH
DB_PATH.parent.mkdir(exist_ok=True)


# Date-keyed sentinel: set when add_live_loss() can't persist a cost/gain and
# can't even re-read the last known total (DB genuinely stuck, not just a
# transient lock — sqlite3.connect already retries internally for 30s).
# While set for today, get_today_live_loss() fails closed (returns inf,
# tripping every daily_loss_limit gate) instead of silently under-reporting.
# Cleared automatically the next time a write succeeds.
# NB: derived from DB_PATH at call time (not frozen at import) since tests
# reassign execution_log.DB_PATH per-test to isolate against a temp DB.
def _degraded_flag_path() -> Path:
    return DB_PATH.parent / "execution_log_degraded.json"


_initialized = False
# L-7: protect the initialization flag against concurrent first-call races
_init_lock = _el_threading.Lock()
_append_lock = _el_threading.Lock()  # WA-9: serialize concurrent JSONL appends

# backlog.txt "execution_log.py's SWALLOWED-ALTER MIGRATIONS vs tracker.py's
# VERSIONED IDIOM" -- ported to tracker.py's PRAGMA user_version cursor
# instead of re-attempting a flat ALTER list on every init inside a bare
# `except sqlite3.OperationalError: pass`. The base CREATE TABLE below now
# only has the columns that predate this list; every column added since is
# expressed as its own migration, matching tracker.py's convention of never
# touching the base CREATE TABLE again once versioning exists.
_SCHEMA_VERSION = 19  # increment when _MIGRATIONS list grows

_MIGRATIONS = [
    "ALTER TABLE orders ADD COLUMN fill_quantity INTEGER",  # v1
    "ALTER TABLE orders ADD COLUMN error_code TEXT",  # v2
    "ALTER TABLE orders ADD COLUMN error_type TEXT",  # v3
    "ALTER TABLE orders ADD COLUMN forecast_cycle TEXT",  # v4
    "ALTER TABLE orders ADD COLUMN live INTEGER DEFAULT 0",  # v5
    "ALTER TABLE orders ADD COLUMN settled_at TEXT",  # v6
    "ALTER TABLE orders ADD COLUMN outcome_yes INTEGER",  # v7
    "ALTER TABLE orders ADD COLUMN pnl REAL",  # v8
    "ALTER TABLE orders ADD COLUMN close_time TEXT",  # v9
    "ALTER TABLE orders ADD COLUMN filled_at TEXT",  # v10
    "ALTER TABLE orders ADD COLUMN market_mid_at_fill REAL",  # v11
    "ALTER TABLE orders ADD COLUMN replaces_order_id INTEGER",  # v12
    "ALTER TABLE orders ADD COLUMN peak_profit_pct REAL",  # v13
    "ALTER TABLE orders ADD COLUMN exit_reason TEXT",  # v14
    "ALTER TABLE orders ADD COLUMN exit_price REAL",  # v15
    "ALTER TABLE orders ADD COLUMN entry_prob REAL",  # v16
    "ALTER TABLE orders ADD COLUMN closes_position_id INTEGER",  # v17
    "ALTER TABLE orders ADD COLUMN exit_claimed_at TEXT",  # v18
    # batch-89: entry_prob's PRE-section-9c twin. Appended, never inserted --
    # this list is positional (version = index + 1), so placing it next to
    # entry_prob at v16 would renumber everything after it and every DB
    # already past that version would skip the new column forever.
    "ALTER TABLE orders ADD COLUMN entry_prob_precal REAL",  # v19
]


def _run_migrations(con: sqlite3.Connection) -> None:
    """Apply any pending schema migrations and advance PRAGMA user_version.

    Mirrors tracker.py's _run_migrations: a genuine OperationalError (locked
    DB, disk error) on a needed ALTER is distinguished from "column already
    exists" by inspecting the error message, instead of swallowing both
    alike -- the former now propagates instead of silently leaving the
    column missing.
    """
    current = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(_MIGRATIONS):
        version = i + 1
        if version <= current:
            continue
        try:
            con.execute(sql)
            # Write user_version immediately after each migration so a crash
            # between steps leaves the version accurate rather than at v0.
            con.execute(f"PRAGMA user_version={version}")
            _log.info("execution_log: applied migration v%d", version)
        except sqlite3.OperationalError as e:
            err_str = str(e).lower()
            if "duplicate column" in err_str or "already exists" in err_str:
                # Migration already applied (e.g. a pre-versioning DB that
                # already has every column) -- still advance the cursor.
                con.execute(f"PRAGMA user_version={version}")
                _log.debug(
                    "execution_log: migration v%d already applied: %s", version, e
                )
            else:
                raise
    con.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """AUD-0048: every one of this module's ~30 `with _conn() as con:` call
    sites relied on sqlite3.Connection's own context-manager protocol, which
    only commits/rolls back the transaction on exit -- it does NOT close the
    connection, and none of those call sites ever called con.close(). Wrapping
    _conn() itself in a generator-based context manager fixes every call site
    at once (none of them change): `with con:` below still gives the exact
    same commit-on-success/rollback-on-exception behavior every caller
    already depends on, and the outer try/finally now also closes the
    connection once that block exits -- including when commit() itself
    raises.
    """
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    try:
        with con:
            yield con
    finally:
        con.close()


def init_log() -> None:
    global _initialized
    if _initialized:
        return
    with (
        _init_lock
    ):  # L-7: hold the lock for the entire init body (double-checked locking)
        if (
            _initialized
        ):  # re-check inside lock — another thread may have finished first
            return
        with _conn() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker         TEXT    NOT NULL,
                side           TEXT    NOT NULL,   -- "yes" or "no"
                quantity       INTEGER NOT NULL,
                price          REAL    NOT NULL,
                order_type     TEXT,              -- "market" or "limit"
                status         TEXT,              -- "sent", "pending", "filled", "failed", "canceled", "amended", "unknown" (AUD-0007: placement outcome ambiguous -- see kalshi_client.OrderStatusUnknownError), "unresolved" (batch-58 item 5: an 'unknown' row that stayed unresolvable past _UNRESOLVED_AGE_MINUTES -- terminal, operator-actionable, see park_unresolved_order)
                response       TEXT,              -- JSON-encoded API response
                error          TEXT,              -- error message if failed
                placed_at      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_orders_ticker    ON orders(ticker, placed_at);
            CREATE INDEX IF NOT EXISTS idx_orders_status    ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_orders_placed_at ON orders(placed_at);

            CREATE TABLE IF NOT EXISTS daily_live_loss (
                date       TEXT PRIMARY KEY,
                total      REAL NOT NULL DEFAULT 0.0,
                updated_at TEXT NOT NULL
            );

            -- Batch-49 item 2: queue-position observations (read-only
            -- fill-quality instrumentation, NOT wired into any reprice/
            -- chase decision -- see kalshi_client.get_order_queue_position's
            -- docstring). A genuine time series, not a single snapshot per
            -- order -- one row per observation (placement, or each poll
            -- pass while the order is still resting), so this is a new
            -- table rather than a column on `orders` (which has exactly one
            -- row per order attempt).
            CREATE TABLE IF NOT EXISTS queue_positions (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                order_row_id       INTEGER,   -- orders.id, if resolvable at log time
                exchange_order_id  TEXT    NOT NULL,
                ticker             TEXT    NOT NULL,
                queue_position     REAL,      -- NULL if the API omitted/couldn't parse it
                source             TEXT    NOT NULL,   -- "placement" or "poll"
                observed_at        TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_queue_positions_order
                ON queue_positions(exchange_order_id, observed_at);
            """)
        with _conn() as con:
            _run_migrations(con)
        _initialized = True


def log_order(
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    order_type: str = "limit",
    status: str = "sent",
    response: dict | None = None,
    error: str | None = None,
    fill_quantity: int | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
    forecast_cycle: str | None = None,
    live: bool = False,
    close_time: str | None = None,
    replaces_order_id: int | None = None,
    entry_prob: float | None = None,
    entry_prob_precal: float | None = None,
    closes_position_id: int | None = None,
) -> int:
    """
    Record a live order attempt. Returns the new row ID.
    Call with status='sent' before placing, then update with log_order_result().

    replaces_order_id: id of the order row this one cancel-replaced (reprice
    or taker-cross), if any — links the chain for fill-latency/price-drift
    analysis. None for a fresh (non-reprice) placement.

    entry_prob: analyze_trade()'s forecast_prob at placement time, used by
    the live model-exit check to detect a meaningful forecast reversal
    against the held position (mirrors paper.py's place_paper_order
    entry_prob field). None for a replacement/reprice order — the position's
    entry_prob was already captured on the original placement it replaces.

    entry_prob_precal: the same probability BEFORE section 9c's analysis
    calibration, so _check_live_model_exits can compare entry against current
    on one calibration basis rather than measuring the calibration's own
    re-basing as a forecast move. Follows entry_prob exactly: same source
    (analyze_trade's result), same None-on-reprice rule.

    closes_position_id: id of the OPEN POSITION row (an earlier entry order)
    this order was placed to close, if any -- set only by
    order_executor._exit_live_position for its protective stop-loss/
    breakeven/model-exit SELL orders. Without this, a filled exit order's
    own row (live=1, status='filled', settled_at still NULL on itself) is
    indistinguishable from a genuine new entry fill and would be
    misidentified as a brand-new open position by
    get_filled_unsettled_live_orders() on the very next call -- this field
    exists solely so that query can exclude it. None for every other order
    (entries, reprices, taker-crosses all open or replace a position, they
    never close one).
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO orders
              (ticker, side, quantity, price, order_type, status, response, error,
               placed_at, fill_quantity, error_code, error_type, forecast_cycle, live,
               close_time, replaces_order_id, entry_prob, entry_prob_precal,
               closes_position_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                side,
                quantity,
                price,
                order_type,
                status,
                json.dumps(response) if response else None,
                error,
                datetime.now(UTC).isoformat(),
                fill_quantity,
                error_code,
                error_type,
                forecast_cycle,
                int(live),
                close_time,
                replaces_order_id,
                entry_prob,
                entry_prob_precal,
                closes_position_id,
            ),
        )
        return cur.lastrowid or 0


def log_order_result(
    row_id: int,
    status: str,
    response: dict | None = None,
    error: str | None = None,
    fill_quantity: int | None = None,
    error_code: str | None = None,
    error_type: str | None = None,
    filled_at: str | None = None,
    market_mid_at_fill: float | None = None,
) -> None:
    """Update an existing order log entry with the final status/response.
    Structured error fields allow querying failures without parsing JSON.

    filled_at/market_mid_at_fill: only ever passed at the moment a fill is
    first detected (see order_executor._poll_pending_orders) — used with
    COALESCE so a later log_order_result() call on the same row (e.g. an
    unrelated field update) can never accidentally null them back out.

    Batch-58 item 7 (backlog L27399): response and fill_quantity now get the
    same COALESCE treatment, for the same reason. Both were unconditional
    column writes, so ANY caller that omitted them wiped whatever the row
    already held. That is the bug class the backlog records as "L-10(a)",
    and it was live in at least two places:
      - order_executor._amend_live_order's bare
        log_order_result(row_id=replaces_order_id, status="amended") call,
        which nulled the amended-away order's recorded response (where
        order_id lives) and its fill quantity.
      - order_executor._recover_pending_orders' pending-resolve branch,
        which passes fill_quantity but not response, wiping the order_id
        the row was recovered by.
    Two other sites already worked around it by hand -- _recover_pending_
    orders' resting branch re-passes response purely to avoid the wipe, and
    _finalize_cancel re-reads the row and passes its own prior values back
    in. Those pass-throughs are now redundant but harmless (an explicitly
    passed value still wins over the stored one); they are left in place
    rather than removed, since each also documents WHY the field matters at
    that specific site.

    COALESCE only ever protects a None: an explicitly passed value --
    including fill_quantity=0 -- still overwrites, because 0 is not NULL in
    SQLite. One edge (opus review, batch-58): `response` is bound as
    `json.dumps(response) if response else None`, so an explicitly passed
    EMPTY dict is falsy and reaches the COALESCE as None, i.e. it preserves
    rather than clears. No production caller passes {}, and clearing a row's
    response is exactly what this change exists to prevent, so the behaviour
    is correct -- but "only protects a None" is a hair stronger than the
    code, and this is the gap. No caller in this repo relies on log_order_result nulling either
    column back out; the only writer that intentionally REDUCES
    fill_quantity is record_live_partial_exit, which uses its own atomic
    UPDATE and is unaffected.
    """
    init_log()
    with _conn() as con:
        con.execute(
            """UPDATE orders SET
               status=?, response=COALESCE(?, response), error=?,
               fill_quantity=COALESCE(?, fill_quantity),
               error_code=?, error_type=?,
               filled_at=COALESCE(?, filled_at),
               market_mid_at_fill=COALESCE(?, market_mid_at_fill)
               WHERE id=?""",
            (
                status,
                json.dumps(response) if response else None,
                error,
                fill_quantity,
                error_code,
                error_type,
                filled_at,
                market_mid_at_fill,
                row_id,
            ),
        )


def claim_unknown_order(row_id: int) -> bool:
    """Atomically claim an 'unknown'-status row for recovery processing,
    flipping it to 'pending' (reusing that status' existing "in-flight,
    being reconciled" meaning rather than inventing a new one) ONLY if it
    is still 'unknown' at the moment of this UPDATE. Returns whether THIS
    call won the claim.

    Opus review follow-up (AUD-0007, round 2): order_executor.
    _recover_pending_orders can run concurrently from more than one process
    (cron.py's own cycle vs cmd_watch's standalone call, deliberately NOT
    serialized behind the shared cron lock per AUD-0013) -- without this,
    two processes could both read the same 'unknown' row via
    get_unknown_live_orders() and both attempt to resolve/settle it,
    double-applying a partial-exit's quantity reduction and P&L (
    record_live_partial_exit's own guard only checks the remaining
    quantity is non-negative, not whether this specific delta was already
    applied once). Only the winner of this atomic claim may proceed to
    call _settle_recovered_exit_order; the loser must skip the row
    entirely this pass.
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            "UPDATE orders SET status = 'pending' WHERE id = ? AND status = 'unknown'",
            (row_id,),
        )
    return cur.rowcount > 0


def claim_position_for_exit(position_id: int, ttl_minutes: int = 10) -> str | None:
    """Atomically claim an open live position row for a protective-exit
    attempt, mirroring claim_unknown_order's CAS pattern. Only the winner
    of this claim may proceed to call place_order() for this position; the
    loser must skip it entirely this pass.

    Batch-31 M-4: cron's and watch's exit scanners are deliberately NOT
    serialized (AUD-0013), and each independently derives the identical
    exit decision for the same position -- without a claim, both could call
    place_order() and both real SELLs could land. TTL-bounded (not a
    permanent claim) specifically because the window between winning this
    claim and place_order() actually completing is exactly where the live-
    order watchdog's os._exit(1) can land (CR-1) -- a permanent claim would
    leave the position unprotected forever after a crash in that window;
    this one self-heals after ttl_minutes with no settlement.

    Also guarded on settled_at IS NULL: a position already fully closed
    (by this claim's own eventual caller, or a concurrent writer) must
    never be re-claimed.

    Returns the claim token (the exit_claimed_at timestamp THIS call wrote)
    on success, None if the claim was lost. Independent review (batch-31):
    a caller must pass this exact token back to release_exit_claim(), not
    just the position_id -- otherwise a slow claimant (e.g. place_order()
    stalling past the TTL on its own internal reconciliation retries) could
    release a LATER claimant's still-active claim on the same return path,
    reopening the double-sell window a third scanner could then win.
    """
    init_log()
    token = datetime.now(UTC).isoformat()
    with _conn() as con:
        cur = con.execute(
            f"""
            UPDATE orders SET exit_claimed_at = ?
            WHERE id = ? AND settled_at IS NULL
              AND (exit_claimed_at IS NULL
                   OR {sql_normalize_iso_column("exit_claimed_at")} < datetime('now', ?))
            """,
            (token, position_id, f"-{ttl_minutes} minutes"),
        )
    return token if cur.rowcount > 0 else None


def release_exit_claim(position_id: int, claim_token: str) -> None:
    """Clear a position's exit claim after an attempt that did NOT close it
    (no fill, a genuine partial fill leaving the position open at a smaller
    size, or a confirmed-failed placement) -- so the next scan can retry
    immediately instead of waiting out claim_position_for_exit's TTL.

    claim_token must be the exact value claim_position_for_exit() returned
    to this same caller -- the UPDATE only clears the claim if it still
    matches, so a caller whose own attempt ran long enough for the TTL to
    expire and a NEW claimant to win can never wipe that newer claim out
    from under it (independent review, batch-31 F5).

    Deliberately NOT called after an OrderStatusUnknownError outcome: the
    sell attempt's true fate is unconfirmed (AUD-0007), so an early release
    here would reopen the exact double-sell window this claim exists to
    close. Leaving the claim in place until the TTL expires (or the row
    settles, which makes the claim moot) is the load-bearing protection for
    that case.
    """
    init_log()
    with _conn() as con:
        con.execute(
            "UPDATE orders SET exit_claimed_at = NULL "
            "WHERE id = ? AND exit_claimed_at = ?",
            (position_id, claim_token),
        )


def was_recently_ordered(ticker: str, side: str, within_minutes: int = 10) -> bool:
    """
    Return True if an order for this ticker+side was placed within the last N minutes.
    Use before auto-placing to prevent duplicate orders if the program restarts.
    """
    init_log()
    with _conn() as con:
        # H-21: normalize placed_at to SQLite format before comparing — see
        # sql_normalize_iso_column()'s docstring for why mixed ISO-T/SQLite
        # timestamp formats otherwise corrupt this comparison.
        row = con.execute(
            f"""
            SELECT 1 FROM orders
            WHERE ticker = ? AND side = ? AND status != 'failed'
              AND {sql_normalize_iso_column("placed_at")} >= datetime('now', ?)
            LIMIT 1
            """,
            (ticker, side, f"-{within_minutes} minutes"),
        ).fetchone()
    return row is not None


def was_traded_today(ticker: str, side: str, live: bool | None = None) -> bool:
    """
    Return True if this ticker+side was successfully ordered today (UTC).
    Excludes failed and canceled orders so a timeout or a no-fill GTC cancel
    doesn't permanently blacklist the ticker for the rest of the UTC day —
    same reasoning as was_ordered_recently()'s canceled exclusion (F8): a
    canceled order never established a position, so it shouldn't count as
    "already traded" the way was_ordered_this_cycle()/was_recently_ordered()
    deliberately still do (those are short anti-thrash windows where even a
    just-canceled attempt should block an immediate retry; this is a
    same-day window where that tradeoff no longer favors blocking).

    live: if True, only match live orders (live=1); if False, only paper; if None, match both.
    H-6: the live= filter lets the micro-live dedup check be scoped to live orders only,
    preventing the paper order from self-blocking the micro-live placement.
    """
    init_log()
    today = datetime.now(UTC).date().isoformat()
    live_clause = "" if live is None else f" AND live = {1 if live else 0}"
    with _conn() as con:
        row = con.execute(
            f"SELECT 1 FROM orders WHERE ticker=? AND side=? AND placed_at LIKE ? "
            f"AND status NOT IN ('failed', 'canceled', 'cancelled'){live_clause} LIMIT 1",
            (ticker, side, f"{today}%"),
        ).fetchone()
    return row is not None


def was_ordered_this_cycle(ticker: str, side: str, cycle: str) -> bool:
    """Return True if an order for ticker+side was placed on this forecast cycle."""
    init_log()
    with _conn() as con:
        row = con.execute(
            """
            SELECT 1 FROM orders
            WHERE ticker = ? AND side = ? AND forecast_cycle = ? AND status != 'failed'
            LIMIT 1
            """,
            (ticker, side, cycle),
        ).fetchone()
    return row is not None


def was_ordered_recently(ticker: str, days: int = 7) -> bool:
    """Return True if a filled order for this ticker was placed within the last N days.

    Belt-and-suspenders duplicate guard: catches cross-run re-entries when
    get_open_trades() returns stale data (e.g. after an incorrect early settlement).
    Safe to use because weather market tickers encode the target date, so the same
    ticker appearing within 7 days is always a duplicate, never a new opportunity.
    """
    init_log()
    with _conn() as con:
        # H-22: match any non-failed/canceled status — orders stuck in 'sent'/'pending'
        # after a crash would be invisible with status='filled' only, allowing re-entry.
        # F8: "canceled" (American) is the only spelling any writer uses now.
        # _kalshi_status_to_internal() (translating Kalshi's real API status)
        # always wrote "canceled", which this NOT IN list never matched (it
        # only had the GTC-timer paths' "cancelled", British) — an
        # API-canceled order stayed wrongly excluded from re-entry for the
        # full 7-day dedup window instead of unblocking immediately, the way
        # a GTC-timer cancel already correctly did. "cancelled" (British) is
        # kept in this list too — deploying the F8 spelling fix doesn't
        # retroactively rewrite rows already on disk from before the fix, so
        # a pre-existing "cancelled" row would otherwise wrongly block
        # re-entry for its own leftover 7-day window post-deploy.
        # H-21: normalize placed_at to SQLite format before comparing — see
        # sql_normalize_iso_column()'s docstring for why mixed ISO-T/SQLite
        # timestamp formats otherwise corrupt this comparison (same bug class
        # already fixed in was_recently_ordered() above and repeatedly in
        # tracker.py).
        row = con.execute(
            f"""
            SELECT 1 FROM orders WHERE ticker=?
            AND status NOT IN ('failed', 'canceled', 'cancelled')
            AND {sql_normalize_iso_column("placed_at")} >= datetime('now', ?)
            LIMIT 1
            """,
            (ticker, f"-{days} days"),
        ).fetchone()
    return row is not None


def _degraded_for_today() -> bool:
    """True if a prior add_live_loss() failure left today's total untrustworthy."""
    path = _degraded_flag_path()
    try:
        if not path.exists():
            return False
        flag = json.loads(path.read_text(encoding="utf-8"))
        return flag.get("date") == datetime.now(UTC).strftime("%Y-%m-%d")
    except Exception:
        # Can't even read our own flag — treat as degraded rather than assume clean.
        return True


def _clear_degraded_flag() -> None:
    try:
        _degraded_flag_path().unlink(missing_ok=True)
    except Exception:
        pass  # best-effort; a stale flag only ever makes the gate stricter, never looser


def _set_degraded_flag(reason: str) -> None:
    try:
        _degraded_flag_path().write_text(
            json.dumps(
                {"date": datetime.now(UTC).strftime("%Y-%m-%d"), "reason": reason}
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        _log.error("add_live_loss: could not even write degraded flag: %s", exc)


def get_today_live_loss() -> float:
    """Return today's accumulated live loss in dollars (UTC date).

    Fails closed: if a prior write left today's total untrustworthy (see
    add_live_loss), or this read itself fails against a stuck DB, returns
    inf so every `>= daily_loss_limit` gate trips rather than silently
    under-reporting. Returns 0.0 only for the genuine "no orders yet today" case.
    """
    if _degraded_for_today():
        return float("inf")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        init_log()
        with _conn() as con:
            row = con.execute(
                "SELECT total FROM daily_live_loss WHERE date = ?", (today,)
            ).fetchone()
        return row["total"] if row else 0.0
    except Exception as exc:
        _log.error("get_today_live_loss: DB read failed, failing closed: %s", exc)
        _set_degraded_flag(f"read failed: {exc}")
        return float("inf")


def get_live_realized_loss_since(days: int) -> float:
    """Return realized live loss (dollars) over the trailing `days` calendar
    dates, inclusive of today (UTC), in the same loss-sign convention as
    get_today_live_loss(): positive = net loss, negative = net gain.

    AUD-0005: paper.is_paused_drawdown() only ever reads paper_trades.json,
    so a real live-account bleed spread across multiple days was never
    caught by any gate. Sums daily_live_loss.total (already correctly
    updated at every full settlement AND every partial exit via
    add_live_loss -- see order_executor._exit_live_position's docstring)
    rather than re-deriving from orders.pnl directly, since that table is
    the single place both settlement paths already write to.

    A trailing window (not a true all-time peak-balance drawdown, which
    paper.py's mechanism is) by design -- there is no persisted live
    peak/starting balance anywhere to compute a real high-water mark from,
    and this project deliberately chose not to add one (new table +
    snapshot-writer) for a currently-dormant feature. Fails closed (inf) on
    a DB read failure, matching get_today_live_loss()/get_today_live_spend().

    Opus-review-caught: also fails closed via the same degraded-flag check
    get_today_live_loss() uses -- if a prior add_live_loss() write failed,
    today's own row in daily_live_loss is untrustworthy (understated), and
    silently summing it as fact here would let a real bleed pass the
    drawdown gate on the one day the data is known-wrong.
    """
    if _degraded_for_today():
        return float("inf")
    # Opus-review-caught (L5): days<=0 would push cutoff into the future,
    # matching zero rows and silently returning 0.0 loss -- a silent kill
    # switch for the drawdown gate with no warning. Clamp to at least 1 day
    # (today only) instead.
    days = max(1, days)
    today = datetime.now(UTC).date()
    cutoff = (today - timedelta(days=days - 1)).isoformat()
    try:
        init_log()
        with _conn() as con:
            row = con.execute(
                "SELECT COALESCE(SUM(total), 0.0) AS total FROM daily_live_loss "
                # Opus-review-caught (L5): upper-bound the window too --
                # without it a future-dated row (clock skew, a test/dev
                # artifact) would silently count toward today's loss.
                "WHERE date >= ? AND date <= ?",
                (cutoff, today.isoformat()),
            ).fetchone()
        return float(row["total"]) if row else 0.0
    except Exception as exc:
        _log.error(
            "get_live_realized_loss_since: DB read failed, failing closed: %s", exc
        )
        return float("inf")


def get_live_settlement_streak() -> tuple[str, int, float]:
    """Live-order equivalent of paper.get_current_streak(): returns
    ("win"|"loss"|"neutral"|"none", N, streak_pnl) describing the trailing
    run of consecutive same-direction settled live orders, ordered by
    settlement time. streak_pnl is the sum of pnl across those N orders
    (paper's is_streak_paused() re-derives this same magnitude from a
    second, separate query over paper_trades.json -- returned directly here
    instead so the caller doesn't need its own second query or reach into
    this module's private _conn()).

    AUD-0005: paper.is_streak_paused() only ever reads paper_trades.json, so
    a genuine live consecutive-loss streak was never caught by any gate.

    No closes_position_id filter (unlike get_filled_unsettled_live_orders,
    which excludes those rows because they'd be misread as brand-new open
    positions) -- a partial-exit's own row IS a genuine settled outcome with
    real pnl (order_executor._exit_live_position's partial-fill path calls
    record_live_early_exit on that exact row), and excluding it here would
    silently drop real losses/wins from the streak the same way it used to
    drop them from get_live_pnl_summary's totals before that was fixed.

    AUD-0057 review followup: DOES exclude exit_reason='unmatched_sell' rows
    (mirroring get_live_pnl_summary/export_live_tax_csv's own exclusion) --
    that row's pnl=0.0 is a documented non-real placeholder (cmd_order has
    no tracked entry_price to compute a real one for an unmatched sell), and
    this function is the one consumer of orders.pnl that feeds an actual
    live risk GATE (paper.is_streak_paused() via LiveTradingGate.check()),
    not just a dashboard/export display. Left unfiltered, a placeholder
    'neutral, 0-length streak' settlement landing right after a real
    consecutive-loss run would silently reset the streak the circuit
    breaker is watching, exactly when it should be tripping.

    Unlike get_today_live_loss()/get_live_realized_loss_since(), this does
    NOT catch and fail closed internally -- there is no natural "worse than
    any real streak" sentinel for a (direction, count, pnl) tuple the way
    `inf` is for a dollar total. Raises on a DB read failure; the caller
    (paper.is_streak_paused()) is responsible for failing its own bool
    contract closed, matching how trading_gates.LiveTradingGate.check()
    already wraps each individual safety check in its own try/except.

    Opus-review-caught: excludes same-day (days_out==0) settlements from
    the streak, matching paper.get_current_streak()'s own
    `((_d := t.get("days_out")) is None or _d >= 1)` filter exactly -- same-
    day trades settle within hours and this codebase deliberately treats
    them as a separate, faster-cycling risk bucket that shouldn't drive the
    same multi-day streak signal. execution_log's orders table never
    persisted days_out for live orders, so it's reconstructed the same way
    order_executor._get_live_open_positions() does for open positions:
    target_date (parsed from the ticker, falling back to close_time for
    series with no day-level date in the ticker) minus the date the
    position was entered.

    2nd-round-opus-review-caught (M-F): unlike order_executor.
    _resolve_live_balance (given a short TTL cache in the same review
    round -- see its docstring), this function is deliberately left
    UNcached despite running an unbounded full-table scan with a
    per-row regex/timezone parse on every call, now including from
    kelly_bet_dollars(client=...) once per Kelly-sizing call. A
    _resolve_live_balance-style cache attaches to the client object
    itself, naturally scoping its lifetime to that object (safe across
    tests, since each test gets a fresh mock). This function takes no
    client -- any cache would have to be module-level, and this module's
    own DB_PATH is routinely repointed at a fresh per-test temp file by
    tests/conftest.py's autouse isolate_execution_log fixture, which a
    naive time-based module cache has no way to know about -- it would
    silently serve a PRIOR test's stale result into a fresh, supposedly-
    isolated test DB. This is a real, DB-local (not network/circuit-
    breaker) cost that grows with live-order history; worth revisiting
    with a DB_PATH-aware cache key if live order volume ever makes it
    material, but not risked here given the test-isolation hazard.
    """
    from weather_markets import _CITY_TZ, parse_city_date

    init_log()
    with _conn() as con:
        rows = con.execute(
            "SELECT pnl, ticker, close_time, placed_at, filled_at FROM orders "
            "WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL "
            "AND (exit_reason IS NULL OR exit_reason != 'unmatched_sell') "
            # Opus-review-caught (L4): `id` tiebreaker for a deterministic
            # order when two settlements land in the same instant -- paper's
            # get_current_streak() sorts a stable Python list, this is the
            # SQL equivalent.
            "ORDER BY settled_at, id",
        ).fetchall()

    def _is_same_day(row) -> bool:
        city, target_date = parse_city_date({"ticker": row["ticker"]})
        if target_date is None and row["close_time"]:
            try:
                from zoneinfo import ZoneInfo as _ZI

                # 2nd-round-opus-review-caught (H-B): close_time is UTC;
                # target_date must be CITY-LOCAL -- mirrors
                # order_executor._get_live_open_positions()' identical fix.
                target_date = (
                    datetime.fromisoformat(row["close_time"].replace("Z", "+00:00"))
                    .astimezone(_ZI(_CITY_TZ.get(city or "", "America/New_York")))
                    .date()
                )
            except (ValueError, TypeError, KeyError):
                return False
        entered_at = row["filled_at"] or row["placed_at"]
        if target_date is None or not entered_at:
            return False
        try:
            # 2nd-round-opus-review-caught (H-B/L-1): target_date is
            # CITY-LOCAL; entered_at is UTC. Convert to the city's own
            # local calendar date before comparing -- mirrors
            # order_executor._get_live_open_positions()' own fix for the
            # identical bug, which this docstring already claims (now
            # correctly) to match.
            from zoneinfo import ZoneInfo

            entered_dt = datetime.fromisoformat(entered_at.replace("Z", "+00:00"))
            entered_date = entered_dt.astimezone(
                ZoneInfo(_CITY_TZ.get(city or "", "America/New_York"))
            ).date()
        except (ValueError, TypeError, KeyError):
            return False
        return target_date == entered_date

    rows = [r for r in rows if not _is_same_day(r)]
    if not rows:
        return ("none", 0, 0.0)
    pnls = [r["pnl"] for r in rows]
    last = pnls[-1]
    if last > 0:
        direction = "win"
    elif last < 0:
        direction = "loss"
    else:
        return ("neutral", 0, 0.0)
    streak = 1
    for pnl in reversed(pnls[:-1]):
        if direction == "win" and pnl > 0:
            streak += 1
        elif direction == "loss" and pnl < 0:
            streak += 1
        else:
            break
    return (direction, streak, sum(pnls[-streak:]))


def get_today_live_spend() -> float:
    """Return today's cumulative live order spend in dollars (UTC date),
    across every non-failed/canceled/amended order regardless of settlement
    status.

    F7 followup: placement-time add_live_loss(cost) was removed because it
    double-counted with settlement-time add_live_loss(-pnl) -- correct, but
    it had also been the only thing making a long-running `watch --auto
    --live` session's MAX_DAILY_SPEND-style cap see PRIOR cycles' live
    spend; _daily_paper_spend()/_daily_sameday_spend() only ever read
    paper_trades.json and are blind to live orders entirely. This is a
    dedicated spend counter (not the realized-loss counter), computed fresh
    from execution_log each call so it reflects every live order placed
    this UTC day across the whole process's lifetime, not just this call.

    'amended' is excluded for the same reason 'canceled' is: an amended
    order's original row represents capital that was never actually
    released (unlike a genuine cancel), but its commitment now lives on in
    the new row the amend chain logged via replaces_order_id -- counting
    both would double-count the same resting position's capital every time
    it gets repriced (see order_executor._amend_live_order).

    closes_position_id IS NULL excludes protective-exit SELL orders for the
    same reason _exit_live_position() itself skips the daily-spend gate on
    exits: a SELL that closes existing exposure isn't new capital deployed,
    and every exit order's own row would otherwise inflate this counter --
    compounding once per cycle for a position whose IOC exit repeatedly
    partial-fills, since each retry logs its own new exit-order row.

    Fails closed (inf) on a DB read failure, matching get_today_live_loss().
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        init_log()
        with _conn() as con:
            row = con.execute(
                "SELECT COALESCE(SUM(quantity * price), 0.0) AS total FROM orders "
                "WHERE live = 1 "
                "AND status NOT IN ('failed', 'canceled', 'cancelled', 'amended') "
                "AND closes_position_id IS NULL "
                "AND placed_at >= ?",
                (today,),
            ).fetchone()
        return float(row["total"]) if row else 0.0
    except Exception as exc:
        _log.error("get_today_live_spend: DB read failed, failing closed: %s", exc)
        return float("inf")


def add_live_loss(amount: float) -> float:
    """Add amount to today's live loss total and return the new total.

    amount > 0 means a cost (order placed, loss settled).
    amount < 0 means a gain (winning settlement).
    Uses INSERT ... ON CONFLICT so concurrent calls are safe.

    On total failure (can't write, can't even re-read the last known total),
    fails closed: sets a same-day degraded flag that forces get_today_live_loss()
    to report inf until a write succeeds again, instead of silently returning
    0.0 (sqlite3.connect already retries internally for 30s, so reaching this
    branch means the DB is genuinely stuck, not just momentarily locked).
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now_iso = datetime.now(UTC).isoformat()
    try:
        init_log()
        with _conn() as con:
            con.execute(
                """
                INSERT INTO daily_live_loss (date, total, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total = total + excluded.total,
                    updated_at = excluded.updated_at
                """,
                (today, amount, now_iso),
            )
            row = con.execute(
                "SELECT total FROM daily_live_loss WHERE date = ?", (today,)
            ).fetchone()
        _clear_degraded_flag()
        return row["total"] if row else amount
    except Exception as exc:
        _log.error("add_live_loss DB write failed: %s", exc)
        _set_degraded_flag(f"write failed: {exc}")
        try:
            with _conn() as con:
                row = con.execute(
                    "SELECT total FROM daily_live_loss WHERE date = ?", (today,)
                ).fetchone()
            return row["total"] if row else float("inf")
        except Exception as _e:
            _log.error("add_live_loss fallback read also failed: %s", _e)
            return float("inf")


def get_pending_live_orders() -> list[dict]:
    """Return every live order still resting (status='pending'), unbounded.

    AUD-0012: dedicated scoped query, not a LIMIT-N-of-everything fetch
    filtered in Python afterward -- that pattern (execution_log.py's own
    get_recent_orders(limit=N)) can silently evict a genuinely still-pending
    live order once enough other (overwhelmingly paper) orders accumulate
    after it, once N is exceeded. Mirrors get_filled_unsettled_live_orders's
    own unbounded WHERE-scoped shape.
    """
    init_log()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM orders WHERE live = 1 AND status = 'pending' "
            "ORDER BY placed_at",
        ).fetchall()
    return [dict(r) for r in rows]


def get_unknown_live_orders() -> list[dict]:
    """Return every live order whose placement outcome is ambiguous
    (status='unknown'), unbounded.

    AUD-0007: written when place_order()'s create-order POST failed AND
    reconciliation itself couldn't confirm either way (see
    kalshi_client.OrderStatusUnknownError) -- the order may or may not have
    landed on the exchange. response's client_order_id is the only way to
    re-check these against Kalshi later (there is no order_id -- the create
    call itself never confirmed one). Mirrors get_pending_live_orders'
    unbounded WHERE-scoped shape for the same reason (AUD-0012).
    """
    init_log()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM orders WHERE live = 1 AND status = 'unknown' "
            "ORDER BY placed_at",
        ).fetchall()
    return [dict(r) for r in rows]


def get_unresolved_live_orders() -> list[dict]:
    """Return every live order parked at the terminal status='unresolved',
    unbounded.

    Batch-58 item 5 (backlog L24457): an 'unknown' row whose true state
    still could not be determined after _UNRESOLVED_AGE_MINUTES. Parking it
    here is what stops order_executor._recover_pending_orders re-checking
    it against Kalshi forever; an operator alert fires once at the moment of
    parking (see LIVE_TRADING_RUNBOOK.md).

    'unresolved' is deliberately NOT 'failed'. Every dedup/spend guard in
    this module keys off status via NOT-IN lists that exclude
    'failed'/'canceled'/'cancelled'/'amended' -- a parked row keeps
    blocking a re-placement (get_recent_order_for_market,
    has_order_this_cycle) and keeps counting toward
    get_today_live_spend(), exactly as it did while 'unknown'. Reusing
    'failed' would have unblocked dedup and let the bot re-place an order
    that may genuinely be resting live on the exchange.
    """
    init_log()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM orders WHERE live = 1 AND status = 'unresolved' "
            "ORDER BY placed_at",
        ).fetchall()
    return [dict(r) for r in rows]


def park_unresolved_order(row_id: int) -> bool:
    """Atomically move an 'unknown' row to the terminal 'unresolved' status,
    ONLY if it is still 'unknown' at the moment of this UPDATE. Returns
    whether THIS call won the transition.

    Batch-58 item 5. Mirrors claim_unknown_order/claim_sent_order's exact
    atomicity pattern for the identical reason: _recover_pending_orders can
    run concurrently from more than one process (cron.py's own cycle vs
    cmd_watch's standalone call, deliberately NOT serialized per AUD-0013),
    so a plain unconditional UPDATE here could park a row another process
    had just resolved to 'pending'/'filled', silently reverting real
    settlement data. The rowcount check is also what stops a losing
    concurrent pass re-alerting for a row it did not park. (Opus review,
    batch-58, M1: "exactly once per row" was the intent but not the
    behaviour until the caller switched to a per-ROW send_system_alert
    cooldown_key -- a single shared key meant only one parked row per 6
    hours ever alerted.)

    Deliberately does NOT touch response -- the stored client_order_id is
    the only handle an operator has for reconciling this row against Kalshi
    by hand.
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            "UPDATE orders SET status = 'unresolved' "
            "WHERE id = ? AND status = 'unknown'",
            (row_id,),
        )
    return cur.rowcount > 0


def count_open_live_positions() -> int:
    """Count open live positions -- the single definition of "open" shared by
    order_executor._count_open_live_orders (the max_open_positions safety
    gate) and get_live_pnl_summary's open_count (the dashboard stat).

    Batch-58 item 3 (backlog L24388): get_live_pnl_summary computed its own
    `status = 'pending'` COUNT, which is the exact undercount AUD-0009
    already fixed for the gate -- both gaps that entry named (filled-
    unsettled AND unknown) were still present. Extracted here rather than
    duplicated in SQL so the two consumers cannot drift apart again.

    The union, and why each arm is in it (see _count_open_live_orders'
    docstring for the full history):
      - status='pending'    -- a resting entry order is real capital that
                               could fill at any moment.
      - status='unknown'    -- an ambiguous placement (AUD-0007) could turn
                               out to be a real fill.
      - status='unresolved' -- batch-58 item 5's terminal park for an
                               'unknown' row that never resolved. It counted
                               here while it was 'unknown'; dropping it on
                               the status change would have silently LOOSENED
                               max_open_positions, which is why parking a row
                               adds it to this union rather than removing it.
      - filled-but-unsettled positions.
    closes_position_id IS NULL on the three non-settled arms excludes a
    protective EXIT order's own row, which would otherwise be double-counted
    alongside the position it is closing.
    """
    init_log()
    with _conn() as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS open_count FROM orders
            WHERE live = 1
              AND closes_position_id IS NULL
              AND (
                    status IN ('pending', 'unknown', 'unresolved')
                 OR (status = 'filled' AND settled_at IS NULL)
              )
            """,
        ).fetchone()
    return row["open_count"] or 0


def get_sent_live_orders(older_than_minutes: int = 0) -> list[dict]:
    """Return every live order still at status='sent' (log_order()'s
    transient pre-placement default), unbounded.

    Batch-22 item 2: 'sent' is written in two situations, both meaning "we
    don't know what happened to this order attempt": (a) log_order()'s own
    default, when a caller (main.cmd_order) pre-logs before ever touching
    the API and the process then crashes before the real outcome is
    recorded; (b) order_executor._recover_pending_orders' own "pending row
    with no order_id" branch, which downgrades TO 'sent' for the same
    reason. Neither get_pending_live_orders() nor get_unknown_live_orders()
    nor get_filled_unsettled_live_orders() ever select 'sent' -- before this
    fix, nothing ever re-checked these rows again, so a real fill could go
    permanently untracked. Mirrors get_pending_live_orders'/
    get_unknown_live_orders' unbounded WHERE-scoped shape.

    older_than_minutes: opus review (batch-22 follow-up, F1/F2) -- a 'sent'
    row is genuinely "unknown outcome" for its ENTIRE lifetime, not just
    after a crash: main.cmd_order/main._quick_paper_buy pre-log with this
    exact status BEFORE calling place_order at all, so a row can be 'sent'
    for the ordinary few seconds an in-flight placement takes. Without this
    filter, a concurrent _recover_pending_orders() pass (cron vs `watch
    --auto --live`, deliberately unserialized per AUD-0013) could read and
    promote/resolve a row the ORIGINAL placing process hasn't finished with
    yet -- racing its own eventual log_order_result() call and, worse,
    potentially resolving a not-yet-actually-attempted order to 'failed'
    (unblocking dedup) or double-applying a partial-exit settlement. The
    default (0) is unbounded for callers that intentionally want every
    'sent' row regardless of age (e.g. an operator inspection script);
    order_executor._recover_pending_orders passes a real margin.
    """
    init_log()
    with _conn() as con:
        if older_than_minutes > 0:
            rows = con.execute(
                f"SELECT * FROM orders WHERE live = 1 AND status = 'sent' "
                f"AND {sql_normalize_iso_column('placed_at')} <= datetime('now', ?) "
                f"ORDER BY placed_at",
                (f"-{older_than_minutes} minutes",),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM orders WHERE live = 1 AND status = 'sent' "
                "ORDER BY placed_at",
            ).fetchall()
    return [dict(r) for r in rows]


def claim_sent_order(row_id: int, client_order_id: str) -> bool:
    """Atomically promote a 'sent' row to 'unknown' (carrying its recovered
    client_order_id) ONLY if it is still 'sent' at the moment of this
    UPDATE. Returns whether THIS call won the claim.

    Opus review follow-up (batch-22, F3): the original promotion write was
    a plain unconditional UPDATE (no WHERE status='sent' predicate) --
    log_order_result() always overwrites status/response/error/fill_quantity
    regardless of the row's CURRENT state, so a promotion landing after a
    concurrent process had already resolved the same row (e.g. to 'filled'
    via the 'unknown' reconciliation loop just below, in the same or a
    different process) could silently revert real settlement data (order_id,
    fill_quantity) back to a bare {"client_order_id": ...} response. Mirrors
    claim_unknown_order's exact atomicity pattern for the identical reason.
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            "UPDATE orders SET status = 'unknown', response = ? "
            "WHERE id = ? AND status = 'sent'",
            (json.dumps({"client_order_id": client_order_id}), row_id),
        )
    return cur.rowcount > 0


def get_filled_unsettled_live_orders() -> list[dict]:
    """Return live filled orders that have not yet had their settlement
    outcome recorded -- i.e. open POSITIONS, not exit orders.

    closes_position_id IS NULL excludes a protective exit order's own row:
    that row is itself live=1/status=filled/settled_at=NULL (it closed a
    DIFFERENT row, the position referenced by closes_position_id, not
    itself), so without this filter it would be indistinguishable from a
    genuine new entry fill and misread as a brand-new open position by
    every caller of this function.
    """
    init_log()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM orders
            WHERE live = 1 AND status = 'filled' AND settled_at IS NULL
              AND closes_position_id IS NULL
            ORDER BY placed_at
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def record_live_settlement(order_id: int, outcome_yes: bool, pnl: float) -> bool:
    """Write natural-market-settlement outcome to an order row.

    outcome_yes=True means the YES side won (the market resolved 'yes').
    pnl is net P&L after Kalshi fee, in dollars.

    Batch-31 M-3: guarded on settled_at IS NULL, like every sibling
    settlement writer (record_live_early_exit, update_live_peak_profit) --
    previously an unconditional UPDATE. cron's _settle_recovered_exit_order
    and watch's own settlement poll can race on the same row (a stale
    get_filled_unsettled_live_orders() snapshot read before a concurrent
    writer already settled it), and two concurrent watch processes are a
    second route to the same race. The danger direction is real even though
    narrower than originally scoped (cron never calls _poll_pending_orders;
    an exit IOC fill on an already-finalized market is impossible): a
    winning position credited twice would make the live daily-loss brake
    read looser than reality, and an unconditional overwrite would also
    silently replace an earlier early-exit's realized pnl with this
    natural-settlement figure, corrupting the tax CSV / get_live_pnl_summary
    / settlement-streak history for that row. Returns whether THIS call
    won the race so the caller can skip add_live_loss on a loss.
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            """
            UPDATE orders
            SET settled_at = ?, outcome_yes = ?, pnl = ?
            WHERE id = ? AND settled_at IS NULL
            """,
            (datetime.now(UTC).isoformat(), int(outcome_yes), pnl, order_id),
        )
    return cur.rowcount > 0


def update_live_peak_profit(order_id: int, peak_profit_pct: float) -> None:
    """Record a new peak unrealized-profit fraction for an open live position
    (mirrors paper.py's PaperPositionStore.save_peak, both invoked via the
    shared positions.update_peak_profits() -- see backlog.txt's "PAPER AND
    LIVE POSITIONS ARE TWO LEDGERS WITH ADAPTER GLUE" entry).

    Compare-and-set guarded in SQL: only writes when the stored value is
    NULL or lower, and only while the row is still open (settled_at IS
    NULL) -- a caller-computed peak can be stale by the time this executes
    (built from a snapshot taken before a REST price-fetch loop that can
    take seconds), so a concurrent writer could otherwise have this call
    silently LOWER an already-higher peak (disarming the breakeven stop) or
    write onto a position closed in the interim.
    """
    init_log()
    with _conn() as con:
        con.execute(
            "UPDATE orders SET peak_profit_pct = ? WHERE id = ? AND "
            "settled_at IS NULL AND "
            "(peak_profit_pct IS NULL OR peak_profit_pct < ?)",
            (peak_profit_pct, order_id, peak_profit_pct),
        )


def record_live_early_exit(
    order_id: int,
    exit_price: float,
    exit_reason: str,
    pnl: float,
    expected_quantity: int | None = None,
) -> bool:
    """Mark an open live position closed via an early protective exit
    (stop-loss/breakeven/model-exit), as opposed to natural market
    settlement. Sets settled_at (so get_filled_unsettled_live_orders() stops
    treating this row as open) but deliberately leaves outcome_yes NULL --
    the underlying market hasn't actually resolved yet, we just closed our
    own position early; there is no real "yes won" / "no won" fact to record
    here. pnl is the realized net P&L (already fee-adjusted) from this exit.

    Also called by order_executor._exit_live_position on a PARTIAL fill, but
    targeted at the exit order's own row (closes_position_id set, not a
    position row) instead of the position's -- settles that row's own
    pnl/exit_price/exit_reason so the sold lot gets counted by
    export_live_tax_csv/get_live_pnl_summary, while the actual position row
    stays open (untouched) for the remainder.

    Guarded on `settled_at IS NULL` and returns whether this call actually
    applied (True) or lost a race to a concurrent settle (False) --
    record_live_exit_fill's new caller, main.cmd_order, means a manual sell
    can now race the automated cron/watch exit scan against the SAME
    position for the first time; without this guard a second writer would
    silently overwrite the first's exit_price/pnl and double-count via
    add_live_loss. Mirrors update_live_peak_profit's existing
    compare-and-set pattern just above.

    expected_quantity, when given, additionally requires the row's CURRENT
    tracked open size (fill_quantity, falling back to quantity) to still
    equal it -- opus review (2026-08-17), NEW-M2: the settled_at guard alone
    does not stop a caller holding a STALE position snapshot from
    full-closing a position a concurrent writer already partially reduced
    (partial exits deliberately leave settled_at NULL). Without this,
    Writer B computing pnl off a stale larger quantity, after Writer A's
    partial exit already shrank the real remaining size, would overwrite
    the row with inflated P&L and no error. record_live_exit_fill always
    passes this for its full-close branch. Not used by
    _exit_live_position's own partial-fill-branch call onto the EXIT
    order's row (see above) -- that row is freshly created earlier in the
    same call and not shared with any other writer, so the plain
    settled_at-only guard is sufficient there.
    """
    init_log()
    with _conn() as con:
        if expected_quantity is None:
            cur = con.execute(
                """
                UPDATE orders
                SET settled_at = ?, exit_price = ?, exit_reason = ?, pnl = ?
                WHERE id = ? AND settled_at IS NULL
                """,
                (
                    datetime.now(UTC).isoformat(),
                    exit_price,
                    exit_reason,
                    pnl,
                    order_id,
                ),
            )
        else:
            cur = con.execute(
                """
                UPDATE orders
                SET settled_at = ?, exit_price = ?, exit_reason = ?, pnl = ?
                WHERE id = ? AND settled_at IS NULL
                  AND COALESCE(fill_quantity, quantity) = ?
                """,
                (
                    datetime.now(UTC).isoformat(),
                    exit_price,
                    exit_reason,
                    pnl,
                    order_id,
                    expected_quantity,
                ),
            )
    return cur.rowcount > 0


# AUD-0026: distinct from _degraded_flag_path (which means "daily_live_loss
# writes are untrustworthy today") -- this one accumulates individual rows
# that record_live_early_exit_with_retry could not settle even after
# retrying, each of which is left in the exact live=1/status='filled'/
# settled_at=NULL/closes_position_id=NULL shape get_filled_unsettled_live_orders()
# reads as a phantom open position. Not date-scoped (unlike the degraded
# flag) since a given row's failure doesn't stop mattering at UTC midnight.
def _unsettled_exit_flag_path() -> Path:
    return DB_PATH.parent / "execution_log_unsettled_exit_rows.json"


def record_live_early_exit_with_retry(
    order_id: int,
    exit_price: float,
    exit_reason: str,
    pnl: float,
    retries: int = 3,
) -> bool:
    """Best-effort wrapper around record_live_early_exit for callers where a
    failed write leaves a row permanently in the dangerous phantom-position
    shape described above (currently only cmd_order's unmatched-sell
    fallback). The underlying UPDATE is guarded on `settled_at IS NULL`, so
    retrying after a transient failure (e.g. a momentary disk/WAL hiccup --
    ordinary lock contention is already absorbed by sqlite3.connect's own
    30s busy-timeout before an exception ever reaches this function, per
    add_live_loss's docstring) is safe and cannot double-settle the row.

    If every attempt still fails, appends a record to a persistent sentinel
    flag file (mirroring _set_degraded_flag's pattern) instead of only
    logging a warning that scrolls away, so the still-unsettled row has a
    durable, greppable trace for an operator to find.
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            applied = record_live_early_exit(order_id, exit_price, exit_reason, pnl)
            if attempt > 1:
                _log.info(
                    "record_live_early_exit_with_retry: order %d settled on "
                    "attempt %d/%d",
                    order_id,
                    attempt,
                    retries,
                )
            return applied
        except Exception as exc:
            last_exc = exc
            _log.warning(
                "record_live_early_exit_with_retry: order %d attempt %d/%d failed: %s",
                order_id,
                attempt,
                retries,
                exc,
            )
            if attempt < retries:
                _el_time.sleep(0.5 * attempt)

    _log.error(
        "record_live_early_exit_with_retry: order %d still unsettled after "
        "%d attempts (%s) -- row left live=1/status='filled'/settled_at=NULL, "
        "writing sentinel flag",
        order_id,
        retries,
        last_exc,
    )
    # Batch-22 item 7: was a plain write_text() read-modify-write with no
    # lock and no atomic_write_json -- two processes (cron and `watch --auto
    # --live`, deliberately unserialized per AUD-0013) could each read the
    # same pre-append list and one write would clobber the other's record; a
    # crash mid-write (plain write_text is not atomic) could truncate the
    # WHOLE accumulated list, not just this append. CrossProcessLock (same
    # class settlement_monitor.run_settlement_monitor already uses) guards
    # the read-modify-write as one critical section; atomic_write_json does
    # the actual write (temp + fsync + rename).
    #
    # Opus review follow-up: the prior version of this comment claimed this
    # matches "_set_degraded_flag's sibling sentinel file... for the same
    # 'fails CLOSED on corruption' reasoning" -- inaccurate on both counts.
    # _set_degraded_flag (this module, ~line 433) uses a plain write_text()
    # too, not atomic_write_json; and its fail-CLOSED property lives
    # entirely in the READ side (_degraded_for_today treats ANY read
    # exception, including a corrupt file, as "degraded" -- the safe
    # direction for that specific flag), not in how it's written. This
    # write-side fix (atomic + locked) is this item's own, standalone
    # improvement, not a mirror of an existing pattern elsewhere in the file.
    from safe_io import CrossProcessLock, atomic_write_json

    flag_path = _unsettled_exit_flag_path()
    lock = CrossProcessLock(flag_path.with_name(flag_path.name + ".lock"), timeout=10.0)
    _locked = lock.acquire()
    if not _locked:
        _log.error(
            "record_live_early_exit_with_retry: could not acquire sentinel "
            "flag lock for order %d -- writing unlocked, a concurrent writer "
            "could lose a record",
            order_id,
        )
    try:
        existing: list = []
        if flag_path.exists():
            try:
                loaded = json.loads(flag_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    existing = loaded
            except (json.JSONDecodeError, OSError) as _read_exc:
                # Opus review follow-up (LOW #9): preserve the unreadable
                # file under a .corrupt suffix before starting a fresh list
                # and overwriting it below -- the prior version's "prior
                # records may be lost" warning was true and then made itself
                # true, discarding a possibly-still-partially-recoverable
                # record of earlier phantom positions with nothing but a log
                # line. Best-effort: a rename failure here must not block
                # this function's own primary job (recording THIS row's
                # unsettled-exit flag).
                try:
                    flag_path.rename(flag_path.with_name(flag_path.name + ".corrupt"))
                except OSError as _rename_exc:
                    _log.error(
                        "record_live_early_exit_with_retry: could not "
                        "preserve unreadable sentinel flag file as "
                        ".corrupt (%s) -- it will be overwritten",
                        _rename_exc,
                    )
                _log.error(
                    "record_live_early_exit_with_retry: sentinel flag file "
                    "unreadable (%s) -- preserved as %s.corrupt, starting a "
                    "fresh list",
                    _read_exc,
                    flag_path.name,
                )
        existing.append(
            {
                "order_id": order_id,
                "exit_reason": exit_reason,
                "error": str(last_exc),
                "flagged_at": datetime.now(UTC).isoformat(),
            }
        )
        # atomic_write_json's own signature is typed for a dict payload --
        # this sentinel file's established on-disk shape (every existing
        # reader, including this function's own read above and
        # get_unsettled_exit_flags below) is a bare JSON list, and changing
        # that shape is out of this batch's scope (safe_io.py belongs to a
        # different batch per INDEX.md). json.dumps handles a list identically
        # to a dict at runtime -- only the static type differs.
        atomic_write_json(existing, flag_path)  # type: ignore[arg-type]
    except Exception as flag_exc:
        _log.error(
            "record_live_early_exit_with_retry: could not even write "
            "sentinel flag for order %d: %s",
            order_id,
            flag_exc,
        )
    finally:
        if _locked:
            lock.release()
    return False


def get_unsettled_exit_flags() -> list[dict]:
    """Read back every row record_live_early_exit_with_retry could not
    settle even after retrying, if any.

    Opus review follow-up (AUD-0026): the sentinel file this reads had no
    reader anywhere in the codebase -- a file nobody ever checks does not
    actually deliver on "the operator is alerted to" (this fix's own design
    goal), since the underlying row stays in the exact phantom-open-position
    shape the automated exit scanner could act on. Called from
    order_executor._poll_pending_orders() once per watch/cron cycle so a
    lingering flag surfaces as a recurring warning, not just a one-time
    console line an operator could miss.

    Batch-22 item 7: a decode failure used to silently return [] -- the
    operator's one recurring warning about a still-open phantom live
    position would disappear with no trace. Now logs at ERROR before
    returning [] so the failure itself is visible even though the caller
    still gets a safe empty list (this remains a best-effort visibility aid,
    not itself a safety gate -- returning [] rather than raising keeps a
    corrupt sentinel file from also taking down the poll cycle that calls
    this).
    """
    flag_path = _unsettled_exit_flag_path()
    try:
        if not flag_path.exists():
            return []
        loaded = json.loads(flag_path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        _log.error(
            "get_unsettled_exit_flags: sentinel flag file unreadable (%s) -- "
            "returning empty, but a real unsettled-exit record may be "
            "hidden behind this failure",
            exc,
        )
        return []


def record_live_partial_exit(order_id: int, filled_count: int) -> bool:
    """Reconcile an open live position's tracked size after an IOC exit
    order only partial-fills (matches what's immediately available, cancels
    the rest -- see order_executor._exit_live_position's docstring).

    Deliberately leaves settled_at/exit_price/exit_reason/pnl untouched --
    the position isn't closed, just smaller, so get_filled_unsettled_live_orders()
    must keep surfacing this row next cycle for the remaining quantity to get
    its own protective-exit attempt. Writes fill_quantity (also read by
    order_executor._poll_pending_orders' settlement loop and
    _get_live_open_positions() -- both already correctly treat it as "the
    position's current open quantity," so reusing it for this needs no
    schema change) rather than a separate column.

    filled_count is a DELTA (how many contracts this exit attempt just
    sold), not the resulting total -- the UPDATE computes
    fill_quantity - filled_count in SQL, a single atomic statement, rather
    than the caller reading fill_quantity, subtracting in Python, and
    writing the absolute result back. The latter is a read-modify-write
    race: two processes (e.g. cron and a concurrent `watch --auto --live`)
    could both read the same pre-decrement value and each independently
    compute and write the same wrong "remaining" total, silently losing one
    of the two reductions and leaving the tracked quantity too high.

    The sold portion's realized P&L is the caller's responsibility to add
    via add_live_loss(), same division of labor record_live_early_exit()
    already has with its own caller.

    Also guarded on `settled_at IS NULL` (see record_live_early_exit's
    docstring) -- returns False without writing anything if the position was
    already fully closed by a concurrent writer. Additionally requires
    `COALESCE(fill_quantity, quantity) >= filled_count` so a DELTA larger
    than what's actually still open (a stale caller) can never drive
    fill_quantity negative -- opus review (2026-08-17), NEW-L2: a negative
    or exactly-zero fill_quantity is falsy, which _get_live_open_positions()'s
    `fill_quantity or quantity` fallback would silently misread as "nothing
    tracked yet, use the full original quantity," resurrecting an
    already-closed-out position at its original size.
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            "UPDATE orders SET fill_quantity = COALESCE(fill_quantity, quantity) - ? "
            "WHERE id = ? AND settled_at IS NULL "
            "AND COALESCE(fill_quantity, quantity) >= ?",
            (filled_count, order_id, filled_count),
        )
    return cur.rowcount > 0


def set_exit_row_attribution(
    order_id: int, position_id: int | None, fill_quantity: int
) -> bool:
    """Point an EXIT order's row at the position whose partial leg it is
    about to be settled with, and record how many contracts that leg sold.

    position_id=None clears the linkage instead, which is what an
    UNMATCHED remainder needs: contracts that belong to no tracked position
    at all. export_live_tax_csv keys entirely off this column -- a NULL says
    "this row's own price/quantity are the disposition", a non-NULL says
    "join to the referenced position for the true entry price". Leaving a
    stale non-NULL there for an unmatched remainder makes the export report
    that remainder against an unrelated position's cost basis.

    Needed because main.cmd_order's live sell resolves closes_position_id
    BEFORE placement (it must -- log_order writes the row up front so a
    crash mid-flight leaves a reconcilable record), naming the OLDEST
    matching position. Once batch-60 made that sell cascade its fill across
    several positions oldest-first, the leg whose P&L lands on this row via
    record_live_early_exit is the LAST one touched, not necessarily the
    first -- so the pre-placement guess can be wrong by the time the fill
    is known.

    export_live_tax_csv's self-join treats a row with closes_position_id
    set as "a partial exit's own row" and reads the referenced position for
    the true entry price, plus COALESCE(fill_quantity, quantity) for the
    amount sold. Leaving the stale pointer in place therefore reported that
    leg's P&L against the WRONG position's entry price, and counted the
    whole multi-position fill as this one leg's quantity -- a 4+6 cascade
    exported 4 + 10 = 14 contracts disposed for a 10-contract sale (opus
    review, F2). Rolled-up P&L (get_live_pnl_summary) was unaffected; this
    is a cost-basis and quantity defect, which on a tax export is its own
    kind of wrong.

    A no-op in the single-match case order_executor._exit_live_position and
    the pre-cascade code both produce -- there the pointer already names
    the right position and fill_quantity already equals the leg -- so this
    is safe to call unconditionally rather than only when the cascade
    actually spanned more than one position.

    Deliberately does NOT touch settled_at/pnl: the caller settles the row
    itself immediately afterwards via record_live_early_exit, which keeps
    that function the single writer of settlement state. Guarded on
    settled_at IS NULL for the same reason every other writer here is --
    if a concurrent writer already settled this row, its attribution
    belongs to whatever it recorded, not to us.

    Returns True if the row was updated.
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            "UPDATE orders SET closes_position_id = ?, fill_quantity = ? "
            "WHERE id = ? AND settled_at IS NULL",
            (position_id, fill_quantity, order_id),
        )
    return cur.rowcount > 0


def record_live_exit_fill(
    position: dict, fill_count: int, exit_price: float, reason: str | None = None
) -> tuple[float, bool]:
    """Record a live position's exit fill (full or partial) and compute its
    fee-adjusted realized P&L -- the shared settlement math both
    order_executor._exit_live_position (automated protective exits) and
    main.cmd_order (manual live sells) need.

    Batch-22 items 3+6: subtracts utils.kalshi_taker_fee(clamped_fill_count,
    exit_price) from gross P&L unconditionally (win or loss) -- this exit is
    always an IOC/taker fill (see below), so the real fee is charged on this
    leg regardless of how the position resolves. The prior formula
    (KALSHI_FEE_RATE as a flat fraction of gross P&L, applied only when
    gross_pnl > 0) both understated a losing exit's real cost (zero fee
    charged) and mis-shaped a winning exit's fee (flat-percent-of-winnings
    instead of the curved per-contract formula) -- see kalshi_taker_fee's
    own docstring for the reproduced numeric error. This also drops the
    old docstring's "the entry side already paid $0, always a resting maker
    order" assumption: that's false for a position entered via
    main.cmd_order's live buy (always IOC/taker post-e5331a8d) or the
    auto-path's taker-cross reprice fallback. That assumption used to be
    harmless here because this function only modelled the EXIT leg; as of
    batch-58 item 8 (below) it models both legs, and the entry leg's real
    maker/taker status is read from the row rather than assumed.

    ENTRY-LEG FEE (batch-58 item 8, backlog L26637 -- the gap this
    docstring previously recorded as a deliberate deferral, now closed).
    Both legs are charged here. The entry leg's fee is looked up from the
    POSITION ROW itself, not from the caller's dict: order_type is the
    maker/taker discriminator AUD-0003 established for exactly this purpose
    ("limit" = a resting GTC maker fill, anything else = a taker fill), and
    an unreadable/missing order_type conservatively falls back to the TAKER
    rate -- same direction AUD-0003 chose, since understating realized P&L
    is the safe failure direction and assuming free maker fills is not.
    Before this, only the exit leg was ever charged on an early exit
    (order_executor._poll_pending_orders' settlement branch is the only
    other place an entry-side fee is computed, and it never runs for a row
    this function has already marked settled_at), so realized P&L on every
    taker-entered, early-exited live position was overstated by the
    unrecorded entry fee.

    The entry fee is charged on the CONTRACTS BEING CLOSED BY THIS FILL
    (clamped_fill_count at entry_price), not as a lump sum on the first
    partial exit. That is what makes it correct across more than one exit
    event -- the original deferral's stated blocker was needing the
    ORIGINAL entry quantity to prorate a one-time fee, which this sidesteps
    entirely by charging per contract with the same curved per-contract
    formula the exchange itself uses. For a position that closes in a
    single exit, the total charged is exactly the real entry fee. For a
    position that closes across k separate exits, the total can exceed it
    by at most k-1 cents, because kalshi_taker_fee rounds UP to the whole
    cent independently per call -- an overstatement of cost, i.e. the same
    safe direction as the order_type fallback above.

    SCOPE (decided explicitly, batch-58): this is a forward-only fix, and
    no backfill of stored rows is needed or performed. Verified 2026-08-24
    against the production data/execution_log.db: zero live=1 rows and zero
    settled_at rows exist, in the live database and in every retained
    backup of it -- the bot has never settled a live position, so there is
    no historical corpus carrying the overstated P&L and no date boundary
    introduced by fixing it here.

    This exit is always an IOC/taker fill for every caller of this function
    (order_executor._exit_live_position and main.cmd_order's live sells both
    place immediate_or_cancel), so kalshi_taker_fee's per-fill formula
    applies unconditionally here -- this would need revisiting if a future
    caller ever placed a resting (maker-eligible) live exit order.

    position must have "id" (its execution_log row id -- used both as the
    closes_position_id linkage and as the row this update targets),
    "quantity" (the position's currently tracked open size), and
    "entry_price".

    fill_count is clamped to position["quantity"] before any math -- a
    caller-supplied fill_count larger than what this bot believes is open
    (e.g. main.cmd_order's user-typed `count` exceeding the matched
    position's real tracked size) must not inflate the realized P&L or
    add_live_loss beyond the position's actual economic exposure.

    Returns (pnl, fully_closed). fully_closed is False when the (clamped)
    fill_count is less than the position's tracked quantity (a genuine
    partial exit -- the position stays open at the reduced size via
    record_live_partial_exit for a future retry), True when the full
    remaining quantity closed via record_live_early_exit. Both branches
    call add_live_loss(-pnl) so the day's aggregate live total reflects
    this fill immediately.

    Raises RuntimeError if a concurrent writer moved this position between
    the caller's snapshot and this call's UPDATE -- add_live_loss is
    deliberately NOT called in that case, so the same exit's P&L is never
    double-counted. NOTE the raise does NOT imply "already settled": both
    branches also raise when the position was merely REDUCED and is still
    open (the full-close branch's expected_quantity guard, and the partial
    branch's own `COALESCE(fill_quantity, quantity) >= filled_count`
    condition). A caller that reacts differently to settled-vs-reduced --
    main.cmd_order's exit cascade does -- must re-read the row rather than
    infer it from this exception.
    """
    from utils import kalshi_maker_fee, kalshi_taker_fee

    qty = position["quantity"]
    entry_price = position["entry_price"]
    clamped_fill_count = min(fill_count, qty)
    gross_pnl = clamped_fill_count * (exit_price - entry_price)

    # Batch-58 item 8: entry leg. order_type lives on the row, not on the
    # caller-supplied position dict (order_executor._get_live_open_positions
    # and main.cmd_order both build that dict without it), so read it back
    # here rather than widening every caller's dict shape. A row that can't
    # be read at all falls through to the taker rate, same conservative
    # default AUD-0003 applies to a missing/unrecognized order_type.
    _entry_row = get_order_by_id(position["id"])
    _entry_is_maker = _entry_row is not None and _entry_row.get("order_type") == "limit"
    _entry_fee = (
        kalshi_maker_fee(clamped_fill_count, entry_price)
        if _entry_is_maker
        else kalshi_taker_fee(clamped_fill_count, entry_price)
    )
    _exit_fee = kalshi_taker_fee(clamped_fill_count, exit_price)
    pnl = round(gross_pnl - _entry_fee - _exit_fee, 4)
    resolved_reason = "manual_close" if reason is None else reason

    if clamped_fill_count < qty:
        applied = record_live_partial_exit(position["id"], clamped_fill_count)
        if not applied:
            # Two distinct causes, and this message must not claim to know
            # which (opus round-2 review, MEDIUM-1): record_live_partial_exit
            # returns False when settled_at IS NOT NULL *or* when
            # COALESCE(fill_quantity, quantity) < filled_count -- the latter
            # meaning the position is STILL OPEN with real contracts, just
            # smaller than this call's snapshot. An earlier version said
            # "was already settled by a concurrent writer" unconditionally,
            # and main.cmd_order's exit cascade believed it, skipping a
            # still-open position and re-attributing its contracts to the
            # next match at the wrong cost basis. Callers that need to tell
            # the two apart must re-read the row.
            raise RuntimeError(
                f"position {position['id']} was settled or reduced below "
                f"{clamped_fill_count} by a concurrent writer -- not applying "
                "this partial exit"
            )
        add_live_loss(-pnl)
        return pnl, False

    applied = record_live_early_exit(
        position["id"], exit_price, resolved_reason, pnl, expected_quantity=qty
    )
    if not applied:
        raise RuntimeError(
            f"position {position['id']} was already settled OR partially reduced "
            "by a concurrent writer since this call's position snapshot was "
            "taken -- not applying this exit"
        )
    add_live_loss(-pnl)
    return pnl, True


def export_live_tax_csv(path: str, tax_year: int | None = None) -> int:
    """Export settled live orders to CSV for tax reporting.

    Filters to live=1, settled_at IS NOT NULL, pnl IS NOT NULL.
    If tax_year is provided, filters to rows where settled_at starts with that year.

    CSV columns: date, ticker, side, quantity, entry_price, outcome, pnl, settled_at

    A settled row is one of two shapes, disambiguated by closes_position_id:
    - closes_position_id IS NULL: a position's own row, settled via
      record_live_settlement/record_live_early_exit at full closure. `price`
      on this row IS the entry price (record_live_early_exit never touches
      it), so it's used directly.
    - closes_position_id IS NOT NULL: a partial exit's own row (see
      order_executor._exit_live_position), settled via
      record_live_early_exit called on the EXIT order's row instead of the
      position's. This row's own `price`/`quantity` are the exit order's
      limit price and REQUESTED quantity, not the entry price or the actual
      sold amount -- the self-join pulls the true entry price from the
      referenced position row, and fill_quantity (set by log_order_result
      when the IOC fill came back) gives the actual sold amount instead of
      what was requested.

    AUD-0057 + opus review follow-up: cmd_order's live sell path settles an
    unmatched sell (no tracked entry_price to compute real P&L against) with
    a documented pnl=0.0 neutral placeholder. An earlier version of this fix
    excluded those rows entirely -- reviewed and reversed: a real sell DID
    execute on the exchange, and a tax export silently OMITTING a genuine
    disposition (with no count or note anywhere) is a worse failure than
    including it, and is exactly the kind of gap an operator reconciling
    against a Kalshi statement would have no way to notice from inside this
    tool. These rows are now INCLUDED but distinctly labeled: outcome is
    written as "unmatched_sell_unknown_pnl" (not "early_exit", which would
    otherwise misreport it identically to a real early exit) and pnl is
    written as an empty cell rather than a misleading "0.0", so it reads as
    "needs manual entry" rather than "measured and zero". Dashboard
    aggregates (get_live_pnl_summary) still exclude the placeholder from
    their SUMs -- unlike a line-item CSV, a rolled-up total has no column to
    flag an unknown value in, so silently including a fabricated $0 there
    would be strictly worse than omitting it from the sum.

    Returns count of rows written.
    """
    import csv

    init_log()
    with _conn() as con:
        base_query = """
            SELECT o.placed_at, o.ticker, o.side,
                   COALESCE(o.fill_quantity, o.quantity) AS quantity,
                   COALESCE(pos.price, o.price) AS price,
                   o.outcome_yes, o.pnl, o.settled_at, o.exit_reason
            FROM orders o
            LEFT JOIN orders pos ON pos.id = o.closes_position_id
            WHERE o.live = 1 AND o.settled_at IS NOT NULL AND o.pnl IS NOT NULL
        """
        if tax_year is not None:
            rows = con.execute(
                base_query + " AND o.settled_at LIKE ? ORDER BY o.settled_at",
                (f"{tax_year}%",),
            ).fetchall()
        else:
            rows = con.execute(
                base_query + " ORDER BY o.settled_at",
            ).fetchall()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "date",
                "ticker",
                "side",
                "quantity",
                "entry_price",
                "outcome",
                "pnl",
                "settled_at",
            ]
        )
        for row in rows:
            # outcome_yes is NULL for a row closed via an early protective
            # exit (record_live_early_exit) -- the market never actually
            # resolved, so "yes"/"no" would misreport a real outcome that
            # doesn't exist. `if row["outcome_yes"] else "no"` would silently
            # write "no" here (None is falsy), reporting a fabricated result
            # on a real tax-relevant realized gain/loss.
            # AUD-0057 + opus review follow-up: an unmatched-sell row must
            # be distinguishable from a genuine early exit, not just from a
            # genuine market resolution -- both share outcome_yes IS NULL,
            # but only the former has no real pnl to report at all.
            if row["exit_reason"] == "unmatched_sell":
                outcome = "unmatched_sell_unknown_pnl"
                pnl_cell = ""
            elif row["outcome_yes"] is None:
                outcome = "early_exit"
                pnl_cell = row["pnl"]
            else:
                outcome = "yes" if row["outcome_yes"] else "no"
                pnl_cell = row["pnl"]
            writer.writerow(
                [
                    row["placed_at"][:10],
                    row["ticker"],
                    row["side"],
                    row["quantity"],
                    row["price"],
                    outcome,
                    pnl_cell,
                    row["settled_at"],
                ]
            )
    return len(rows)


def get_live_pnl_summary() -> dict:
    """Return live order P&L summary for the dashboard.

    Returns:
        today_pnl:     sum of pnl for live orders settled today (UTC),
                       excluding exit_reason='unmatched_sell' placeholders
        total_pnl:     sum of all settled live order pnl, same exclusion
        open_count:    count of open live positions -- see
                       count_open_live_positions() for the union this
                       delegates to
        settled_count: count of live orders with settled_at IS NOT NULL --
                       NOT exclusion-filtered (see AUD-0057 note below)

    AUD-0057: both SUMs exclude exit_reason='unmatched_sell' rows -- see
    export_live_tax_csv's matching docstring note. Those rows carry a
    documented pnl=0.0 placeholder (no tracked entry_price to compute a real
    P&L against), which would otherwise silently read as a genuine $0
    outcome in this dashboard summary.

    Opus review follow-up: settled_count deliberately does NOT get the same
    exclusion. An unmatched-sell row genuinely IS a settled live order (a
    real sell hit the exchange) -- only its P&L is unknown/placeholder, not
    its settled-ness. Applying the SUM exclusion via CASE (rather than a
    WHERE-clause AND, which would have silently dropped it from
    settled_count too) keeps that one true fact ("N live orders have
    settled") accurate while still not counting the placeholder's $0
    toward either P&L total.

    Batch-58 item 3 (backlog L24388): open_count was its own
    `status = 'pending'` COUNT, documenting the undercount as if it were
    intended -- the identical bug AUD-0009 fixed for
    order_executor._count_open_live_orders, with both gaps that entry named
    (filled-but-unsettled positions AND ambiguous 'unknown' placements)
    still present here. It now delegates to count_open_live_positions(),
    the shared definition the safety gate uses, so the dashboard stat and
    the gate can no longer disagree about what "open" means.

    Opus review (batch-58, L10): open_count is therefore read on its OWN
    connection, after this function's `with _conn()` block closes, rather
    than alongside the two P&L sums as it was before. A concurrent writer
    can make the returned dict internally inconsistent (a position settling
    between the two reads). Accepted deliberately for a dashboard stat --
    the alternative is either a nested connection or duplicating the union
    SQL here, and duplication is exactly what this item existed to remove.
    """
    init_log()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    _real_pnl = (
        "CASE WHEN exit_reason IS NULL OR exit_reason != 'unmatched_sell' "
        "THEN pnl ELSE 0 END"
    )
    with _conn() as con:
        today_row = con.execute(
            f"""
            SELECT COALESCE(SUM({_real_pnl}), 0.0) AS today_pnl
            FROM orders
            WHERE live = 1 AND settled_at LIKE ? AND pnl IS NOT NULL
            """,
            (f"{today}%",),
        ).fetchone()
        totals_row = con.execute(
            f"""
            SELECT COALESCE(SUM({_real_pnl}), 0.0) AS total_pnl,
                   COUNT(*) AS settled_count
            FROM orders
            WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL
            """,
        ).fetchone()
    return {
        "today_pnl": round(today_row["today_pnl"] or 0.0, 4),
        "total_pnl": round(totals_row["total_pnl"] or 0.0, 4),
        "open_count": count_open_live_positions(),
        "settled_count": totals_row["settled_count"] or 0,
    }


def get_recent_orders(limit: int = 50) -> list[dict]:
    """Return the most recent N order log entries."""
    init_log()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM orders ORDER BY placed_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def log_queue_position(
    exchange_order_id: str,
    ticker: str,
    queue_position: float | None,
    source: str,
    order_row_id: int | None = None,
) -> int:
    """Record one queue-position observation for a resting order.

    Batch-49 item 2: read-only fill-quality instrumentation. `source` is
    "placement" (logged once, right after a maker order is confirmed live)
    or "poll" (logged once per poll pass for each still-resting order, via
    the bulk queue_positions endpoint -- see order_executor._poll_pending_orders).

    Does NOT swallow errors itself (init_log()/the INSERT can both raise,
    e.g. a locked or corrupt DB) -- every call site wraps this in its own
    try/except per this repo's convention that instrumentation must never
    risk the trading-critical path it's observing (same reasoning as
    market_mid_at_fill's lookup in _poll_pending_orders); this function
    itself just does the write and lets the caller decide whether a
    logging failure is worth a warning.
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO queue_positions
              (order_row_id, exchange_order_id, ticker, queue_position, source, observed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_row_id,
                exchange_order_id,
                ticker,
                queue_position,
                source,
                datetime.now(UTC).isoformat(),
            ),
        )
        return cur.lastrowid or 0


def get_queue_position_history(exchange_order_id: str) -> list[dict]:
    """Return every logged queue-position observation for one exchange
    order, oldest first. Batch-49 item 2 -- makes the logged data queryable
    for the (separate, not-yet-built) reprice-decision backlog item this
    batch deliberately does not wire into."""
    init_log()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM queue_positions
            WHERE exchange_order_id = ?
            ORDER BY observed_at ASC
            """,
            (exchange_order_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_order_by_id(order_id: int | str) -> dict | None:
    """Fetch a single order record by id from execution_log.db."""
    init_log()
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT * FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            if row:
                return dict(row)
    except Exception as exc:
        _log.warning("get_order_by_id: %s", exc)
    return None


def append_entry(entry: dict, path: Path | None = None) -> None:
    """Append a single entry dict as a JSONL line to the entries log."""
    import json

    target = (
        Path(path) if path is not None else DB_PATH.parent / "execution_entries.jsonl"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with _append_lock:
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
