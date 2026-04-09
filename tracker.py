"""
Prediction tracker — SQLite-backed log of every prediction we make.
After markets settle, records outcomes so we can:
  - Compute Brier scores (are our probabilities well-calibrated?)
  - Detect per-city/season bias and correct for it
  - Show a history of past calls
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "predictions.db"
DB_PATH.parent.mkdir(exist_ok=True)


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker        TEXT    NOT NULL,
            city          TEXT,
            market_date   TEXT,
            condition_type TEXT,
            threshold_lo  REAL,
            threshold_hi  REAL,
            our_prob      REAL,
            market_prob   REAL,
            edge          REAL,
            method        TEXT,
            n_members     INTEGER,
            predicted_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            ticker        TEXT    PRIMARY KEY,
            settled_yes   INTEGER NOT NULL,   -- 1 = YES won, 0 = NO won
            settled_at    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pred_ticker ON predictions(ticker);
        CREATE INDEX IF NOT EXISTS idx_pred_city   ON predictions(city, market_date);
        """)


# ── Logging ───────────────────────────────────────────────────────────────────


def log_prediction(
    ticker: str, city: str | None, market_date: date | None, analysis: dict
) -> None:
    """Save a prediction to the database."""
    init_db()
    cond = analysis.get("condition", {})
    lo = cond.get("threshold", cond.get("lower"))
    hi = cond.get("threshold", cond.get("upper"))

    with _conn() as con:
        # Don't duplicate — update if already logged today
        existing = con.execute(
            "SELECT id FROM predictions WHERE ticker = ? AND date(predicted_at) = date('now')",
            (ticker,),
        ).fetchone()
        if existing:
            con.execute(
                """
                UPDATE predictions SET
                    our_prob=?, market_prob=?, edge=?, method=?, n_members=?
                WHERE id=?
            """,
                (
                    analysis.get("forecast_prob"),
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                    existing["id"],
                ),
            )
        else:
            con.execute(
                """
                INSERT INTO predictions
                  (ticker, city, market_date, condition_type,
                   threshold_lo, threshold_hi, our_prob, market_prob,
                   edge, method, n_members, predicted_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            """,
                (
                    ticker,
                    city,
                    market_date.isoformat() if market_date else None,
                    cond.get("type"),
                    lo,
                    hi,
                    analysis.get("forecast_prob"),
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                ),
            )


def log_outcome(ticker: str, settled_yes: bool) -> None:
    """Record whether a market settled YES or NO."""
    init_db()
    with _conn() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO outcomes (ticker, settled_yes, settled_at)
            VALUES (?, ?, datetime('now'))
        """,
            (ticker, 1 if settled_yes else 0),
        )


# ── Bias correction ───────────────────────────────────────────────────────────


def get_bias(city: str | None, month: int | None, min_samples: int = 20) -> float:
    """
    Compute systematic bias for a city/month: mean(our_prob - actual_outcome).
    Positive bias means we consistently over-estimate; negative = under-estimate.
    Returns 0.0 if insufficient data.
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """
        params: list = []
        if city:
            query += " AND p.city = ?"
            params.append(city)
        if month:
            query += " AND strftime('%m', p.market_date) = ?"
            params.append(f"{month:02d}")

        rows = con.execute(query, params).fetchall()

    if len(rows) < min_samples:
        return 0.0

    bias = sum(r["our_prob"] - r["settled_yes"] for r in rows) / len(rows)
    return bias


# ── History + Brier scoring ───────────────────────────────────────────────────


def brier_score_by_method(min_samples: int = 20) -> dict[str, float]:
    """
    Brier score broken down by method string (e.g. 'ensemble', 'normal_dist').
    Returns {method: brier} for methods with enough data.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.method, p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.method IS NOT NULL
        """).fetchall()

    by_method: dict[str, list] = {}
    for r in rows:
        by_method.setdefault(r["method"], []).append(
            (r["our_prob"] - r["settled_yes"]) ** 2
        )
    return {
        m: sum(errs) / len(errs)
        for m, errs in by_method.items()
        if len(errs) >= min_samples
    }


def brier_score(city: str | None = None) -> float | None:
    """
    Brier score = mean((our_prob - outcome)²).
    Lower is better. 0.25 = random, 0.0 = perfect.
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """
        params: list = []
        if city:
            query += " AND p.city = ?"
            params.append(city)
        rows = con.execute(query, params).fetchall()

    if not rows:
        return None
    return sum((r["our_prob"] - r["settled_yes"]) ** 2 for r in rows) / len(rows)


def get_history(limit: int = 50) -> list[dict]:
    """Return recent predictions with outcomes where available."""
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                p.ticker, p.city, p.market_date, p.condition_type,
                p.threshold_lo, p.threshold_hi,
                p.our_prob, p.market_prob, p.edge,
                p.method, p.predicted_at,
                o.settled_yes
            FROM predictions p
            LEFT JOIN outcomes o ON p.ticker = o.ticker
            ORDER BY p.predicted_at DESC
            LIMIT ?
        """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_calibration_trend(weeks: int = 8) -> list[dict]:
    """
    Brier score grouped by ISO week for the last N weeks.
    Returns [{week, brier, n}, ...] oldest first.
    Only includes weeks with at least one settled prediction.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT
                strftime('%Y-W%W', p.predicted_at) AS week,
                p.our_prob,
                o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
            ORDER BY week ASC
        """).fetchall()

    by_week: dict[str, list[float]] = {}
    for r in rows:
        by_week.setdefault(r["week"], []).append(
            (r["our_prob"] - r["settled_yes"]) ** 2
        )

    result = []
    for week, errors in sorted(by_week.items())[-weeks:]:
        result.append(
            {
                "week": week,
                "brier": sum(errors) / len(errors),
                "n": len(errors),
            }
        )
    return result


