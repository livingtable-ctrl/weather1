"""
Prediction tracker — SQLite-backed log of every prediction we make.
After markets settle, records outcomes so we can:
  - Compute Brier scores (are our probabilities well-calibrated?)
  - Detect per-city/season bias and correct for it
  - Show a history of past calls
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import date, datetime
from pathlib import Path

_log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "predictions.db"
DB_PATH.parent.mkdir(exist_ok=True)

_db_initialized = False

_SCHEMA_VERSION = 9  # increment when _MIGRATIONS list grows

_MIGRATIONS = [
    # v1 → v2: add condition_type column (if not already added)
    "ALTER TABLE predictions ADD COLUMN condition_type TEXT",
    # v2 → v3: ensure api_requests table exists
    """CREATE TABLE IF NOT EXISTS api_requests (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        method      TEXT NOT NULL,
        endpoint    TEXT NOT NULL,
        status_code INTEGER,
        latency_ms  REAL,
        logged_at   TEXT NOT NULL
    )""",
    # v3 → v4: add forecast_cycle column (#37)
    "ALTER TABLE predictions ADD COLUMN forecast_cycle TEXT",
    # v4 → v5: price improvement tracking table (#65)
    """CREATE TABLE IF NOT EXISTS price_improvement (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker        TEXT    NOT NULL,
        desired_price REAL    NOT NULL,
        actual_price  REAL    NOT NULL,
        improvement   REAL    NOT NULL,
        quantity      INTEGER NOT NULL,
        side          TEXT    NOT NULL,
        logged_at     TEXT    NOT NULL
    )""",
    # v5 → v6: add blend_sources column to predictions (#84)
    "ALTER TABLE predictions ADD COLUMN blend_sources TEXT",
    # v6 → v7: unselected bias tracking (#55)
    """CREATE TABLE IF NOT EXISTS analysis_attempts (
        ticker TEXT NOT NULL,
        city TEXT,
        condition TEXT,
        target_date TEXT,
        analyzed_at TEXT,
        forecast_prob REAL,
        market_prob REAL,
        days_out INTEGER,
        was_traded INTEGER DEFAULT 0,
        outcome INTEGER,
        PRIMARY KEY (ticker, target_date)
    )""",
    # v7 → v8: add error column to api_requests (#69)
    "ALTER TABLE api_requests ADD COLUMN error TEXT",
    # v8 → v9: per-source probabilities for blend weight calibration (#118/#122)
    "ALTER TABLE predictions ADD COLUMN ensemble_prob REAL",
    "ALTER TABLE predictions ADD COLUMN nws_prob REAL",
    "ALTER TABLE predictions ADD COLUMN clim_prob REAL",
]


def _run_migrations(con: sqlite3.Connection) -> None:
    """Apply any pending schema migrations and update schema_version (#99)."""
    # Keep schema_version table for backward compatibility
    con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")

    # Use PRAGMA user_version as the authoritative migration cursor (#99)
    current = con.execute("PRAGMA user_version").fetchone()[0]

    for i, sql in enumerate(_MIGRATIONS):
        version = i + 1
        if version <= current:
            continue
        try:
            con.execute(sql)
            _log.info("Applied migration v%d", version)
        except Exception as e:
            err_str = str(e).lower()
            if "duplicate column" in err_str or "already exists" in err_str:
                _log.debug("Migration v%d already applied: %s", version, e)
            else:
                raise

    # Update PRAGMA user_version to reflect applied migrations
    con.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    # Keep schema_version table in sync for backward compatibility
    row = con.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        con.execute("INSERT INTO schema_version VALUES (?)", (_SCHEMA_VERSION,))
    else:
        con.execute("UPDATE schema_version SET version=?", (_SCHEMA_VERSION,))


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # #98: WAL mode for better concurrency + performance
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=10000")
    return con


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS ensemble_member_scores (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            city           TEXT NOT NULL,
            model          TEXT NOT NULL,
            predicted_temp REAL,
            actual_temp    REAL,
            target_date    TEXT,
            logged_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ems_city_model
            ON ensemble_member_scores(city, model);

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
            predicted_at  TEXT    NOT NULL,
            days_out      INTEGER
        );

        CREATE TABLE IF NOT EXISTS outcomes (
            ticker        TEXT    PRIMARY KEY,
            settled_yes   INTEGER NOT NULL,   -- 1 = YES won, 0 = NO won
            settled_at    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_pred_ticker    ON predictions(ticker);
        CREATE INDEX IF NOT EXISTS idx_pred_city      ON predictions(city, market_date);
        CREATE INDEX IF NOT EXISTS idx_pred_condition ON predictions(condition_type);
        CREATE INDEX IF NOT EXISTS idx_pred_method    ON predictions(method);
        CREATE INDEX IF NOT EXISTS idx_out_settled_at ON outcomes(settled_at);

        CREATE TABLE IF NOT EXISTS source_reliability (
            city        TEXT NOT NULL,
            source      TEXT NOT NULL,
            logged_date TEXT NOT NULL,
            success     INTEGER NOT NULL,
            PRIMARY KEY (city, source, logged_date)
        );
        CREATE INDEX IF NOT EXISTS idx_src_city ON source_reliability(city, source);

        -- #110: audit trail for manual trades placed via the CLI
        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            action     TEXT    NOT NULL,   -- e.g. "manual_buy"
            ticker     TEXT,
            side       TEXT,
            price      REAL,
            qty        INTEGER,
            thesis     TEXT,
            logged_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_ticker ON audit_log(ticker);

        -- #69: audit trail for every outbound API call (latency + status monitoring)
        CREATE TABLE IF NOT EXISTS api_requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            method      TEXT NOT NULL,
            endpoint    TEXT NOT NULL,
            status_code INTEGER,
            latency_ms  REAL,
            logged_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_api_endpoint ON api_requests(endpoint, logged_at);
        """)
    # #99: versioned migrations replacing ad-hoc ALTER TABLE try/except blocks
    # Also handles legacy columns (days_out, raw_prob) via the CREATE TABLE schema above
    with _conn() as con:
        # Legacy ad-hoc migrations — keep for existing DBs without schema_version
        for stmt in [
            "ALTER TABLE predictions ADD COLUMN days_out INTEGER",
            "ALTER TABLE predictions ADD COLUMN raw_prob REAL",
        ]:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass  # Column already exists
        _run_migrations(con)

    _db_initialized = True


# ── Logging ───────────────────────────────────────────────────────────────────


def log_api_request(
    method: str,
    endpoint: str,
    status_code: int | None,
    latency_ms: float,
    error: str | None = None,
) -> None:
    """Log an API call for audit trail and latency monitoring (#69)."""
    from datetime import UTC

    init_db()
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO api_requests (method, endpoint, status_code, latency_ms, logged_at, error) VALUES (?,?,?,?,?,?)",
                (
                    method,
                    endpoint,
                    status_code,
                    latency_ms,
                    datetime.now(UTC).isoformat(),
                    error,
                ),
            )
    except Exception as exc:
        _log.warning("Failed to log API request: %s", exc)


def log_audit(
    action: str,
    ticker: str | None = None,
    side: str | None = None,
    price: float | None = None,
    qty: int | None = None,
    thesis: str | None = None,
) -> None:
    """
    #110: Write a row to the audit_log table for any manual user action
    (e.g. manual paper buys placed via _quick_paper_buy).
    Never raises — audit failures must not interrupt the trading flow.
    """
    from datetime import UTC, datetime

    init_db()
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO audit_log
                   (action, ticker, side, price, qty, thesis, logged_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    action,
                    ticker,
                    side,
                    price,
                    qty,
                    thesis,
                    datetime.now(UTC).isoformat(),
                ),
            )
    except Exception:
        pass


def log_prediction(
    ticker: str,
    city: str | None,
    market_date: date | None,
    analysis: dict,
    forecast_cycle: str | None = None,
    blend_sources: dict | None = None,
    ensemble_prob: float | None = None,
    nws_prob: float | None = None,
    clim_prob: float | None = None,
) -> None:
    """Save a prediction to the database.
    Stores both the raw (pre-bias-correction) probability and the adjusted one (#53).
    #37: Optionally stores the NWP forecast cycle (00z/06z/12z/18z).
    #84: Optionally stores blend_sources dict (model weights) as JSON.
    """
    import json as _json

    init_db()
    cond = analysis.get("condition", {})
    lo = cond.get("threshold", cond.get("lower"))
    hi = cond.get("threshold", cond.get("upper"))
    days_out = (market_date - date.today()).days if market_date is not None else None
    # #53: raw_prob is pre-bias-correction; forecast_prob is the adjusted value
    bias = analysis.get("bias_correction", 0.0) or 0.0
    forecast_prob = analysis.get("forecast_prob")
    raw_prob = round(forecast_prob + bias, 6) if forecast_prob is not None else None
    blend_sources_json = (
        _json.dumps(blend_sources) if blend_sources is not None else None
    )

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
                    our_prob=?, raw_prob=?, market_prob=?, edge=?, method=?, n_members=?,
                    days_out=?, forecast_cycle=?, blend_sources=?,
                    ensemble_prob=?, nws_prob=?, clim_prob=?
                WHERE id=?
            """,
                (
                    forecast_prob,
                    raw_prob,
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                    days_out,
                    forecast_cycle,
                    blend_sources_json,
                    ensemble_prob,
                    nws_prob,
                    clim_prob,
                    existing["id"],
                ),
            )
        else:
            con.execute(
                """
                INSERT INTO predictions
                  (ticker, city, market_date, condition_type,
                   threshold_lo, threshold_hi, our_prob, raw_prob, market_prob,
                   edge, method, n_members, predicted_at, days_out, forecast_cycle,
                   blend_sources, ensemble_prob, nws_prob, clim_prob)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?,?,?,?)
            """,
                (
                    ticker,
                    city,
                    market_date.isoformat() if market_date else None,
                    cond.get("type"),
                    lo,
                    hi,
                    forecast_prob,
                    raw_prob,
                    analysis.get("market_prob"),
                    analysis.get("edge"),
                    analysis.get("method"),
                    analysis.get("n_members"),
                    days_out,
                    forecast_cycle,
                    blend_sources_json,
                    ensemble_prob,
                    nws_prob,
                    clim_prob,
                ),
            )


def log_outcome(ticker: str, settled_yes: bool) -> bool:
    """Record whether a market settled YES or NO.
    Returns True if newly recorded, False if outcome already existed (#17).
    Refuses to overwrite an existing finalized outcome to prevent data corruption.
    """
    init_db()
    with _conn() as con:
        existing = con.execute(
            "SELECT 1 FROM outcomes WHERE ticker = ?", (ticker,)
        ).fetchone()
        if existing:
            return False  # already settled; refuse duplicate
        con.execute(
            """
            INSERT INTO outcomes (ticker, settled_yes, settled_at)
            VALUES (?, ?, datetime('now'))
        """,
            (ticker, 1 if settled_yes else 0),
        )
    return True


# ── Bias correction ───────────────────────────────────────────────────────────


def get_bias(
    city: str | None,
    month: int | None,
    min_samples: int = 5,
    condition_type: str | None = None,
) -> float:
    """
    Compute systematic bias for a city/month: weighted mean(our_prob - actual_outcome).
    Weights each sample by exp(-age_days / 30) so recent predictions count more.
    Positive bias means we consistently over-estimate; negative = under-estimate.
    Returns 0.0 if insufficient data (raw count < min_samples).
    Optionally filter by condition_type (#10).
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT p.our_prob, o.settled_yes, p.predicted_at
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
        if condition_type is not None:
            query += " AND p.condition_type = ?"
            params.append(condition_type)

        rows = con.execute(query, params).fetchall()

    if len(rows) < min_samples:
        return 0.0

    now = datetime.utcnow()
    weighted_bias = 0.0
    total_weight = 0.0
    min_age_days = float("inf")
    for r in rows:
        try:
            predicted_at = datetime.fromisoformat(
                r["predicted_at"].replace("Z", "+00:00")
            )
            if predicted_at.tzinfo is not None:
                predicted_at = predicted_at.replace(tzinfo=None)
            age_days = max(0.0, (now - predicted_at).total_seconds() / 86400)
        except (ValueError, TypeError, AttributeError):
            age_days = 0.0
        min_age_days = min(min_age_days, age_days)
        weight = math.exp(-age_days / 30.0)
        weighted_bias += (r["our_prob"] - r["settled_yes"]) * weight
        total_weight += weight

    # #9: if most recent sample is >14 days old, bias estimate is stale — don't apply
    if min_age_days > 14:
        return 0.0

    if total_weight == 0:
        return 0.0
    return weighted_bias / total_weight


def get_brier_by_days_out() -> dict[str, float]:
    """
    Brier score segmented by forecast horizon.
    Returns {"0-2d": brier, "3-5d": brier, "6-10d": brier, "11+d": brier}
    Only buckets with >= 5 settled predictions are included.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes, p.days_out
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.days_out IS NOT NULL
        """).fetchall()

    buckets: dict[str, list[float]] = {"0-2d": [], "3-5d": [], "6-10d": [], "11+d": []}
    for r in rows:
        d = r["days_out"]
        err = (r["our_prob"] - r["settled_yes"]) ** 2
        if d <= 2:
            buckets["0-2d"].append(err)
        elif d <= 5:
            buckets["3-5d"].append(err)
        elif d <= 10:
            buckets["6-10d"].append(err)
        else:
            buckets["11+d"].append(err)

    return {k: sum(v) / len(v) for k, v in buckets.items() if len(v) >= 5}


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


def get_component_attribution() -> dict[str, dict]:
    """#84: Brier score broken down by dominant blend source.

    For each settled prediction that has blend_sources recorded, identify the
    dominant model (highest weight) and compute per-source Brier scores.
    Returns {source: {"n": int, "brier": float}}.
    """
    import json as _json

    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, p.blend_sources, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND p.blend_sources IS NOT NULL
              AND o.settled_yes IS NOT NULL
        """).fetchall()

    by_source: dict[str, list[float]] = {}
    for r in rows:
        try:
            sources: dict = _json.loads(r["blend_sources"])
            if not sources:
                continue
            dominant = max(sources, key=lambda k: sources[k])
            err = (r["our_prob"] - r["settled_yes"]) ** 2
            by_source.setdefault(dominant, []).append(err)
        except Exception:
            continue

    return {
        src: {"n": len(errs), "brier": sum(errs) / len(errs)}
        for src, errs in by_source.items()
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


def get_brier_over_time(weeks: int = 12) -> list[dict]:
    """Return mean Brier score per ISO week for the last `weeks` weeks.

    Joins settled predictions with outcomes, groups by strftime('%Y-W%W', predicted_at),
    computes mean (our_prob - settled_yes)^2 per week.

    Returns [{"week": "2025-W40", "brier": 0.21}, ...] sorted ascending.
    Returns an empty list if no settled predictions exist in the window.
    """
    import datetime

    init_db()
    cutoff = (
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(weeks=weeks)
    ).isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                strftime('%Y-W%W', p.predicted_at) AS week,
                AVG(
                    (p.our_prob - o.settled_yes) * (p.our_prob - o.settled_yes)
                ) AS brier
            FROM predictions p
            JOIN outcomes o ON o.ticker = p.ticker
            WHERE p.predicted_at >= ?
              AND p.our_prob IS NOT NULL
            GROUP BY week
            ORDER BY week
            """,
            (cutoff,),
        ).fetchall()
    return [{"week": row["week"], "brier": round(row["brier"], 4)} for row in rows]


