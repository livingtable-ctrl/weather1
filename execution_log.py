"""
Execution log — SQLite-backed audit trail of every live order attempt.
Prevents duplicate orders and provides a full history of what was sent to Kalshi.

Usage:
    from execution_log import log_order, get_recent_orders, was_recently_ordered
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading as _el_threading
from datetime import UTC, datetime
from pathlib import Path

from utils import sql_normalize_iso_column

_log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "execution_log.db"
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
_SCHEMA_VERSION = 16  # increment when _MIGRATIONS list grows

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


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    return con


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
                status         TEXT,              -- "sent", "pending", "filled", "failed", "canceled"
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
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO orders
              (ticker, side, quantity, price, order_type, status, response, error,
               placed_at, fill_quantity, error_code, error_type, forecast_cycle, live,
               close_time, replaces_order_id, entry_prob)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    """
    init_log()
    with _conn() as con:
        con.execute(
            """UPDATE orders SET
               status=?, response=?, error=?,
               fill_quantity=?, error_code=?, error_type=?,
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


def get_filled_unsettled_live_orders() -> list[dict]:
    """Return live filled orders that have not yet had their settlement outcome recorded."""
    init_log()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT * FROM orders
            WHERE live = 1 AND status = 'filled' AND settled_at IS NULL
            ORDER BY placed_at
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def record_live_settlement(order_id: int, outcome_yes: bool, pnl: float) -> None:
    """Write settlement outcome to an order row.

    outcome_yes=True means the YES side won (the market resolved 'yes').
    pnl is net P&L after Kalshi fee, in dollars.
    """
    init_log()
    with _conn() as con:
        con.execute(
            """
            UPDATE orders
            SET settled_at = ?, outcome_yes = ?, pnl = ?
            WHERE id = ?
            """,
            (datetime.now(UTC).isoformat(), int(outcome_yes), pnl, order_id),
        )


def update_live_peak_profit(order_id: int, peak_profit_pct: float) -> None:
    """Record a new peak unrealized-profit fraction for an open live position
    (mirrors paper.py's peak_profit_pct tracking, used by the breakeven-stop
    check). Caller is responsible for only calling this when the new value is
    actually higher than the stored one -- this just writes whatever it's given.
    """
    init_log()
    with _conn() as con:
        con.execute(
            "UPDATE orders SET peak_profit_pct = ? WHERE id = ?",
            (peak_profit_pct, order_id),
        )


def record_live_early_exit(
    order_id: int, exit_price: float, exit_reason: str, pnl: float
) -> None:
    """Mark an open live position closed via an early protective exit
    (stop-loss/breakeven/model-exit), as opposed to natural market
    settlement. Sets settled_at (so get_filled_unsettled_live_orders() stops
    treating this row as open) but deliberately leaves outcome_yes NULL --
    the underlying market hasn't actually resolved yet, we just closed our
    own position early; there is no real "yes won" / "no won" fact to record
    here. pnl is the realized net P&L (already fee-adjusted) from this exit.
    """
    init_log()
    with _conn() as con:
        con.execute(
            """
            UPDATE orders
            SET settled_at = ?, exit_price = ?, exit_reason = ?, pnl = ?
            WHERE id = ?
            """,
            (datetime.now(UTC).isoformat(), exit_price, exit_reason, pnl, order_id),
        )


def export_live_tax_csv(path: str, tax_year: int | None = None) -> int:
    """Export settled live orders to CSV for tax reporting.

    Filters to live=1, settled_at IS NOT NULL, pnl IS NOT NULL.
    If tax_year is provided, filters to rows where settled_at starts with that year.

    CSV columns: date, ticker, side, quantity, entry_price, outcome, pnl, settled_at
    Returns count of rows written.
    """
    import csv

    init_log()
    with _conn() as con:
        if tax_year is not None:
            rows = con.execute(
                """
                SELECT placed_at, ticker, side, quantity, price,
                       outcome_yes, pnl, settled_at
                FROM orders
                WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL
                  AND settled_at LIKE ?
                ORDER BY settled_at
                """,
                (f"{tax_year}%",),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT placed_at, ticker, side, quantity, price,
                       outcome_yes, pnl, settled_at
                FROM orders
                WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL
                ORDER BY settled_at
                """,
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
            if row["outcome_yes"] is None:
                outcome = "early_exit"
            else:
                outcome = "yes" if row["outcome_yes"] else "no"
            writer.writerow(
                [
                    row["placed_at"][:10],
                    row["ticker"],
                    row["side"],
                    row["quantity"],
                    row["price"],
                    outcome,
                    row["pnl"],
                    row["settled_at"],
                ]
            )
    return len(rows)


def get_live_pnl_summary() -> dict:
    """Return live order P&L summary for the dashboard.

    Returns:
        today_pnl:     sum of pnl for live orders settled today (UTC)
        total_pnl:     sum of all settled live order pnl
        open_count:    count of live orders with status='pending'
        settled_count: count of live orders with settled_at IS NOT NULL
    """
    init_log()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _conn() as con:
        today_row = con.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS today_pnl
            FROM orders
            WHERE live = 1 AND settled_at LIKE ? AND pnl IS NOT NULL
            """,
            (f"{today}%",),
        ).fetchone()
        totals_row = con.execute(
            """
            SELECT COALESCE(SUM(pnl), 0.0) AS total_pnl,
                   COUNT(*) AS settled_count
            FROM orders
            WHERE live = 1 AND settled_at IS NOT NULL AND pnl IS NOT NULL
            """,
        ).fetchone()
        open_row = con.execute(
            """
            SELECT COUNT(*) AS open_count
            FROM orders
            WHERE live = 1 AND status = 'pending'
            """,
        ).fetchone()
    return {
        "today_pnl": round(today_row["today_pnl"] or 0.0, 4),
        "total_pnl": round(totals_row["total_pnl"] or 0.0, 4),
        "open_count": open_row["open_count"] or 0,
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


def get_order_by_id(order_id: str) -> dict | None:
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
