"""
Execution log — SQLite-backed audit trail of every live order attempt.
Prevents duplicate orders and provides a full history of what was sent to Kalshi.

Usage:
    from execution_log import log_order, get_recent_orders, was_recently_ordered
"""

from __future__ import annotations

import json
import sqlite3
import warnings
from datetime import UTC, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "execution_log.db"
DB_PATH.parent.mkdir(exist_ok=True)

_initialized = False


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # #98: same WAL pragmas as predictions DB
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_log() -> None:
    global _initialized
    if _initialized:
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
            status         TEXT,              -- "sent", "pending", "filled", "failed", "cancelled"
            response       TEXT,              -- JSON-encoded API response
            error          TEXT,              -- error message if failed
            placed_at      TEXT    NOT NULL,
            -- #75: structured columns for querying failures without JSON parsing
            fill_quantity  INTEGER,           -- contracts actually filled
            error_code     TEXT,              -- HTTP status or error type
            error_type     TEXT,              -- exception class name
            forecast_cycle TEXT,              -- forecast cycle for cycle-aware dedup
            live           INTEGER DEFAULT 0, -- 1 if this is a live order
            settled_at     TEXT,              -- ISO timestamp when settlement outcome was recorded
            outcome_yes    INTEGER,           -- 1 if YES side won, 0 if NO side won
            pnl            REAL               -- net P&L after Kalshi fee in dollars
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
    # Migration: add structured error columns for older DBs
    migrations = [
        "ALTER TABLE orders ADD COLUMN fill_quantity INTEGER",
        "ALTER TABLE orders ADD COLUMN error_code TEXT",
        "ALTER TABLE orders ADD COLUMN error_type TEXT",
        "ALTER TABLE orders ADD COLUMN forecast_cycle TEXT",
        "ALTER TABLE orders ADD COLUMN live INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN settled_at TEXT",
        "ALTER TABLE orders ADD COLUMN outcome_yes INTEGER",
        "ALTER TABLE orders ADD COLUMN pnl REAL",
    ]
    with _conn() as con:
        for stmt in migrations:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass
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
) -> int:
    """
    Record a live order attempt. Returns the new row ID.
    Call with status='sent' before placing, then update with log_order_result().
    """
    init_log()
    with _conn() as con:
        cur = con.execute(
            """
            INSERT INTO orders
              (ticker, side, quantity, price, order_type, status, response, error,
               placed_at, fill_quantity, error_code, error_type, forecast_cycle, live)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
) -> None:
    """Update an existing order log entry with the final status/response.
    #5/#75: structured error fields allow querying failures without parsing JSON.
    """
    init_log()
    with _conn() as con:
        con.execute(
            """UPDATE orders SET
               status=?, response=?, error=?,
               fill_quantity=?, error_code=?, error_type=?
               WHERE id=?""",
            (
                status,
                json.dumps(response) if response else None,
                error,
                fill_quantity,
                error_code,
                error_type,
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
        row = con.execute(
            """
            SELECT 1 FROM orders
            WHERE ticker = ? AND side = ? AND status != 'failed'
              AND placed_at >= datetime('now', ?)
            LIMIT 1
            """,
            (ticker, side, f"-{within_minutes} minutes"),
        ).fetchone()
    return row is not None


def was_traded_today(ticker: str, side: str) -> bool:
    """
    Return True if this ticker+side was ordered (any status) today (UTC).
    Prevents trading the same market+side multiple times per calendar day (P1.5).
    """
    init_log()
    today = datetime.now(UTC).date().isoformat()
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM orders WHERE ticker=? AND side=? AND placed_at LIKE ? LIMIT 1",
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


def get_today_live_loss() -> float:
    """Return today's accumulated live loss in dollars (UTC date). Returns 0.0 if no row."""
    init_log()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _conn() as con:
        row = con.execute(
            "SELECT total FROM daily_live_loss WHERE date = ?", (today,)
        ).fetchone()
    return row["total"] if row else 0.0


def add_live_loss(amount: float) -> float:
    """Add amount to today's live loss total and return the new total.

    amount > 0 means a cost (order placed, loss settled).
    amount < 0 means a gain (winning settlement).
    Uses INSERT ... ON CONFLICT so concurrent calls are safe.
    """
    init_log()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    now_iso = datetime.now(UTC).isoformat()
    try:
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
        return row["total"] if row else amount
    except Exception as exc:
        warnings.warn(f"add_live_loss DB write failed: {exc}")
        try:
            return get_today_live_loss()
        except Exception:
            return 0.0


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
            writer.writerow(
                [
                    row["placed_at"][:10],
                    row["ticker"],
                    row["side"],
                    row["quantity"],
                    row["price"],
                    "yes" if row["outcome_yes"] else "no",
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
            WHERE live = 1 AND settled_at LIKE ?
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


def append_entry(entry: dict, path: Path | None = None) -> None:
    """Write a single entry dict as a JSON file using safe_io for resilient disk writes (#8)."""
    import safe_io

    target = (
        Path(path) if path is not None else DB_PATH.parent / "execution_entries.json"
    )
    safe_io.atomic_write_json(entry, target)