def brier_skill_score(city: str | None = None) -> float | None:
    """
    Brier Skill Score (BSS) vs market baseline (#11).
    BSS = 1 - (BS_model / BS_reference) where reference uses market_prob as prediction.
    Returns None if < 10 samples with both our_prob and market_prob.
    BSS > 0 means our model beats the market; BSS = 0 means equal to market.
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT p.our_prob, p.market_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.market_prob IS NOT NULL
        """
        params: list = []
        if city:
            query += " AND p.city = ?"
            params.append(city)
        rows = con.execute(query, params).fetchall()

    if len(rows) < 10:
        return None

    bs_model = sum((r["our_prob"] - r["settled_yes"]) ** 2 for r in rows) / len(rows)
    bs_ref = sum((r["market_prob"] - r["settled_yes"]) ** 2 for r in rows) / len(rows)

    if bs_ref == 0:
        return None  # avoid division by zero

    return round(1.0 - bs_model / bs_ref, 6)


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
    Brier score grouped by ISO week of the MARKET DATE for the last N weeks.
    Groups by market_date (not predicted_at) so the trend reflects when the
    weather event occurred, not when the analysis was run (#54).
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT
                strftime('%Y-W%W', p.market_date) AS week,
                p.our_prob,
                o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND p.market_date IS NOT NULL
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


def get_calibration_by_city(
    condition_type: str | None = None,
) -> dict[str, dict]:
    """
    Per-city Brier score and sample count (#54, #56).
    Returns {city: {brier, n, bias}} for cities with settled predictions.
    Optionally filter by condition_type.
    Monthly bias grouping uses market_date (not predicted_at) to avoid timezone skew.
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT p.city, p.our_prob, o.settled_yes,
                   CAST(strftime('%m', p.market_date) AS INTEGER) AS month
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.city IS NOT NULL
        """
        params: list = []
        if condition_type is not None:
            query += " AND p.condition_type = ?"
            params.append(condition_type)
        rows = con.execute(query, params).fetchall()

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


def get_calibration_by_season() -> dict[str, dict]:
    """
    Brier score and bias broken down by meteorological season (#59).
    Returns {season: {brier, bias, n}} for seasons with settled predictions.
    Seasons: Spring (Mar-May), Summer (Jun-Aug), Fall (Sep-Nov), Winter (Dec-Feb).
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes,
                   CAST(strftime('%m', p.market_date) AS INTEGER) AS month
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.market_date IS NOT NULL
        """).fetchall()

    def _season(month: int) -> str:
        if month in (3, 4, 5):
            return "Spring"
        elif month in (6, 7, 8):
            return "Summer"
        elif month in (9, 10, 11):
            return "Fall"
        else:
            return "Winter"

    by_season: dict[str, list] = {}
    for r in rows:
        if r["month"]:
            s = _season(r["month"])
            by_season.setdefault(s, []).append((r["our_prob"], r["settled_yes"]))

    result = {}
    for season, pairs in by_season.items():
        errors = [(p - y) ** 2 for p, y in pairs]
        biases = [p - y for p, y in pairs]
        result[season] = {
            "brier": round(sum(errors) / len(errors), 4),
            "bias": round(sum(biases) / len(biases), 4),
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


def log_source_attempt(city: str, source: str, success: bool) -> None:
    """
    Record whether a forecast source returned usable data for a city today.
    Uses INSERT OR REPLACE so only the last status per city/source/day is kept.
    """
    init_db()
    with _conn() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO source_reliability
              (city, source, logged_date, success)
            VALUES (?, ?, date('now'), ?)
            """,
            (city, source, 1 if success else 0),
        )


def get_source_reliability(city: str | None = None, days: int = 30) -> dict:
    """
    Return per-city, per-source reliability over the last N days.
    Returns {city: {source: {successes, failures, rate, total}}}.
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT city, source, success, COUNT(*) AS cnt
            FROM source_reliability
            WHERE logged_date >= date('now', ?)
        """
        params: list = [f"-{days} days"]
        if city:
            query += " AND city = ?"
            params.append(city)
        query += " GROUP BY city, source, success"
        rows = con.execute(query, params).fetchall()

    result: dict = {}
    for r in rows:
        c, s = r["city"], r["source"]
        result.setdefault(c, {}).setdefault(s, {"successes": 0, "failures": 0})
        if r["success"]:
            result[c][s]["successes"] += r["cnt"]
        else:
            result[c][s]["failures"] += r["cnt"]

    for c in result:
        for s in result[c]:
            total = result[c][s]["successes"] + result[c][s]["failures"]
            result[c][s]["total"] = total
            result[c][s]["rate"] = result[c][s]["successes"] / total if total else 0.0

    return result


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
    now_utc = datetime.utcnow()
    for row in pending:
        ticker = row["ticker"]
        try:
            market = client.get_market(ticker)
            status = market.get("status", "")
            result = market.get("result", "")
            if status == "finalized":
                # #16/#80: only accept outcome if finalized for >1 hour (Kalshi may revise)
                close_time_str = market.get("close_time") or market.get(
                    "expiration_time", ""
                )
                if close_time_str:
                    try:
                        close_dt = datetime.fromisoformat(
                            close_time_str.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                        hours_since = (now_utc - close_dt).total_seconds() / 3600
                        if hours_since < 1.0:
                            continue  # too soon; wait for finalization to stabilize
                    except (ValueError, TypeError):
                        pass
                settled_yes = result == "yes"
                if log_outcome(ticker, settled_yes):
                    count += 1
        except Exception:
            continue
    return count


def log_member_score(
    city: str,
    model: str,
    predicted_temp: float,
    actual_temp: float,
    target_date_str: str,
) -> None:
    """Log an ensemble member's temperature prediction vs actuals for accuracy tracking."""
    init_db()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO ensemble_member_scores
              (city, model, predicted_temp, actual_temp, target_date, logged_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (city, model, predicted_temp, actual_temp, target_date_str),
        )


def get_member_accuracy(days_back: int = 60) -> dict:
    """
    Return per-model accuracy stats filtered to recent predictions.

    days_back=60 captures ~one season transition while giving each model
    enough observations (daily scoring ≈ 60 data points per city per model).
    Returns {model: {mae: float, n: int, city_breakdown: {city: mae}}}
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model, city, predicted_temp, actual_temp
            FROM ensemble_member_scores
            WHERE predicted_temp IS NOT NULL
              AND actual_temp IS NOT NULL
              AND logged_at >= datetime('now', ? || ' days')
            """,
            (f"-{days_back}",),
        ).fetchall()

    if not rows:
        return {}

    by_model: dict[str, list[tuple[str, float, float]]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(
            (r["city"], r["predicted_temp"], r["actual_temp"])
        )

    result: dict = {}
    for model, entries in by_model.items():
        errors = [abs(p - a) for _, p, a in entries]
        mae = sum(errors) / len(errors)
        city_errs: dict[str, list[float]] = {}
        for city, p, a in entries:
            city_errs.setdefault(city, []).append(abs(p - a))
        city_mae = {c: sum(v) / len(v) for c, v in city_errs.items()}
        result[model] = {
            "mae": round(mae, 4),
            "n": len(entries),
            "city_breakdown": {c: round(v, 4) for c, v in city_mae.items()},
        }
    return result


def get_ensemble_member_accuracy(
    city: str | None = None,
    season: str | None = None,
) -> dict | None:
    """
    Per-model MAE from ensemble_member_scores, stratified by city and season (#18).
    season: 'winter' = Oct-Mar (months 10-12, 1-3); 'summer' = Apr-Sep (months 4-9).
    Returns {model: {mae, count}} or None if table is empty after filtering.
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT model, city, predicted_temp, actual_temp, target_date
            FROM ensemble_member_scores
            WHERE predicted_temp IS NOT NULL AND actual_temp IS NOT NULL
        """
        params: list = []
        if city:
            query += " AND city = ?"
            params.append(city)
        if season:
            if season.lower() == "winter":
                query += " AND (CAST(strftime('%m', target_date) AS INTEGER) IN (10,11,12,1,2,3))"
            elif season.lower() == "summer":
                query += " AND (CAST(strftime('%m', target_date) AS INTEGER) IN (4,5,6,7,8,9))"
        rows = con.execute(query, params).fetchall()

    if not rows:
        return None

    by_model: dict[str, list[float]] = {}
    for r in rows:
        err = abs(r["predicted_temp"] - r["actual_temp"])
        by_model.setdefault(r["model"], []).append(err)

    return {
        model: {"mae": round(sum(errs) / len(errs), 4), "count": len(errs)}
        for model, errs in by_model.items()
    }


def get_market_calibration(n_buckets: int = 10) -> dict:
    """
    How well-calibrated are the MARKET PRICES (not our model)?
    Groups settled predictions into quantile-based buckets (equal frequency, not equal
    width) and computes actual outcome rate per bucket (#13).
    Returns a list of dicts with bucket_min, bucket_max, mean_prob, freq_yes, count.
    A well-calibrated market has freq_yes ≈ mean_prob.
    Systematic deviations = exploitable edges.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.market_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.market_prob IS NOT NULL
            ORDER BY p.market_prob ASC
        """).fetchall()

    if not rows:
        return {"buckets": []}

    # Quantile-based (equal frequency) bucketing
    data = [(r["market_prob"], r["settled_yes"]) for r in rows]
    n = len(data)
    bucket_size = max(1, n // n_buckets)

    result_buckets = []
    i = 0
    while i < n:
        chunk = data[i : i + bucket_size]
        # Merge last tiny remainder into previous bucket if it would be too small
        if i + bucket_size < n and (n - (i + bucket_size)) < bucket_size // 2:
            chunk = data[i:]
        probs = [p for p, _ in chunk]
        outcomes = [y for _, y in chunk]
        bucket_min = round(min(probs), 4)
        bucket_max = round(max(probs), 4)
        mean_prob = round(sum(probs) / len(probs), 4)
        freq_yes = round(sum(outcomes) / len(outcomes), 4)
        result_buckets.append(
            {
                "bucket_min": bucket_min,
                "bucket_max": bucket_max,
                "mean_prob": mean_prob,
                "freq_yes": freq_yes,
                "count": len(chunk),
            }
        )
        if i + bucket_size >= n or (n - (i + bucket_size)) < bucket_size // 2:
            break
        i += bucket_size

    return {"buckets": result_buckets}


def get_outcome_for_ticker(ticker: str) -> bool | None:
    """
    Return the recorded outcome for a ticker (True=YES, False=NO),
    or None if no outcome has been recorded yet.
    """
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT settled_yes FROM outcomes WHERE ticker = ?", (ticker,)
        ).fetchone()
    if row is None:
        return None
    return bool(row["settled_yes"])