def get_calibration_by_city() -> dict[str, dict]:
    """
    Per-city Brier score and sample count.
    Returns {city: {brier, n, bias}} for cities with settled predictions.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.city, p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.city IS NOT NULL
        """).fetchall()

    by_city: dict[str, list] = {}
    for r in rows:
        by_city.setdefault(r["city"], []).append((r["our_prob"], r["settled_yes"]))

    result = {}
    for city, pairs in by_city.items():
        errors = [(p - y) ** 2 for p, y in pairs]
        biases = [p - y for p, y in pairs]
        result[city] = {
            "brier": sum(errors) / len(errors),
            "bias": sum(biases) / len(biases),
            "n": len(pairs),
        }
    return result


def get_calibration_by_type() -> dict[str, dict]:
    """
    Per condition-type Brier score, bias, and sample count.
    Returns {condition_type: {brier, bias, n}} for types with settled predictions.
    Condition types include: above, below, between, precip_any, precip_above.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.condition_type, p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.condition_type IS NOT NULL
        """).fetchall()

    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r["condition_type"], []).append(
            (r["our_prob"], r["settled_yes"])
        )

    result = {}
    for ctype, pairs in by_type.items():
        errors = [(p - y) ** 2 for p, y in pairs]
        biases = [p - y for p, y in pairs]
        result[ctype] = {
            "brier": sum(errors) / len(errors),
            "bias": sum(biases) / len(biases),
            "n": len(pairs),
        }
    return result


def export_predictions_csv(path: str) -> int:
    """Export prediction history with outcomes to CSV. Returns row count."""
    import csv

    rows = get_history(limit=10_000)
    if not rows:
        return 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])
    return len(rows)


def sync_outcomes(client) -> int:
    """
    Check settled markets in the DB against Kalshi and record outcomes.
    Returns number of new outcomes recorded.
    """
    init_db()
    with _conn() as con:
        pending = con.execute("""
            SELECT DISTINCT ticker FROM predictions p
            WHERE NOT EXISTS (SELECT 1 FROM outcomes o WHERE o.ticker = p.ticker)
        """).fetchall()

    count = 0
    for row in pending:
        ticker = row["ticker"]
        try:
            market = client.get_market(ticker)
            status = market.get("status", "")
            result = market.get("result", "")
            if status == "finalized":
                settled_yes = result == "yes"
                log_outcome(ticker, settled_yes)
                count += 1
        except Exception:
            continue
    return count
