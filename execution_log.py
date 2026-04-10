"""
Execution log — SQLite-backed audit trail of every live order attempt.
Prevents duplicate orders and provides a full history of what was sent to Kalshi.

Usage:
    from execution_log import log_order, get_recent_orders, was_recently_ordered
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "execution_log.db"
DB_PATH.parent.mkdir(exist_ok=True)

_initialized = False


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_log() -> None:
    global _initialized
    if _initialized:
        return
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker       TEXT    NOT NULL,
            side         TEXT    NOT NULL,   -- "yes" or "no"
            quantity     INTEGER NOT NULL,
            price        REAL    NOT NULL,
            order_type   TEXT,              -- "market" or "limit"
            status       TEXT,              -- "sent", "filled", "failed", "cancelled"
            response     TEXT,              -- JSON-encoded API response
            error        TEXT,              -- error message if failed
            placed_at    TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_orders_ticker ON orders(ticker, placed_at);
        """)
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
              (ticker, side, quantity, price, order_type, status, response, error, placed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        return cur.lastrowid or 0


def log_order_result(
    row_id: int, status: str, response: dict | None = None, error: str | None = None
) -> None:
    """Update an existing order log entry with the final status/response."""
    init_log()
    with _conn() as con:
        con.execute(
            "UPDATE orders SET status=?, response=?, error=? WHERE id=?",
            (
                status,
                json.dumps(response) if response else None,
                error,
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


def get_recent_orders(limit: int = 50) -> list[dict]:
    """Return the most recent N order log entries."""
    init_log()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM orders ORDER BY placed_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