# ── Model performance analytics ───────────────────────────────────────────────


def get_confusion_matrix(threshold: float = 0.5) -> dict:
    """
    TP/FP/TN/FN classification of model predictions.
    Positive = model predicted YES (our_prob >= threshold).
    Returns {tp, fp, tn, fn, precision, recall, f1, accuracy, n}.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """).fetchall()

    if not rows:
        return {
            "tp": 0,
            "fp": 0,
            "tn": 0,
            "fn": 0,
            "precision": None,
            "recall": None,
            "f1": None,
            "accuracy": None,
            "threshold": threshold,
            "n": 0,
        }

    tp = fp = tn = fn = 0
    for r in rows:
        predicted_yes = r["our_prob"] >= threshold
        actual_yes = bool(r["settled_yes"])
        if predicted_yes and actual_yes:
            tp += 1
        elif predicted_yes and not actual_yes:
            fp += 1
        elif not predicted_yes and actual_yes:
            fn += 1
        else:
            tn += 1

    n = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    accuracy = (tp + tn) / n if n > 0 else None

    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "threshold": threshold,
        "n": n,
    }


def get_optimal_threshold() -> dict | None:
    """
    Sweep thresholds 0.05..0.95 (step 0.05) and find the one maximizing F1 (#60).
    Returns {"threshold_f1": float, "best_f1": float} or None if < 20 samples.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """).fetchall()

    if len(rows) < 20:
        return None

    best_f1 = -1.0
    best_threshold = 0.5

    thresholds = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05 to 0.95
    for thresh in thresholds:
        tp = fp = tn = fn = 0
        for r in rows:
            predicted_yes = r["our_prob"] >= thresh
            actual_yes = bool(r["settled_yes"])
            if predicted_yes and actual_yes:
                tp += 1
            elif predicted_yes and not actual_yes:
                fp += 1
            elif not predicted_yes and actual_yes:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = thresh

    return {"threshold_f1": best_threshold, "best_f1": round(best_f1, 4)}


