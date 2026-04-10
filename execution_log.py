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
            status         TEXT,              -- "sent", "filled", "failed", "cancelled"
            response       TEXT,              -- JSON-encoded API response
            error          TEXT,              -- error message if failed
            placed_at      TEXT    NOT NULL,
            -- #75: structured columns for querying failures without JSON parsing
            fill_quantity  INTEGER,           -- contracts actually filled
            error_code     TEXT,              -- HTTP status or error type
            error_type     TEXT               -- exception class name
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