def get_roc_auc() -> dict:
    """
    ROC curve and AUC score for the model.
    Returns {auc, n, points: [{fpr, tpr}]} with ~11 representative points.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """).fetchall()

    if len(rows) < 10:
        return {"auc": None, "n": len(rows), "points": []}

    # Sort by descending probability (most confident YES first)
    sorted_rows = sorted(rows, key=lambda r: r["our_prob"], reverse=True)
    total_pos = sum(1 for r in sorted_rows if r["settled_yes"])
    total_neg = len(sorted_rows) - total_pos

    if total_pos == 0 or total_neg == 0:
        return {"auc": None, "n": len(rows), "points": []}

    # #19: if all predictions are identical, AUC is 0.5 (no discrimination ability)
    all_probs = [r["our_prob"] for r in sorted_rows]
    if len(set(all_probs)) == 1:
        return {
            "auc": 0.5,
            "n": len(rows),
            "points": [],
            "note": "no variance in predictions",
        }

    # Walk threshold from high to low, accumulate TPR/FPR
    tp = fp = 0
    roc_full: list[tuple[float, float]] = [(0.0, 0.0)]
    for r in sorted_rows:
        if r["settled_yes"]:
            tp += 1
        else:
            fp += 1
        roc_full.append((fp / total_neg, tp / total_pos))
    roc_full.append((1.0, 1.0))

    # AUC via trapezoidal rule
    auc = sum(
        (roc_full[i + 1][0] - roc_full[i][0])
        * (roc_full[i + 1][1] + roc_full[i][1])
        / 2
        for i in range(len(roc_full) - 1)
    )

    # Downsample to ~11 points (FPR bins 0.0, 0.1, ..., 1.0)
    bins: dict[float, float] = {}
    for fpr, tpr in roc_full:
        bucket = round(round(fpr * 10) / 10, 1)
        bins[bucket] = max(bins.get(bucket, 0.0), tpr)
    points = [{"fpr": k, "tpr": round(v, 4)} for k, v in sorted(bins.items())]

    return {"auc": round(auc, 4), "n": len(rows), "points": points}


def get_edge_decay_curve(condition_type: str | None = None) -> list[dict]:
    """
    Average edge and Brier score grouped by forecast horizon (days_out) (#14).
    Shows whether our edge shrinks as markets approach settlement.
    Returns [{bucket, avg_edge, avg_brier, n}] sorted near→far.
    Only includes buckets with >= 3 samples.
    Optionally filter by condition_type.
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT p.our_prob, p.market_prob, p.days_out, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.market_prob IS NOT NULL
              AND p.days_out IS NOT NULL
        """
        params: list = []
        if condition_type is not None:
            query += " AND p.condition_type = ?"
            params.append(condition_type)
        rows = con.execute(query, params).fetchall()

    buckets: dict[str, list] = {"0-2": [], "3-5": [], "6-10": [], "11+": []}
    order = ["0-2", "3-5", "6-10", "11+"]

    for r in rows:
        d = r["days_out"]
        edge = abs(r["our_prob"] - r["market_prob"])
        brier = (r["our_prob"] - r["settled_yes"]) ** 2
        if d <= 2:
            buckets["0-2"].append((edge, brier))
        elif d <= 5:
            buckets["3-5"].append((edge, brier))
        elif d <= 10:
            buckets["6-10"].append((edge, brier))
        else:
            buckets["11+"].append((edge, brier))

    result = []
    for key in order:
        entries = buckets[key]
        if len(entries) < 3:
            continue
        avg_edge = sum(e for e, _ in entries) / len(entries)
        avg_brier = sum(b for _, b in entries) / len(entries)
        result.append(
            {
                "bucket": key,
                "avg_edge": round(avg_edge, 4),
                "avg_brier": round(avg_brier, 4),
                "n": len(entries),
            }
        )
    return result


# ── Standalone statistical helpers ───────────────────────────────────────────


def bayesian_confidence_interval(
    successes: int,
    trials: int,
    confidence: float = 0.90,
) -> tuple[float, float]:
    """
    Bayesian credible interval for a proportion using Beta(1+s, 1+f) posterior (#57).
    Uses the Wilson score approximation for the interval bounds.

    Parameters
    ----------
    successes : int  — number of successes (e.g. YES outcomes)
    trials    : int  — total number of trials
    confidence: float — credible level, e.g. 0.90 for 90% CI

    Returns
    -------
    (lower, upper) tuple of floats in [0, 1]

    The interval shrinks (narrows) as trials increases, reflecting more certainty.
    """
    import math

    if trials < 0 or successes < 0:
        raise ValueError("successes and trials must be non-negative")
    if successes > trials:
        raise ValueError("successes cannot exceed trials")

    # Beta(1+s, 1+f) posterior — add 1 Laplace smoothing prior
    alpha = 1 + successes
    beta_param = 1 + (trials - successes)
    n_posterior = alpha + beta_param  # = trials + 2

    # Posterior mean
    p_hat = alpha / n_posterior

    # Wilson-score-style approximation using posterior parameters
    # z = inverse normal CDF for the tail area
    alpha_tail = (1.0 - confidence) / 2.0
    # Rational approximation of inverse normal (Beasley-Springer-Moro)
    z = _inv_normal_cdf(1.0 - alpha_tail)

    denominator = 1.0 + z * z / n_posterior
    centre = (p_hat + z * z / (2.0 * n_posterior)) / denominator
    margin = (
        z
        * math.sqrt(
            p_hat * (1 - p_hat) / n_posterior
            + z * z / (4.0 * n_posterior * n_posterior)
        )
        / denominator
    )

    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)
    return (round(lower, 6), round(upper, 6))


def _inv_normal_cdf(p: float) -> float:
    """Rational approximation of the inverse normal CDF (Abramowitz & Stegun 26.2.17)."""
    import math

    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")

    if p < 0.5:
        sign = -1.0
        p = 1.0 - p
    else:
        sign = 1.0

    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    numerator = c0 + c1 * t + c2 * t * t
    denominator = 1.0 + d1 * t + d2 * t * t + d3 * t * t * t
    return sign * (t - numerator / denominator)


# ── Price improvement tracking (#65) ─────────────────────────────────────────


def log_price_improvement(
    ticker: str,
    desired: float,
    actual: float,
    quantity: int,
    side: str,
) -> None:
    """
    #65: Record the difference between the desired price and the actual fill price.

    improvement = desired - actual  (positive means we got a better price than expected)
    """
    from datetime import UTC, datetime

    init_db()
    improvement = desired - actual
    try:
        with _conn() as con:
            con.execute(
                """
                INSERT INTO price_improvement
                  (ticker, desired_price, actual_price, improvement, quantity, side, logged_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    desired,
                    actual,
                    improvement,
                    quantity,
                    side,
                    datetime.now(UTC).isoformat(),
                ),
            )
    except Exception as exc:
        _log.warning("Failed to log price improvement: %s", exc)


def get_price_improvement_stats() -> dict | None:
    """
    #65: Return aggregate price improvement statistics.

    Returns None if fewer than 5 entries are recorded (insufficient data).
    Otherwise returns:
      {mean: float, median: float, count: int, positive_pct: float}
    where positive_pct is the fraction of fills that beat the desired price.
    """
    import statistics

    init_db()
    with _conn() as con:
        rows = con.execute("SELECT improvement FROM price_improvement").fetchall()

    if len(rows) < 5:
        return None

    improvements = [r["improvement"] for r in rows]
    count = len(improvements)
    mean_val = statistics.mean(improvements)
    median_val = statistics.median(improvements)
    positive_pct = sum(1 for v in improvements if v > 0) / count

    return {
        "mean": round(mean_val, 6),
        "median": round(median_val, 6),
        "count": count,
        "positive_pct": round(positive_pct, 4),
    }


def get_model_calibration_buckets() -> dict:
    """
    How well-calibrated is OUR MODEL (not market prices)?
    Groups settled predictions by our_prob into 10% buckets.
    Systematic deviation = over/under confidence we can correct for.
    Returns {"buckets": [{range, our_prob_avg, actual_rate, deviation, n}]}.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """).fetchall()

    if not rows:
        return {"buckets": []}

    buckets: list[list] = [[] for _ in range(10)]
    for r in rows:
        idx = min(9, int(r["our_prob"] * 10))
        buckets[idx].append((r["our_prob"], r["settled_yes"]))

    result_buckets = []
    for i, entries in enumerate(buckets):
        if len(entries) < 3:
            continue
        lo, hi = i * 10, i * 10 + 10
        avg_prob = sum(p for p, _ in entries) / len(entries)
        actual_rate = sum(y for _, y in entries) / len(entries)
        result_buckets.append(
            {
                "range": f"{lo}-{hi}%",
                "our_prob_avg": round(avg_prob, 4),
                "actual_rate": round(actual_rate, 4),
                "deviation": round(actual_rate - avg_prob, 4),
                "n": len(entries),
            }
        )
    return {"buckets": result_buckets}


# ── Unselected bias tracking (#55) ────────────────────────────────────────────


def log_analysis_attempt(
    ticker: str,
    city: str | None,
    condition: str | None,
    target_date,
    forecast_prob: float,
    market_prob: float,
    days_out: int,
    was_traded: bool = False,
) -> None:
    """#55: Log every analyzed market (traded or not) for bias detection."""
    init_db()
    from datetime import UTC

    analyzed_at = datetime.now(UTC).isoformat()
    target_str = (
        target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date)
    )
    try:
        with _conn() as con:
            con.execute(
                """INSERT OR REPLACE INTO analysis_attempts
                   (ticker, city, condition, target_date, analyzed_at,
                    forecast_prob, market_prob, days_out, was_traded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    city,
                    condition,
                    target_str,
                    analyzed_at,
                    forecast_prob,
                    market_prob,
                    days_out,
                    1 if was_traded else 0,
                ),
            )
    except Exception as exc:
        _log.warning("log_analysis_attempt failed for %s: %s", ticker, exc)


def settle_analysis_attempt(ticker: str, target_date, outcome: int) -> None:
    """#55: Record the outcome for a previously logged analysis attempt."""
    init_db()
    target_str = (
        target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date)
    )
    try:
        with _conn() as con:
            cursor = con.execute(
                "UPDATE analysis_attempts SET outcome=? WHERE ticker=? AND target_date=?",
                (outcome, ticker, target_str),
            )
            if cursor.rowcount == 0:
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "settle_analysis_attempt: no row for ticker=%s target_date=%s",
                    ticker,
                    target_str,
                )
    except Exception as exc:
        _log.warning("settle_analysis_attempt failed for %s: %s", ticker, exc)


def get_unselected_bias(city: str, condition_type: str | None = None) -> float:
    """#55: Mean (forecast_prob - outcome) for untraded markets in this city."""
    init_db()
    try:
        with _conn() as con:
            if condition_type:
                rows = con.execute(
                    """SELECT forecast_prob, outcome FROM analysis_attempts
                       WHERE city=? AND condition=? AND was_traded=0 AND outcome IS NOT NULL""",
                    (city, condition_type),
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT forecast_prob, outcome FROM analysis_attempts
                       WHERE city=? AND was_traded=0 AND outcome IS NOT NULL""",
                    (city,),
                ).fetchall()
    except Exception as exc:
        _log.warning("get_unselected_bias failed for %s: %s", city, exc)
        return 0.0

    if not rows:
        return 0.0
    errors = [fp - o for fp, o in rows]
    return round(sum(errors) / len(errors), 4)


def analyze_all_markets(enriched_list: list[dict]) -> None:
    """
    Log every analyzed market (traded or not) to analysis_attempts (#55).
    """
    init_db()
    from datetime import UTC
    from datetime import date as _date

    analyzed_at = datetime.now(UTC).isoformat()

    for item in enriched_list:
        try:
            ticker = item["ticker"]
            city = item.get("city")
            target_date = item.get("target_date")
            analysis = item.get("analysis", {})
            forecast_prob = analysis.get("forecast_prob")
            market_prob = analysis.get("market_prob")
            condition = analysis.get("condition", {})
            condition_str = condition.get("type") if condition else None
            days_out = (
                (target_date - _date.today()).days
                if target_date is not None and hasattr(target_date, "today")
                else None
            )
            if target_date is None:
                target_str = None
            elif hasattr(target_date, "isoformat"):
                target_str = target_date.isoformat()  # type: ignore[union-attr]
            else:
                target_str = str(target_date)
            try:
                with _conn() as con:
                    con.execute(
                        """INSERT OR REPLACE INTO analysis_attempts
                           (ticker, city, condition, target_date, analyzed_at,
                            forecast_prob, market_prob, days_out, was_traded)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (
                            ticker,
                            city,
                            condition_str,
                            target_str,
                            analyzed_at,
                            forecast_prob,
                            market_prob,
                            days_out,
                        ),
                    )
            except Exception as exc:
                _log.warning("analyze_all_markets: failed to log %s: %s", ticker, exc)
        except (KeyError, TypeError) as exc:
            _log.warning("analyze_all_markets: skipping malformed item: %s", exc)


def get_analysis_bias() -> float | None:
    """
    Mean(forecast_prob - settled_yes) across ALL analyzed markets (#55).
    Returns None if no analysis_attempts rows have a settled outcome.
    """
    init_db()
    try:
        with _conn() as con:
            rows = con.execute(
                """
                SELECT a.forecast_prob, o.settled_yes
                FROM analysis_attempts a
                JOIN outcomes o ON a.ticker = o.ticker
                WHERE a.forecast_prob IS NOT NULL
                  AND o.settled_yes IS NOT NULL
                """
            ).fetchall()
    except Exception as exc:
        _log.warning("get_analysis_bias failed: %s", exc)
        return None

    if not rows:
        return None

    bias_values = [r["forecast_prob"] - r["settled_yes"] for r in rows]
    return round(sum(bias_values) / len(bias_values), 6)


# ── #84 per-city model attribution ────────────────────────────────────────────


def get_model_attribution_by_city() -> dict[str, dict[str, float]]:
    """Return average blend-source weights per city from settled predictions."""
    import json as _json2
    from collections import defaultdict

    init_db()
    with _conn() as con:
        rows = con.execute(
            """SELECT city, blend_sources
               FROM predictions
               WHERE blend_sources IS NOT NULL AND city IS NOT NULL"""
        ).fetchall()

    if not rows:
        return {}

    city_totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    city_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        city = row["city"]
        try:
            sources = _json2.loads(row["blend_sources"])
        except (ValueError, TypeError):
            continue
        if not isinstance(sources, dict):
            continue
        for k, v in sources.items():
            city_totals[city][k] += float(v)
        city_counts[city] += 1

    result: dict[str, dict[str, float]] = {}
    for city, totals in city_totals.items():
        n = city_counts[city]
        result[city] = {k: round(v / n, 4) for k, v in totals.items()}
    return result
