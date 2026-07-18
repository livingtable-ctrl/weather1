"""
Prediction tracker — SQLite-backed log of every prediction we make.
After markets settle, records outcomes so we can:
  - Compute Brier scores (are our probabilities well-calibrated?)
  - Detect per-city/season bias and correct for it
  - Show a history of past calls
"""

from __future__ import annotations

import itertools
import logging
import math
import sqlite3
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from forecast_cache import ForecastCache
from paths import DB_PATH
from safe_io import project_root as _project_root
from utils import sql_normalize_iso_column
from utils import utc_today as _utc_today

_log = logging.getLogger(__name__)

DB_PATH.parent.mkdir(exist_ok=True)

_db_initialized = False

_SCHEMA_VERSION = 45  # increment when _MIGRATIONS list grows

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
    # v7 → v8: per-source probabilities for blend weight calibration (#118/#122)
    "ALTER TABLE predictions ADD COLUMN ensemble_prob REAL",
    # v8 → v9: nws_prob for blend weight calibration
    "ALTER TABLE predictions ADD COLUMN nws_prob REAL",
    # v9 → v10: clim_prob for blend weight calibration
    "ALTER TABLE predictions ADD COLUMN clim_prob REAL",
    # v10 → v11: strategy version stamp on each prediction row (P9.1)
    "ALTER TABLE predictions ADD COLUMN edge_calc_version TEXT",
    # v11 → v12: signal source tracking for P&L attribution (Phase G Task 2)
    "ALTER TABLE predictions ADD COLUMN signal_source TEXT",
    # v12 → v13: unique index on (ticker, predicted_date) prevents duplicate predictions
    # from TOCTOU race between SELECT and INSERT in log_prediction.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_pred_ticker_date ON predictions(ticker, date(predicted_at))",
    # v13 → v14: recovery — ensemble_prob was at v7 in the list but DBs already at v7+
    # when that migration was written had it silently skipped. Duplicate-column error
    # is caught by _run_migrations and treated as "already applied".
    "ALTER TABLE predictions ADD COLUMN ensemble_prob REAL",
    # v14 → v15: G4 — add explicit predicted_date column for reliable UPSERT key
    "ALTER TABLE predictions ADD COLUMN predicted_date TEXT",
    # v15 → v16: G4 — drop the old SQLite-function-based unique index
    "DROP INDEX IF EXISTS idx_pred_ticker_date",
    # v16 → v17: G4 — create new explicit-column unique index
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_pred_ticker_pdate ON predictions(ticker, predicted_date)",
    # v17 → v18: Phase 6.0 — log obs weight used for same-day blend
    "ALTER TABLE predictions ADD COLUMN obs_weight_used REAL",
    # v18 → v19: Phase 6.0 — log local hour at prediction time for obs-weight learning
    "ALTER TABLE predictions ADD COLUMN local_hour INTEGER",
    # v19 → v20: log the bias-corrected forecast temperature at trade time so we can
    # measure the systematic temperature bias driving our probability miscalibration.
    "ALTER TABLE predictions ADD COLUMN forecast_temp_f REAL",
    # v20 → v21: track resolution status so 404-not-found tickers are skipped without
    # deleting their historical prediction rows (fixes H4 — transient 404 destroyed records).
    "ALTER TABLE predictions ADD COLUMN status TEXT DEFAULT 'active'",
    # v21 → v22: H-20 — normalise settled_at to SQLite format (YYYY-MM-DD HH:MM:SS).
    # Python ISO-T format ('T' separator, '+00:00' suffix) was written by older code
    # paths.  Mixed formats corrupt date-range queries that rely on lexicographic order.
    # See sql_normalize_iso_column()'s docstring for the full bug-class writeup.
    f"""UPDATE outcomes
       SET settled_at = {sql_normalize_iso_column("settled_at")}
       WHERE settled_at LIKE '%T%'""",
    # v22 → v23: timestamp for 404-not-found marking so sync_outcomes can re-attempt
    # after 7 days instead of skipping the ticker permanently (WA-4).
    "ALTER TABLE predictions ADD COLUMN not_found_at TEXT",
    # v23 → v24: store the actual observed settlement temperature from Open-Meteo
    # archive so empirical NWS sigma calibration can be computed per city.
    # Without this we only know YES/NO — not the actual temperature — which makes
    # it impossible to measure real forecast error distributions.
    "ALTER TABLE outcomes ADD COLUMN settled_temp_f REAL",
    # v24 → v25: near-settlement snapshot log — model prob vs market price in the
    # 0–2h window before close. Cannot be back-filled; every cron cycle adds rows.
    # Unique index prevents duplicate rows per ticker per UTC hour.
    """CREATE TABLE IF NOT EXISTS near_settlement_log (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker           TEXT    NOT NULL,
        our_model_prob   REAL,
        market_yes_price REAL,
        hours_to_close   REAL    NOT NULL,
        trade_side       TEXT    NOT NULL,
        days_out         INTEGER NOT NULL,
        recorded_at      TEXT    NOT NULL
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_nsl_ticker_hour
        ON near_settlement_log(ticker, strftime('%Y-%m-%dT%H', recorded_at))""",
    # v25 → v26: store ICON/GFS model consensus flag (1=agree, 0=disagree, NULL=unknown)
    # so we can query whether the 0.5x Kelly multiplier in order_executor correlates with
    # outcomes — the multiplier already fires but was never stored for analysis.
    "ALTER TABLE predictions ADD COLUMN model_consensus INTEGER",
    # v26 → v27: EMOS training — ensemble mean at prediction time (degrees F).
    # Required for EMOS fit: mu = a + b*ens_mean.
    "ALTER TABLE predictions ADD COLUMN ens_mean REAL",
    # v27 → v28: EMOS training — ensemble variance at prediction time (degrees F squared).
    # Required for EMOS fit: sigma = sqrt(c + d*ens_var). Stored as variance, not std.
    "ALTER TABLE predictions ADD COLUMN ens_var REAL",
    # v29 → v30: composite index for Brier/calibration JOIN queries on (ticker, our_prob).
    # Speeds up the inner-loop join to outcomes by narrowing the predictions scan to rows
    # that actually have a probability (our_prob NOT NULL).
    "CREATE INDEX IF NOT EXISTS idx_predictions_ticker_settled ON predictions(ticker, our_prob) WHERE our_prob IS NOT NULL",
    # v30 → v31: composite index for per-city stats queries on (city, days_out, predicted_at).
    # Avoids a full table scan when filtering by city+horizon+date-range.
    "CREATE INDEX IF NOT EXISTS idx_predictions_city_days_created ON predictions(city, days_out, predicted_at) WHERE city IS NOT NULL",
    # v31 → v32: partial index on our_prob for calibration queries that filter our_prob IS NOT NULL.
    "CREATE INDEX IF NOT EXISTS idx_predictions_prob_settled ON predictions(our_prob) WHERE our_prob IS NOT NULL",
    # v32 → v33: composite index on outcomes(ticker, settled_at) scoped to rows with
    # settled_temp_f, used by EMOS training queries that join on ticker and filter by date.
    "CREATE INDEX IF NOT EXISTS idx_outcomes_ticker_settled ON outcomes(ticker, settled_at) WHERE settled_temp_f IS NOT NULL",
    # v33 → v34: flag predictions logged for a signal that was never actually
    # traded (e.g. TRADING_PAUSED, drawdown halt) so P&L-labeled displays can
    # distinguish them from trade-backed rows. Brier/calibration queries
    # deliberately do not filter on this — see log_prediction()'s docstring.
    "ALTER TABLE predictions ADD COLUMN is_shadow INTEGER DEFAULT 0",
    # v34 → v35: ensemble_member_scores had no variable column, so daily-HIGH
    # forecast errors and daily-LOW forecast errors were pooled together in
    # get_dynamic_station_bias() despite it accepting a var= parameter. Existing
    # rows can't be reliably backfilled (no way to recover which market type
    # produced them), so they're left NULL and excluded by var-filtered queries
    # going forward rather than guessed.
    "ALTER TABLE ensemble_member_scores ADD COLUMN var TEXT",
    # v35 → v36: ensemble_member_scores had no dedup key, so multiple trades
    # settling in the same city/date (e.g. two thresholds on the same market)
    # each inserted an identical (city, model, target_date, var) row, silently
    # over-weighting that day in get_model_weights/get_dynamic_station_bias
    # and inflating their min-sample gates with far fewer distinct days than
    # intended. NULLs in var (pre-v35 rows) are treated as distinct by SQLite's
    # UNIQUE semantics, so this does not collide with historical rows.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_ems_dedup "
    "ON ensemble_member_scores(city, model, target_date, var)",
    # v36 -> v37: price_history — OHLC candlesticks captured per settled market
    # (backfilled once, from sync_outcomes, via Kalshi's /candlesticks endpoint).
    # Unlocks edge-decay timing, real-price backtest replay, and adverse-selection
    # measurement — none of which are possible with only the scan-time price
    # this bot already logs to `predictions`.
    """CREATE TABLE IF NOT EXISTS price_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT    NOT NULL,
        series_ticker   TEXT,
        period_interval INTEGER NOT NULL,
        end_period_ts   INTEGER NOT NULL,
        price_open      REAL,
        price_high      REAL,
        price_low       REAL,
        price_close     REAL,
        yes_bid_close   REAL,
        yes_ask_close   REAL,
        volume          REAL,
        open_interest   REAL,
        logged_at       TEXT    NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_dedup "
    "ON price_history(ticker, period_interval, end_period_ts)",
    # v38 -> v39: disputed flag on outcomes -- set when audit_settlement() detects
    # a mismatch between Kalshi's settled result and our archive data. Disputed
    # rows are excluded from Brier/calibration/bias queries so a corrupted
    # ground-truth label can't silently pollute calibration scoring. Restores a
    # piece silently lost in the 24559a7 mystery-revert (see backlog.txt) --
    # ported forward against the many calibration functions added since.
    "ALTER TABLE outcomes ADD COLUMN disputed INTEGER DEFAULT 0",
    # v39 -> v42: forecast run-to-run trend signal (backlog.txt "FORECAST
    # RUN-TO-RUN TREND SIGNAL"), 3 columns added as 3 separate migration steps
    # (v40/v41/v42) matching this list's one-ALTER-per-entry convention.
    # run_trend_points is the raw {lead, value} series from
    # get_forecast_run_trend() as JSON (mirrors blend_sources'
    # JSON-for-flexibility pattern); run_trend_delta/run_trend_jumpy are
    # precomputed convenience scalars (mirrors ens_mean/ens_var) so simple
    # queries don't need to parse JSON. Log-only for now -- not read by any
    # blend/sizing code yet; gated behind a future tracked-accuracy pass per
    # the backlog entry's own "why not now."
    "ALTER TABLE predictions ADD COLUMN run_trend_points TEXT",  # v40
    "ALTER TABLE predictions ADD COLUMN run_trend_delta REAL",  # v41
    "ALTER TABLE predictions ADD COLUMN run_trend_jumpy REAL",  # v42
    # v42 -> v45: market-implied temperature distribution signal (backlog.txt
    # "MARKET-IMPLIED TEMPERATURE DISTRIBUTION FROM THE FULL LADDER"), 3
    # columns added as 3 separate migration steps (v43/v44/v45) matching this
    # list's one-ALTER-per-entry convention. implied_mean/implied_sigma are
    # weather_markets.fit_market_implied_distribution()'s fitted Normal
    # parameters from the full sibling bracket ladder; fit_residual is the
    # fit's weighted SSE (a fit-quality diagnostic, not a probability). No
    # delta-vs-model column: unlike run_trend_delta (a genuinely computed
    # multi-point statistic), implied_mean - forecast_temp_f is a trivial
    # single-column subtraction against an already-stored column, not worth
    # a redundant fourth column. Log-only -- not read by any blend/sizing
    # code yet; gated behind a future tracked-accuracy pass per the backlog
    # entry's own ENABLEMENT TRIGGER.
    "ALTER TABLE predictions ADD COLUMN implied_mean REAL",  # v43
    "ALTER TABLE predictions ADD COLUMN implied_sigma REAL",  # v44
    "ALTER TABLE predictions ADD COLUMN fit_residual REAL",  # v45
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
            # H-18: write user_version immediately after each migration so a crash
            # between steps leaves the version accurate rather than at v0.
            con.execute(f"PRAGMA user_version={version}")
            _log.info("Applied migration v%d", version)
        except Exception as e:
            err_str = str(e).lower()
            if "duplicate column" in err_str or "already exists" in err_str:
                # Migration already applied — still advance the version cursor.
                con.execute(f"PRAGMA user_version={version}")
                _log.debug("Migration v%d already applied: %s", version, e)
            else:
                raise

    # Ensure final version is set (covers case where all migrations were skipped)
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
            var            TEXT,
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

        -- #P10.4: micro live fill tracking for slippage measurement
        CREATE TABLE IF NOT EXISTS live_fills (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT    NOT NULL,
            side            TEXT    NOT NULL,
            paper_price     REAL    NOT NULL,   -- price used for paper trade
            fill_price      REAL    NOT NULL,   -- actual live fill price
            slippage_cents  REAL    NOT NULL,   -- (fill_price - paper_price) * 100
            quantity        INTEGER NOT NULL,
            logged_at       TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_live_fills_ticker ON live_fills(ticker, logged_at);

        -- Single definition of "multi-day prediction": excludes same-day trades
        -- (days_out=0) which use METAR-locked probs, not ensemble forecasts.
        -- NULL days_out means the row predates the column and is treated as multi-day.
        -- All analytics queries use this view so the filter is defined once.
        CREATE VIEW IF NOT EXISTS multiday_predictions AS
            SELECT * FROM predictions
            WHERE days_out IS NULL OR days_out >= 1;

        -- Single definition of "not disputed": every calibration/accuracy/
        -- training consumer should join this instead of the raw outcomes
        -- table (backlog.txt "DISPUTED-ROW EXCLUSION PREDICATE HAND-COPIED
        -- ~40 TIMES IN tracker.py"). A short, deliberately-raw allowlist
        -- still joins outcomes directly -- enforced by
        -- tests/test_disputed_row_guard.py.
        CREATE VIEW IF NOT EXISTS outcomes_valid AS
            SELECT * FROM outcomes
            WHERE disputed IS NULL OR disputed = 0;

        CREATE TABLE IF NOT EXISTS near_settlement_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker           TEXT    NOT NULL,
            our_model_prob   REAL,
            market_yes_price REAL,
            hours_to_close   REAL    NOT NULL,
            trade_side       TEXT    NOT NULL,
            days_out         INTEGER NOT NULL,
            recorded_at      TEXT    NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_nsl_ticker_hour
            ON near_settlement_log(ticker, strftime('%Y-%m-%dT%H', recorded_at));
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


def purge_old_predictions(retention_days: int = 730) -> int:
    """Delete settled predictions older than retention_days and their outcomes.

    Unsettled (open) predictions are never deleted.
    Returns the number of rows deleted from predictions.
    """
    cutoff = f"-{retention_days} days"
    init_db()
    with _conn() as con:
        # Item 24: only delete predictions that have a SETTLED outcome older
        # than the retention cutoff.  The previous query used
        # "NOT IN (SELECT ticker FROM outcomes)", which would also delete
        # unsettled predictions that simply haven't received an outcome row
        # yet — effectively purging open trades prematurely.
        #
        # Order matters: delete predictions BEFORE outcomes so the JOIN in
        # the predictions subquery can still find the outcome rows.
        result = con.execute(
            """
            DELETE FROM predictions
            WHERE ticker IN (
                SELECT p.ticker FROM predictions p
                JOIN outcomes o ON p.ticker = o.ticker
                WHERE o.settled_at < datetime('now', ?)
            )
            """,
            (cutoff,),
        )
        # Voided/cancelled markets (sync_outcomes) never get an outcomes row, so
        # the JOIN above can never reach them — purge by predicted_at instead.
        voided_result = con.execute(
            """
            DELETE FROM predictions
            WHERE status = 'voided' AND predicted_at < datetime('now', ?)
            """,
            (cutoff,),
        )
        # Delete orphaned outcome rows for the tickers we just removed.
        con.execute(
            """
            DELETE FROM outcomes
            WHERE ticker NOT IN (SELECT ticker FROM predictions)
              AND settled_at < datetime('now', ?)
            """,
            (cutoff,),
        )
    deleted = result.rowcount + voided_result.rowcount
    if deleted > 0:
        _log.info("purge_old_predictions: removed %d old prediction rows", deleted)
    return deleted


# ── Logging ───────────────────────────────────────────────────────────────────


def log_live_fill(
    ticker: str,
    side: str,
    paper_price: float,
    fill_price: float,
    quantity: int,
) -> None:
    """Record a micro live fill for slippage tracking (#P10.4)."""
    from datetime import UTC

    init_db()
    slippage_cents = round((fill_price - paper_price) * 100, 4)
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO live_fills (ticker, side, paper_price, fill_price, slippage_cents, quantity, logged_at) VALUES (?,?,?,?,?,?,?)",
                (
                    ticker,
                    side,
                    paper_price,
                    fill_price,
                    slippage_cents,
                    quantity,
                    datetime.now(UTC).isoformat(),
                ),
            )
    except Exception as exc:
        _log.warning("log_live_fill: %s", exc)


def get_mean_slippage(days: int = 30) -> float | None:
    """Return mean slippage in cents over the last `days` days, or None if no fills."""
    import datetime as _dt

    init_db()
    cutoff = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days)).isoformat()
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT AVG(slippage_cents) FROM live_fills WHERE logged_at >= ?",
                (cutoff,),
            ).fetchone()
        val = row[0] if row else None
        return round(val, 4) if val is not None else None
    except Exception as exc:
        _log.debug("get_mean_slippage: %s", exc)
        return None


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


def prune_api_requests(days_to_keep: int = 90) -> int:
    """P2-13: Delete api_requests rows older than days_to_keep. Returns row count deleted."""
    from datetime import UTC, timedelta

    init_db()
    cutoff = (datetime.now(UTC) - timedelta(days=days_to_keep)).isoformat()
    try:
        with _conn() as con:
            deleted = con.execute(
                "DELETE FROM api_requests WHERE logged_at < ?", (cutoff,)
            ).rowcount
        if deleted > 0:
            _log.info(
                "Pruned %d api_requests rows older than %d days", deleted, days_to_keep
            )
        return deleted
    except Exception as exc:
        _log.warning("prune_api_requests failed: %s", exc)
        return 0


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
    except Exception as exc:
        _log.warning("log_audit failed: %s", exc)


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
    edge_calc_version: str | None = None,
    signal_source: str | None = None,
    model_consensus: bool | None = None,
    ens_mean: float | None = None,
    ens_var: float | None = None,
    run_trend: dict | None = None,
    implied_mean: float | None = None,
    implied_sigma: float | None = None,
    fit_residual: float | None = None,
    is_shadow: bool = False,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Save a prediction to the database.
    Stores both the raw (pre-bias-correction) probability and the adjusted one (#53).
    #37: Optionally stores the NWP forecast cycle (00z/06z/12z/18z).
    #84: Optionally stores blend_sources dict (model weights) as JSON.
    P9.1: Optionally stores edge_calc_version for strategy version tracking.
    run_trend: optional dict from weather_markets.get_forecast_run_trend's
    caller-side result (see analyze_trade's "run_trend" key) -- shape
    {"points": [{"lead": N, "value": V}, ...], "delta": ..., "jumpy": ...}.
    Stored log-only (points as JSON, delta/jumpy as convenience scalar
    columns); not consumed by any blend/sizing code yet.
    implied_mean/implied_sigma/fit_residual: optional scalars from
    weather_markets.fit_market_implied_distribution()'s fit over an event's
    full sibling bracket ladder (backlog.txt "MARKET-IMPLIED TEMPERATURE
    DISTRIBUTION FROM THE FULL LADDER"). Stored log-only; not consumed by
    any blend/sizing code yet.
    is_shadow: True for a signal that was analyzed and would have traded but
    never had a real order placed (e.g. logged during TRADING_PAUSED) — flags
    the row so downstream P&L-labeled displays can distinguish it from a
    trade-backed prediction. Brier/calibration queries intentionally do NOT
    filter on this — shadow predictions are real forecasts and are meant to
    keep those scores current. The UPSERT uses MIN(existing, new) so a
    shadow/lookup write (e.g. cmd_market) can never un-flag an already
    trade-backed row — but the reverse isn't automatic: the manual quick-buy
    paths (_quick_paper_buy, cmd_paper buy) place real paper trades without
    ever calling log_prediction, so a ticker looked up via cmd_market first
    and then quick-bought keeps is_shadow=1 despite a real settled trade.
    Cosmetic (only affects n_shadow in get_pnl_by_signal_source's display),
    not fixed here — would need those two manual-buy paths to also call
    log_prediction(is_shadow=False), which is trade-placement-flow scope.
    conn: reuse a caller-provided connection (e.g. for batching many calls in
    one transaction) instead of opening a new one per call.

    Returns True if a row was written, False if skipped (e.g. city is None).
    """
    import json as _json

    # L4-B: null city pollutes cross-city bias queries — skip logging entirely
    if city is None:
        return False

    init_db()
    cond = analysis.get("condition", {})
    lo = cond.get("threshold", cond.get("lower"))
    hi = cond.get("threshold", cond.get("upper"))
    # max(0, ...) matches the clamp already used at weather_markets.py's
    # days_out call sites: from 00:00 UTC until local midnight (a same-day
    # evening window for US cities), _utc_today() is already local-tomorrow,
    # which would otherwise store days_out=-1 and drop the row from both the
    # same-day and multiday analytics buckets.
    days_out = (
        max(0, (market_date - _utc_today()).days) if market_date is not None else None
    )
    # #53: raw_prob is pre-bias-correction; forecast_prob is the adjusted value.
    # M-12: arithmetic is correct — bias_correction stores the amount SUBTRACTED from
    # the blended prob to produce forecast_prob, so adding it back reconstructs the
    # pre-correction value: raw = forecast + bias_correction.
    bias = analysis.get("bias_correction", 0.0) or 0.0
    forecast_prob = analysis.get("forecast_prob")
    raw_prob = round(forecast_prob + bias, 6) if forecast_prob is not None else None
    blend_sources_json = (
        _json.dumps(blend_sources) if blend_sources is not None else None
    )
    run_trend_points_json = (
        _json.dumps(run_trend["points"])
        if run_trend is not None and run_trend.get("points") is not None
        else None
    )
    run_trend_delta = run_trend.get("delta") if run_trend is not None else None
    run_trend_jumpy = run_trend.get("jumpy") if run_trend is not None else None
    implied_mean = round(implied_mean, 4) if implied_mean is not None else None
    implied_sigma = round(implied_sigma, 4) if implied_sigma is not None else None
    fit_residual = round(fit_residual, 6) if fit_residual is not None else None

    # G4: use today's wall-clock date as explicit UPSERT key (avoids SQLite
    # date(predicted_at) timezone ambiguity around UTC midnight).
    predicted_date = _utc_today().isoformat()

    sql = """
        INSERT INTO predictions
          (ticker, city, market_date, condition_type,
           threshold_lo, threshold_hi, our_prob, raw_prob, market_prob,
           edge, method, n_members, predicted_at, days_out, forecast_cycle,
           blend_sources, ensemble_prob, nws_prob, clim_prob, edge_calc_version,
           signal_source, predicted_date, obs_weight_used, local_hour,
           forecast_temp_f, model_consensus, ens_mean, ens_var, is_shadow,
           run_trend_points, run_trend_delta, run_trend_jumpy,
           implied_mean, implied_sigma, fit_residual)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker, predicted_date) DO UPDATE SET
            our_prob         = excluded.our_prob,
            raw_prob         = excluded.raw_prob,
            market_prob      = excluded.market_prob,
            edge             = excluded.edge,
            method           = excluded.method,
            n_members        = excluded.n_members,
            days_out         = excluded.days_out,
            forecast_cycle   = excluded.forecast_cycle,
            blend_sources    = excluded.blend_sources,
            ensemble_prob    = excluded.ensemble_prob,
            nws_prob         = excluded.nws_prob,
            clim_prob        = excluded.clim_prob,
            edge_calc_version= excluded.edge_calc_version,
            signal_source    = excluded.signal_source,
            obs_weight_used  = excluded.obs_weight_used,
            local_hour       = excluded.local_hour,
            forecast_temp_f  = excluded.forecast_temp_f,
            model_consensus  = excluded.model_consensus,
            ens_mean         = excluded.ens_mean,
            ens_var          = excluded.ens_var,
            run_trend_points = excluded.run_trend_points,
            run_trend_delta  = excluded.run_trend_delta,
            run_trend_jumpy  = excluded.run_trend_jumpy,
            implied_mean     = excluded.implied_mean,
            implied_sigma    = excluded.implied_sigma,
            fit_residual     = excluded.fit_residual,
            -- MIN(): a real-trade write (is_shadow=0) still clears the flag, but
            -- a shadow/lookup write (is_shadow=1, e.g. cmd_market) can never
            -- un-flag an already trade-backed row for the same (ticker, date).
            is_shadow        = MIN(predictions.is_shadow, excluded.is_shadow)
        """
    params = (
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
        edge_calc_version,
        signal_source,
        predicted_date,
        analysis.get("obs_weight_used"),
        analysis.get("local_hour"),
        analysis.get("forecast_temp"),
        int(model_consensus) if model_consensus is not None else None,
        ens_mean,
        ens_var,
        int(is_shadow),
        run_trend_points_json,
        run_trend_delta,
        run_trend_jumpy,
        implied_mean,
        implied_sigma,
        fit_residual,
    )
    # Atomic upsert — unique index on (ticker, predicted_date) prevents
    # duplicate rows from concurrent calls (TOCTOU of old SELECT+INSERT pattern).
    if conn is not None:
        conn.execute(sql, params)
    else:
        with _conn() as con:
            con.execute(sql, params)
    return True


def log_outcome(ticker: str, settled_yes: bool) -> bool:
    """Record whether a market settled YES or NO.
    Returns True if newly recorded, False if outcome already existed (#17).
    Refuses to overwrite an existing finalized outcome to prevent data corruption.
    """
    init_db()
    with _conn() as con:
        # H-19: use INSERT OR IGNORE to make this atomic — the previous SELECT+INSERT
        # pattern had a TOCTOU race where two concurrent runs could both pass the
        # "already exists" check and then one would silently fail on the UNIQUE constraint.
        result = con.execute(
            """
            INSERT OR IGNORE INTO outcomes (ticker, settled_yes, settled_at)
            VALUES (?, ?, datetime('now'))
            """,
            (ticker, 1 if settled_yes else 0),
        )
    return result.rowcount > 0  # True = newly inserted; False = already existed


def mark_outcome_disputed(ticker: str) -> None:
    """Mark an outcome row as disputed (archive/Kalshi settlement mismatch).
    Disputed rows are excluded from Brier scores and calibration training so a
    corrupted ground-truth label can't silently pollute calibration scoring.
    """
    init_db()
    try:
        with _conn() as con:
            con.execute("UPDATE outcomes SET disputed = 1 WHERE ticker = ?", (ticker,))
    except Exception as exc:
        _log.debug("mark_outcome_disputed: failed for %s: %s", ticker, exc)


def get_disputed_count() -> int:
    """Return the number of outcomes flagged as disputed (settlement audit mismatch)."""
    init_db()
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) FROM outcomes WHERE disputed = 1").fetchone()
    return row[0] if row else 0


def get_stop_loss_accuracy(stop_loss_trades: list[dict]) -> dict:
    """
    Audit stop-loss exits: did they save money vs. holding to actual settlement?

    stop_loss_trades: paper trades already filtered to stop-loss-triggered early
    exits (each needs ticker/entry_price/exit_price/quantity/side). The market
    itself settles on Kalshi regardless of whether this bot's own position was
    still open, so tracker.outcomes still has the real result to compare against
    — this function just does that join. Disputed outcomes are excluded, same as
    every other calibration/scoring consumer of settled_yes.

    entry_price/exit_price are both already the price for OUR held side (see
    close_paper_early / paper._liquidation_price), so no side-based repricing is
    needed for the realized leg — only the hypothetical hold-to-settlement leg
    needs a side check.

    Returns {"total": n, "saved_money": n, "exited_winner": n, "avg_saving": float}.
    "total" counts only rows with a synced settlement (unsynced/unsettled tickers
    are skipped, not counted as zero).
    """
    init_db()
    saved = 0
    exited_winner = 0
    savings: list[float] = []
    with _conn() as con:
        for t in stop_loss_trades:
            ticker = t.get("ticker")
            exit_price = t.get("exit_price")
            if not ticker or exit_price is None:
                continue
            row = con.execute(
                "SELECT settled_yes FROM outcomes_valid WHERE ticker = ?",
                (ticker,),
            ).fetchone()
            if row is None:
                continue
            settled_yes = bool(row["settled_yes"])
            entry_price = t.get("entry_price", 0.0)
            qty = t.get("quantity", 0)
            side = t.get("side", "yes")

            sl_pnl = (exit_price - entry_price) * qty
            settle_price = (
                1.0
                if (settled_yes and side == "yes") or (not settled_yes and side == "no")
                else 0.0
            )
            hold_pnl = (settle_price - entry_price) * qty

            saving = sl_pnl - hold_pnl  # positive = stop-loss saved us money
            savings.append(saving)
            if saving > 0:
                saved += 1
            elif hold_pnl > 0 and sl_pnl < hold_pnl:
                exited_winner += 1

    return {
        "total": len(savings),
        "saved_money": saved,
        "exited_winner": exited_winner,
        "avg_saving": round(sum(savings) / len(savings), 4) if savings else 0.0,
    }


def _candle_dollars(field: dict | None, key: str) -> float | None:
    """Parse a nullable fixed-point-dollar string (e.g. "0.55") from a
    candlestick sub-object (yes_bid/yes_ask/price) into a float."""
    if not field:
        return None
    val = field.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fp_count(val: str | None) -> float | None:
    """Parse a FixedPointCount string (e.g. "10.00" contracts) into a float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def log_price_candles(
    ticker: str,
    series_ticker: str | None,
    period_interval: int,
    candlesticks: list[dict],
) -> int:
    """Bulk-insert OHLC candlesticks for a market. Idempotent — re-running for
    the same ticker/period_interval/end_period_ts is a no-op (unique index).
    Returns the number of newly-inserted rows.
    """
    if not candlesticks:
        return 0
    init_db()
    rows = []
    for c in candlesticks:
        end_ts = c.get("end_period_ts")
        if end_ts is None:
            continue
        price = c.get("price") or {}
        yes_bid = c.get("yes_bid") or {}
        yes_ask = c.get("yes_ask") or {}
        rows.append(
            (
                ticker,
                series_ticker,
                period_interval,
                end_ts,
                _candle_dollars(price, "open_dollars"),
                _candle_dollars(price, "high_dollars"),
                _candle_dollars(price, "low_dollars"),
                _candle_dollars(price, "close_dollars"),
                _candle_dollars(yes_bid, "close_dollars"),
                _candle_dollars(yes_ask, "close_dollars"),
                _fp_count(c.get("volume_fp")),
                _fp_count(c.get("open_interest_fp")),
                datetime.now(UTC).isoformat(),
            )
        )
    if not rows:
        return 0
    with _conn() as con:
        cur = con.executemany(
            """
            INSERT OR IGNORE INTO price_history
            (ticker, series_ticker, period_interval, end_period_ts,
             price_open, price_high, price_low, price_close,
             yes_bid_close, yes_ask_close, volume, open_interest, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def get_price_history(ticker: str) -> list[sqlite3.Row]:
    """Return all logged candlesticks for a ticker, oldest first."""
    init_db()
    with _conn() as con:
        return con.execute(
            "SELECT * FROM price_history WHERE ticker = ? ORDER BY end_period_ts",
            (ticker,),
        ).fetchall()


# ── Bias correction ───────────────────────────────────────────────────────────

# L4-C: shrinkage prior — controls how quickly bias corrections ramp up with
# sample count.  With prior=10, a 5-sample estimate is shrunk to 33% of its
# face value; a 100-sample estimate retains 91%.  Formula: n / (n + prior).
_BIAS_SHRINKAGE_PRIOR: int = 10


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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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

    now = datetime.now(UTC)
    weighted_bias = 0.0
    total_weight = 0.0
    min_age_days = float("inf")
    valid_count = 0
    for r in rows:
        try:
            predicted_at = datetime.fromisoformat(
                r["predicted_at"].replace("Z", "+00:00")
            )
            if predicted_at.tzinfo is None:
                predicted_at = predicted_at.replace(tzinfo=UTC)
            age_days = max(0.0, (now - predicted_at).total_seconds() / 86400)
        except (ValueError, TypeError, AttributeError):
            continue
        valid_count += 1
        min_age_days = min(min_age_days, age_days)
        weight = math.exp(-age_days / 30.0)
        weighted_bias += (r["our_prob"] - r["settled_yes"]) * weight
        total_weight += weight

    # Re-check against min_samples using only rows that actually parsed —
    # the len(rows) gate above admits the raw (possibly corrupt) row count.
    if valid_count < min_samples:
        return 0.0

    # B5: relaxed stale cutoff from 14 → 60 days.
    # The exponential decay (30-day half-life) already smoothly reduces the influence
    # of old data. A hard zero cutoff at 14 days was too aggressive for a bot with a
    # small trade history — bias correction was inactive almost all the time.
    # M-13: use min_age_days (all data is stale) not max_age_days (which fires if even
    # one row is old, e.g. a single recent row would prevent the cutoff from ever firing).
    if min_age_days > 60:
        _log.debug(
            "get_quintile_bias: all %d rows older than 60 days — returning 0.0",
            len(rows),
        )
        return 0.0

    if total_weight == 0:
        return 0.0
    raw_bias = weighted_bias / total_weight
    # L4-C: shrink toward 0 — reduces variance when sample count is low
    n = valid_count
    return raw_bias * n / (n + _BIAS_SHRINKAGE_PRIOR)


_QUINTILE_EDGES = (0.0, 0.20, 0.40, 0.60, 0.80, 1.01)  # 1.01 so 1.0 falls in last bin


def get_quintile_bias(
    city: str | None,
    month: int | None,
    forecast_prob: float,
    min_samples: int = 5,
    condition_type: str | None = None,
) -> float:
    """
    Per-quintile bias correction.

    Bins settled predictions by ``our_prob`` into 5 equal-width buckets
    (0–0.20, 0.20–0.40, 0.40–0.60, 0.60–0.80, 0.80–1.0) and returns the
    exponentially-weighted mean bias for the bucket that ``forecast_prob``
    falls into.  Falls back to the global ``get_bias()`` when the target
    bucket has fewer than ``min_samples`` rows.
    """
    quintile_idx = min(4, int(forecast_prob / 0.20))
    q_lo = _QUINTILE_EDGES[quintile_idx]
    q_hi = _QUINTILE_EDGES[quintile_idx + 1]

    init_db()
    with _conn() as con:
        query = """
            SELECT p.our_prob, o.settled_yes, p.predicted_at
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND p.city IS NOT NULL
              AND p.our_prob >= ? AND p.our_prob < ?
        """
        params: list = [q_lo, q_hi]
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
        return get_bias(
            city, month, min_samples=min_samples, condition_type=condition_type
        )

    now = datetime.now(UTC)
    weighted_bias = 0.0
    total_weight = 0.0
    min_age_days = float("inf")
    valid_count = 0
    for r in rows:
        try:
            predicted_at = datetime.fromisoformat(
                r["predicted_at"].replace("Z", "+00:00")
            )
            if predicted_at.tzinfo is None:
                predicted_at = predicted_at.replace(tzinfo=UTC)
            age_days = max(0.0, (now - predicted_at).total_seconds() / 86400)
        except (ValueError, TypeError, AttributeError):
            continue
        valid_count += 1
        min_age_days = min(min_age_days, age_days)
        weight = math.exp(-age_days / 30.0)
        weighted_bias += (r["our_prob"] - r["settled_yes"]) * weight
        total_weight += weight

    # Re-check against min_samples using only rows that actually parsed —
    # the len(rows) gate above admits the raw (possibly corrupt) row count.
    if valid_count < min_samples:
        return get_bias(
            city, month, min_samples=min_samples, condition_type=condition_type
        )

    if min_age_days > 60:
        return 0.0
    if total_weight == 0:
        return 0.0
    raw_bias = weighted_bias / total_weight
    # L4-C: shrink toward 0 — reduces variance when sample count is low
    n = valid_count
    return raw_bias * n / (n + _BIAS_SHRINKAGE_PRIOR)


def get_brier_by_days_out() -> dict[str, float]:
    """
    Brier score segmented by forecast horizon.
    Returns {"same_day": brier, "1-2d": brier, "3-5d": brier, "6-10d": brier, "11+d": brier}
    Only buckets with >= 5 settled predictions are included.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes, p.days_out
            FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.days_out IS NOT NULL
        """).fetchall()

    buckets: dict[str, list[float]] = {
        "same_day": [],  # days_out == 0 (METAR-locked)
        "1-2d": [],  # days_out 1–2 (was "0-2d" before same-day was re-enabled)
        "3-5d": [],
        "6-10d": [],
        "11+d": [],
    }
    for r in rows:
        d = r["days_out"]
        err = (r["our_prob"] - r["settled_yes"]) ** 2
        if d == 0:
            buckets["same_day"].append(err)
        elif d <= 2:
            buckets["1-2d"].append(err)
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
    Excludes same-day trades (days_out=0) so same-day METAR results don't skew method scores.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.method, p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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


def brier_score_by_method_rolling(
    window: int = 20, min_samples: int = 1
) -> dict[str, float]:
    """Rolling Brier score per method over the last `window` settled predictions.

    Count-based (not time-based) so cadence-uneven methods still get a stable
    sample size — mirrors get_rolling_win_rate()'s windowing convention.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.method, p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.method IS NOT NULL
            ORDER BY o.settled_at DESC
        """).fetchall()

    by_method_recent: dict[str, list] = {}
    for r in rows:
        errs = by_method_recent.setdefault(r["method"], [])
        if len(errs) < window:
            errs.append((r["our_prob"] - r["settled_yes"]) ** 2)

    return {
        m: sum(errs) / len(errs)
        for m, errs in by_method_recent.items()
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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


def brier_score(
    city: str | None = None,
    min_days_out: int = 1,
    cutoff_days: int | None = None,
    last_n: int | None = None,
) -> float | None:
    """
    Brier score = mean((our_prob - outcome)²).
    Lower is better. 0.25 = random, 0.0 = perfect.

    Excludes same-day trades (days_out=0) by default because same-day uses
    METAR-locked probs, not ensemble forecasts — mixing them distorts the
    multi-day model quality signal used for graduation and calibration gates.
    Pass min_days_out=0 to include all trades.

    Pass cutoff_days=N to restrict to predictions whose outcome settled within
    the last N days (rolling window).  None means all-time (default).

    Pass last_n=N to restrict to the N most recently settled predictions.
    Useful for graduation gates where recent performance matters more than
    the historical average (e.g. last_n=50 lets early bad weeks age out).
    None means all (default).  cutoff_days and last_n can be combined.

    Primary source: tracker predictions + outcomes JOIN (populated by log_prediction
    + sync_outcomes).  Fallback: paper_trades.db where entry_prob and outcome are
    recorded directly at trade time — covers the common case where cron places trades
    without a prior analyze-command prediction log entry.
    """
    init_db()
    table = "multiday_predictions" if min_days_out > 0 else "predictions"
    with _conn() as con:
        query = f"""
            SELECT p.our_prob, o.settled_yes
            FROM {table} p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """
        params: list = []
        if city:
            query += " AND p.city = ?"
            params.append(city)
        if min_days_out > 1:
            # multiday_predictions only filters days_out >= 1 OR NULL — for a
            # stricter horizon floor, filter explicitly instead of silently
            # collapsing to the same >=1 population as min_days_out=1.
            query += " AND (p.days_out IS NULL OR p.days_out >= ?)"
            params.append(min_days_out)
        if cutoff_days is not None:
            query += f" AND o.settled_at >= datetime('now', '-{cutoff_days} days')"
        if last_n is not None:
            query += " ORDER BY o.settled_at DESC"
            query += f" LIMIT {last_n}"
        rows = con.execute(query, params).fetchall()

    if rows:
        return sum((r["our_prob"] - r["settled_yes"]) ** 2 for r in rows) / len(rows)

    # ── Fallback: compute from paper_trades (entry_prob + outcome) ────────────
    # paper_trades stores entry_prob (our model's P(YES)) and outcome ('yes'/'no').
    # This covers trades placed by cron that were never run through cmd_analyze.
    try:
        from paper import get_all_trades as _get_all_trades

        cutoff = (
            datetime.now(UTC) - timedelta(days=cutoff_days)
            if cutoff_days is not None
            else None
        )
        trades = _get_all_trades()
        # Collect (settled_at_str, prob, settled_yes) so we can sort for last_n.
        dated: list[tuple[str, float, int]] = []
        for t in trades:
            prob = t.get("entry_prob")
            outcome = t.get("outcome")
            if prob is None or outcome not in ("yes", "no"):
                continue
            if city and t.get("city") != city:
                continue
            # NULL/missing days_out in paper trades predates the column — treat as multi-day.
            trade_days_out = t.get("days_out")
            if (
                min_days_out > 0
                and trade_days_out is not None
                and trade_days_out < min_days_out
            ):
                continue
            settled_str = t.get("settled_at") or ""
            if cutoff is not None:
                if not settled_str:
                    continue
                try:
                    settled_dt = datetime.fromisoformat(
                        settled_str.replace("Z", "+00:00")
                    )
                    if settled_dt < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
            settled_yes = 1 if outcome == "yes" else 0
            dated.append((settled_str, float(prob), settled_yes))
        if last_n is not None:
            dated.sort(key=lambda x: x[0], reverse=True)
            dated = dated[:last_n]
        pairs = [(p, y) for _, p, y in dated]
        if pairs:
            return sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    except Exception as _e:
        _log.warning("brier_score: paper fallback failed: %s", _e)

    return None


def brier_score_rolling(weeks: int = 3) -> float | None:
    """Brier score over the most recent `weeks` weeks of settled multi-day predictions."""
    return brier_score(cutoff_days=weeks * 7)


def brier_score_rolling_with_n(weeks: int = 3) -> tuple[float | None, int]:
    """Returns (brier, n) for the rolling window in a single query.

    Use this at display sites that need to show the sample count alongside the score.
    """
    init_db()
    days = weeks * 7
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_at >= datetime('now', '-{days} days')
            """
        ).fetchall()
    n = len(rows)
    if not rows:
        return None, 0
    brier = sum((r["our_prob"] - r["settled_yes"]) ** 2 for r in rows) / n
    return round(brier, 4), n


def count_settled_predictions_rolling(weeks: int = 3) -> int:
    """Count multi-day predictions whose outcome settled within the last `weeks` weeks."""
    init_db()
    days = weeks * 7
    with _conn() as con:
        row = con.execute(
            f"SELECT COUNT(*) FROM multiday_predictions p "
            f"JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE p.our_prob IS NOT NULL "
            f"  AND o.settled_at >= datetime('now', '-{days} days')"
        ).fetchone()
    return row[0] if row else 0


def get_rolling_win_rate(window: int = 20) -> tuple[float | None, int]:
    """Win rate over the last `window` settled predictions.

    Returns (win_rate, count). Returns (None, 0) only when there is no settled
    data at all — a caller-supplied minimum-sample gate (e.g.
    ACCURACY_MIN_SAMPLE) should be applied by the caller against `count`, not
    inferred from this function returning None. Previously this returned
    (None, count) whenever count < window, which created a dead zone: if a
    caller's own minimum-sample threshold was set below `window`, the win
    rate check silently never activated in that gap since win_rate was always
    None there regardless of the caller's smaller threshold.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT o.settled_yes, p.our_prob
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
            ORDER BY o.settled_at DESC
            LIMIT ?
            """,
            (window,),
        ).fetchall()
    count = len(rows)
    if count == 0:
        return None, 0
    wins = sum(
        1
        for r in rows
        if (r["our_prob"] >= 0.5 and r["settled_yes"] == 1)
        or (r["our_prob"] < 0.5 and r["settled_yes"] == 0)
    )
    return wins / count, count


def get_rolling_win_rate_ci(window: int = 20, confidence: float = 0.90) -> dict | None:
    """Rolling win rate (see get_rolling_win_rate) with a Bayesian credible
    interval, so a small sample's win rate isn't read with more confidence
    than the data supports. Returns None when there is no settled data.

    Pairs get_rolling_win_rate's real (win_rate, count) with
    bayesian_confidence_interval -- the latter was a correctly-implemented,
    fully-tested standalone utility (#57) with no caller anywhere in the
    codebase until this wiring (2026-07-12).
    """
    win_rate, count = get_rolling_win_rate(window)
    if win_rate is None:
        return None
    successes = round(win_rate * count)
    ci_low, ci_high = bayesian_confidence_interval(successes, count, confidence)
    return {
        "win_rate": round(win_rate, 4),
        "n": count,
        "ci_low": round(ci_low, 4),
        "ci_high": round(ci_high, 4),
        "confidence": confidence,
    }


def count_settled_predictions() -> int:
    """Return the number of multi-day predictions with a known outcome.

    Uses multiday_predictions view (days_out >= 1 or NULL) so same-day METAR
    trades don't inflate calibration gates or the graduation threshold — those
    are assessed on multi-day ensemble performance, not same-day observations.
    """
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM multiday_predictions p JOIN outcomes_valid o ON p.ticker = o.ticker"
        ).fetchone()
    return row[0] if row else 0


def count_settled_sameday_predictions() -> int:
    """Count same-day (days_out=0) predictions with a known outcome."""
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            "WHERE p.days_out = 0"
        ).fetchone()
    return row[0] if row else 0


def count_emos_ready_predictions() -> int:
    """Count multi-day predictions that are actually trainable EMOS rows —
    ens_mean AND settled_temp_f both populated, matching get_emos_training_data's
    population exactly (a settlement whose temperature fetch failed leaves
    settled_temp_f NULL and is not trainable even though ens_mean exists).

    ens_var may be NULL for rows backfilled from the Previous Runs API — only
    forward-fill rows (placed after EMOS steps 1-4, Jun 21 2026+) carry both
    columns.  The emos-train mean calibration uses all rows; variance calibration
    uses only the forward-fill subset with non-NULL ens_var.
    """
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM multiday_predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            "WHERE p.ens_mean IS NOT NULL AND o.settled_temp_f IS NOT NULL"
        ).fetchone()
    return row[0] if row else 0


def count_settled_below_predictions() -> int:
    """Count multi-day below-type predictions with a known outcome."""
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM multiday_predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            "WHERE p.condition_type = 'below'"
        ).fetchone()
    return row[0] if row else 0


_WEST_COAST_CITIES = {"LA", "SanFrancisco", "Seattle"}


def count_settled_west_coast_multiday() -> dict[str, int]:
    """Return count of settled multi-day predictions per west-coast city.

    Uses the predictions table (days_out >= 1 or NULL) joined to outcomes so
    we only count rows with a known settlement temperature. Multi-day is defined
    as days_out >= 1 OR days_out IS NULL (legacy rows before the column existed).
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.city, COUNT(*)
            FROM   predictions p
            JOIN   outcomes_valid o ON o.ticker = p.ticker
            WHERE  p.city IN ('LA', 'SanFrancisco', 'Seattle')
              AND  (p.days_out IS NULL OR p.days_out >= 1)
              AND  o.settled_temp_f IS NOT NULL
            GROUP  BY p.city
            """
        ).fetchall()
    return {city: n for city, n in rows}


def get_emos_training_data() -> list[dict]:
    """Return rows for EMOS fitting: {ens_mean, ens_var, settled_temp_f}.

    Excludes rows where ens_mean or settled_temp_f is NULL.
    ens_var may be NULL for backfill rows — callers must handle None.
    Only multi-day predictions (days_out >= 1 or NULL).
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.ens_mean, p.ens_var, o.settled_temp_f
            FROM   predictions p
            JOIN   outcomes_valid o ON o.ticker = p.ticker
            WHERE  p.ens_mean IS NOT NULL
              AND  o.settled_temp_f IS NOT NULL
              AND  (p.days_out IS NULL OR p.days_out >= 1)
            ORDER  BY p.predicted_at
            """
        ).fetchall()
    return [
        {
            "ens_mean": float(r[0]),
            "ens_var": float(r[1]) if r[1] is not None else None,
            "settled_temp_f": float(r[2]),
        }
        for r in rows
    ]


def _get_recent_win_loss(window: int) -> tuple[int, int]:
    """Query the last `window` settled predictions and count wins.

    A win is: (our_prob >= 0.5 AND outcome = 1) OR (our_prob < 0.5 AND outcome = 0).

    Returns (wins, n) where n <= window.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
            ORDER BY o.settled_at DESC
            LIMIT ?
            """,
            (window,),
        ).fetchall()
    n = len(rows)
    wins = sum(
        1
        for r in rows
        if (r["our_prob"] >= 0.5 and r["settled_yes"] == 1)
        or (r["our_prob"] < 0.5 and r["settled_yes"] == 0)
    )
    return wins, n


def sprt_model_health(
    window: int = 50,
    p0: float | None = None,
    p1: float | None = None,
    alpha: float | None = None,
    beta: float | None = None,
    min_trades: int | None = None,
) -> dict:
    """Run SPRT on the last `window` settled trades.

    Sequential Probability Ratio Test to detect model degradation faster than
    waiting for Brier score accumulation.

    Returns:
        dict with keys:
            status: "ok" | "degraded" | "insufficient_data"
            llr: float  — log-likelihood ratio
            n: int      — number of trades evaluated
    """
    import math

    import utils

    p0 = p0 if p0 is not None else utils.SPRT_P0
    p1 = p1 if p1 is not None else utils.SPRT_P1
    alpha = alpha if alpha is not None else utils.SPRT_ALPHA
    beta = beta if beta is not None else utils.SPRT_BETA
    min_trades = min_trades if min_trades is not None else utils.SPRT_MIN_TRADES

    upper = math.log((1 - beta) / alpha)  # reject H0 (degraded) boundary
    lower = math.log(beta / (1 - alpha))  # accept H0 (healthy) boundary

    wins, n = _get_recent_win_loss(window)

    if n < min_trades:
        return {"status": "insufficient_data", "llr": 0.0, "n": n}

    llr = wins * math.log(p1 / p0) + (n - wins) * math.log((1 - p1) / (1 - p0))

    if llr >= upper:
        return {"status": "degraded", "llr": round(llr, 4), "n": n}
    elif llr <= lower:
        return {"status": "ok", "cleared": True, "llr": round(llr, 4), "n": n}
    else:
        return {"status": "ok", "llr": round(llr, 4), "n": n}


def get_brier_by_tier(
    strong_threshold: float = 0.30,
    med_threshold: float = 0.15,
) -> dict[str, dict]:
    """
    Brier score split by signal tier based on abs(edge) at prediction time.

    Tiers:
      strong — abs(edge) >= strong_threshold (default 0.30)
      med    — med_threshold <= abs(edge) < strong_threshold
      weak   — abs(edge) < med_threshold

    Returns {"strong": {"brier": float, "n": int}, "med": ..., "weak": ...}
    with None brier for tiers with no settled predictions.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.our_prob, p.edge, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.edge IS NOT NULL
            """
        ).fetchall()

    tiers: dict[str, list[float]] = {"strong": [], "med": [], "weak": []}
    for r in rows:
        abs_edge = abs(r["edge"])
        sq_err = (r["our_prob"] - r["settled_yes"]) ** 2
        if abs_edge >= strong_threshold:
            tiers["strong"].append(sq_err)
        elif abs_edge >= med_threshold:
            tiers["med"].append(sq_err)
        else:
            tiers["weak"].append(sq_err)

    return {
        tier: {
            "brier": round(sum(errs) / len(errs), 6) if errs else None,
            "n": len(errs),
        }
        for tier, errs in tiers.items()
    }


def get_brier_over_time(weeks: int = 12, min_days_out: int = 1) -> list[dict]:
    """Return mean Brier score per ISO week for the last `weeks` weeks.

    Joins settled predictions with outcomes, groups by strftime('%Y-W%W', predicted_at),
    computes mean (our_prob - settled_yes)^2 per week.

    min_days_out=1 excludes same-day (days_out=0) trades so the multi-day Brier
    alert isn't inflated by same-day settlements which have separate tracking.

    Returns [{"week": "2025-W40", "brier": 0.21}, ...] sorted ascending.
    Returns an empty list if no settled predictions exist in the window.
    """
    init_db()
    # SQLite-format cutoff (not Python isoformat) -- predicted_at is written by
    # SQLite's datetime('now') as 'YYYY-MM-DD HH:MM:SS'. A Python isoformat
    # cutoff ('...T...+00:00') compares lexicographically below every row on
    # the boundary date (' ' < 'T'), silently dropping the whole boundary day.
    cutoff = (datetime.now(UTC) - timedelta(weeks=weeks)).strftime("%Y-%m-%d %H:%M:%S")
    table = "multiday_predictions" if min_days_out > 0 else "predictions"
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT
                strftime('%Y-W%W', p.predicted_at) AS week,
                AVG(
                    (p.our_prob - o.settled_yes) * (p.our_prob - o.settled_yes)
                ) AS brier
            FROM {table} p
            JOIN outcomes_valid o ON o.ticker = p.ticker
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
                p.method, p.predicted_at, p.days_out,
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
    Optionally filter by condition_type. bias is an all-time mean per city
    (not month-weighted — see get_calibration_by_season for the seasonal
    breakdown, which is what actually uses market_date's month).
    """
    init_db()
    with _conn() as con:
        query = """
            SELECT p.city, p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
        wins = sum(1 for p, y in pairs if (p >= 0.5 and y == 1) or (p < 0.5 and y == 0))
        result[ctype] = {
            "brier": sum(errors) / len(errors),
            "bias": sum(biases) / len(biases),
            "win_rate": wins / len(pairs),
            "n": len(pairs),
        }
    return result


_CALIBRATION_GATE = 20


def _calibration_curve(
    pairs: list[tuple[float, int]], gate: int = _CALIBRATION_GATE
) -> dict:
    """Bucket (predicted_prob, settled_yes) pairs into 5 equal-width calibration bins.

    Shared by get_sameday_calibration() and the CLI-scoped *_cli() calibration
    functions so the bucket-edge convention lives in exactly one place. `gate` is
    the training-eligibility threshold (e.g. whether a T value should be trusted),
    NOT a display threshold — callers deciding whether to print a table should use
    their own n>=10 convention (see cmd_walkforward/cmd_backtest in main.py), not
    gate_met.

    Returns {n, gate, gate_met, brier, calibration_buckets}. calibration_buckets
    omits empty bins.
    """
    n = len(pairs)
    if n == 0:
        return {
            "n": 0,
            "gate": gate,
            "gate_met": False,
            "brier": None,
            "calibration_buckets": [],
        }

    probs = [p for p, _ in pairs]
    actuals = [a for _, a in pairs]
    brier = round(sum((p - a) ** 2 for p, a in zip(probs, actuals)) / n, 4)

    # Five equal-width probability bins from 0 to 1. METAR-locked probs live
    # near 0 and 1 because the current observation is usually either clearly
    # above or clearly below the threshold — mid-range bins will often be empty.
    bucket_edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.001]
    cal_buckets = []
    for i in range(len(bucket_edges) - 1):
        lo, hi = bucket_edges[i], bucket_edges[i + 1]
        members = [(p, a) for p, a in zip(probs, actuals) if lo <= p < hi]
        if not members:
            continue
        predicted_mean = sum(p for p, _ in members) / len(members)
        actual_rate = sum(a for _, a in members) / len(members)
        cal_buckets.append(
            {
                "bucket_low": lo,
                "bucket_high": min(bucket_edges[i + 1], 1.0),
                "predicted_mean": round(predicted_mean, 4),
                "actual_rate": round(actual_rate, 4),
                "n": len(members),
            }
        )

    return {
        "n": n,
        "gate": gate,
        "gate_met": n >= gate,
        "brier": brier,
        "calibration_buckets": cal_buckets,
    }


def _read_temperature_scale_key(key: str) -> float | None:
    """Read a single T value from data/temperature_scale.json (None if missing/untrained)."""
    import json as _json

    _ts_path = _project_root() / "data" / "temperature_scale.json"
    if not _ts_path.exists():
        return None
    try:
        ts = _json.loads(_ts_path.read_text())
        entry = ts.get(key, {})
        if isinstance(entry, dict) and "T" in entry:
            return float(entry["T"])
    except Exception:
        pass
    return None


def get_sameday_calibration() -> dict:
    """Calibration analytics for same-day (days_out=0) METAR-locked predictions.

    Completely isolated from multi-day calibration — only queries rows where
    days_out=0 and never touches the multiday_predictions view. Includes ALL
    condition types (does NOT exclude 'between') — this is the dashboard's view
    (web_app.py's /api/sameday-calibration). See get_sameday_calibration_cli() for
    the between-excluding variant the CLI (validate/backtest) uses — the two are
    NOT interchangeable, they differ by 69 rows on this repo's live data (2026-07-08).

    Returns:
      n           — total same-day settled predictions
      gate        — minimum samples needed before T_sameday is trained (20)
      gate_met    — True when n >= gate
      brier       — overall Brier score across all same-day settled trades
      t_sameday   — current T from temperature_scale.json (1.0 = identity / untrained)
      calibration_buckets — [{bucket_low, bucket_high, predicted_mean, actual_rate, n}]
                    5 equal-width bins from 0→1; bins with no data are omitted.
                    METAR probs cluster near 0/1 so mid-range bins will often be empty.
      by_time_of_day — {morning, afternoon, evening} each with
                    {n, brier, mean_prob, mean_actual, bias}
                    bias = mean_prob - mean_actual (positive = model overestimates)
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.our_prob, o.settled_yes, p.local_hour
            FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND p.days_out = 0
            ORDER BY p.predicted_at ASC
            """
        ).fetchall()

    t_sameday = _read_temperature_scale_key("sameday")
    curve = _calibration_curve(
        [(float(r["our_prob"]), int(r["settled_yes"])) for r in rows]
    )

    # Time-of-day breakdown: morning/afternoon/evening based on local_hour
    # recorded at prediction time.  This is the key diagnostic for the
    # temperature-peak-timing bias: morning placements underestimate the daily
    # high (temp still rising), evening placements overestimate (high already
    # passed).  bias = mean_prob - mean_actual; positive = model overestimates.
    # Night (0-5) is included so the TOD n-counts always sum to the overall n
    # for any trade that has local_hour populated.  Excludes by the is-not-None
    # guard only — no hours are silently dropped.
    tod_slots = {
        "night": (0, 6),
        "morning": (6, 12),
        "afternoon": (12, 18),
        "evening": (18, 24),
    }
    by_tod: dict[str, dict] = {}
    for slot, (lo_h, hi_h) in tod_slots.items():
        members = [
            (float(r["our_prob"]), int(r["settled_yes"]))
            for r in rows
            if r["local_hour"] is not None and lo_h <= r["local_hour"] < hi_h
        ]
        if not members:
            continue
        slot_n = len(members)
        slot_probs = [p for p, _ in members]
        slot_actuals = [a for _, a in members]
        slot_brier = sum((p - a) ** 2 for p, a in members) / slot_n
        mean_prob = sum(slot_probs) / slot_n
        mean_actual = sum(slot_actuals) / slot_n
        by_tod[slot] = {
            "n": slot_n,
            "brier": round(slot_brier, 4),
            "mean_prob": round(mean_prob, 4),
            "mean_actual": round(mean_actual, 4),
            "bias": round(mean_prob - mean_actual, 4),
        }

    return {
        **curve,
        "t_sameday": t_sameday,
        "by_time_of_day": by_tod,
    }


def get_multiday_calibration_cli() -> dict:
    """Calibration analytics for multi-day (days_out IS NULL OR >=1) predictions,
    scoped to match what the CLI (validate/backtest) has always shown: excludes
    condition_type='between', matching train_all_temperature_scaling()'s own
    exclusion (ml_bias.py) and both CLI blocks' pre-existing behavior.

    Returns {n, gate, gate_met, brier, t_multiday, calibration_buckets} — same shape
    as get_sameday_calibration() minus the sameday-only by_time_of_day breakdown.
    t_multiday is read from temperature_scale.json's "global" key — confirmed via
    apply_temperature_scaling() (ml_bias.py): days_out=0 uses "sameday" exclusively,
    everything else falls back to condition_type then "global", so "global" IS the
    multiday T, not a separate catch-all.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND (p.condition_type IS NULL OR p.condition_type != 'between')
            """
        ).fetchall()

    t_multiday = _read_temperature_scale_key("global")
    curve = _calibration_curve(
        [(float(r["our_prob"]), int(r["settled_yes"])) for r in rows]
    )
    return {**curve, "t_multiday": t_multiday}


def get_sameday_calibration_cli() -> dict:
    """Same population as get_sameday_calibration() but excludes
    condition_type='between', matching the CLI's (validate/backtest) existing scope.
    The dashboard-facing get_sameday_calibration() deliberately keeps 'between' rows —
    the two differ by 69 rows on this repo's live data (2026-07-08) and are NOT
    interchangeable.

    Returns {n, gate, gate_met, brier, t_sameday, calibration_buckets} — no
    by_time_of_day breakdown (the CLI doesn't currently surface it; dashboard's
    get_sameday_calibration() remains the source for that).
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND p.days_out = 0
              AND (p.condition_type IS NULL OR p.condition_type != 'between')
            """
        ).fetchall()

    t_sameday = _read_temperature_scale_key("sameday")
    curve = _calibration_curve(
        [(float(r["our_prob"]), int(r["settled_yes"])) for r in rows]
    )
    return {**curve, "t_sameday": t_sameday}


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


def _fetch_asos_daily_temp(
    station: str, target_date: date, var: str, city_tz: str = "UTC"
) -> float | None:
    """Fetch daily high (var='max') or low (var='min') from IEM ASOS archive.

    Uses Iowa Environmental Mesonet hourly ASOS observations for the exact
    ICAO station Kalshi uses for settlement — a point reading, not a grid cell.

    Fetches the UTC window that covers the LOCAL calendar day for city_tz (US
    cities are UTC-4 to UTC-8, so local midnight falls at 04:00–08:00 UTC,
    spanning two UTC calendar dates). Only readings whose local timestamp falls
    on target_date are included, which prevents the previous evening's readings
    from inflating the daily max/min.

    Falls back to None on any fetch or parse error.
    """
    from zoneinfo import ZoneInfo

    import requests

    tz_obj = ZoneInfo(city_tz)

    local_start = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tz_obj
    )
    # NWS Daily Climatological Reports (the source Kalshi actually settles on)
    # use a plain local midnight-to-midnight civil day for both max and min —
    # confirmed 2026-07-05 against real CLI reports (Minneapolis: a 69F low at
    # 6:16 AM was attributed to *that same date*; Phoenix: same pattern at
    # 5:16 AM). A prior version of this function extended the "min" window
    # through 10 AM local the *following* day on the theory that NWS climate
    # days run ~7 AM to 7 AM — both examples above directly contradict that
    # theory (a genuine 7am cutoff would have pushed those pre-7am readings
    # into the *previous* day's report instead) and a live audit found the
    # extension was silently misattributing the following morning's own low to
    # the target date whenever that next morning happened to be colder.
    local_end = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        23,
        59,
        59,
        tzinfo=tz_obj,
    )
    # R-42: use precise sts/ets UTC timestamps rather than day1/day2 date params.
    # day1/day2 turned out to be exclusive of day2 (verified against the live
    # API: day1=3/day2=4 returns data only through day1 23:53, never touching
    # day2 at all) — a real problem on its own, since a US city's local
    # midnight-to-midnight day straddles two *UTC* calendar dates (e.g. a
    # Pacific-timezone city's late-evening local reading, still within the same
    # local day, can land past midnight UTC). sts/ets take exact UTC instants,
    # so there's no day-boundary ambiguity to get wrong regardless of how the
    # local day maps onto UTC dates.
    utc_start = local_start.astimezone(UTC)
    utc_end = local_end.astimezone(UTC)

    params: dict[str, str] = {
        "station": station,
        "data": "tmpf",
        "sts": utc_start.strftime("%Y-%m-%dT%H:%MZ"),
        "ets": utc_end.strftime("%Y-%m-%dT%H:%MZ"),
        "tz": "UTC",
        "format": "onlycomma",
        "latlon": "no",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": "3",  # METAR automated observations
    }
    try:
        import time as _time

        # audit_settlement() is called once per settling ticker in a tight loop
        # (tracker.sync_outcomes) with no inter-call delay; IEM mesonet rate-limits
        # rapid requests with HTTP 429, which used to look identical to "no data
        # available" once raise_for_status() fed it to the blanket except below.
        resp = requests.get(
            "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py",
            params=params,
            timeout=15,
        )
        for attempt in range(2):
            if resp.status_code != 429:
                break
            _time.sleep(2 ** (attempt + 1))  # 2s, 4s backoff
            resp = requests.get(
                "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py",
                params=params,
                timeout=15,
            )
        resp.raise_for_status()
        temps: list[float] = []
        for line in resp.text.splitlines():
            parts = line.split(",")
            if len(parts) < 3:
                continue
            # Accept only readings on the target local calendar day (both
            # max and min — see the local_end comment above for why "min"
            # no longer extends into the following day).
            try:
                obs_utc = datetime.strptime(parts[1].strip(), "%Y-%m-%d %H:%M").replace(
                    tzinfo=UTC
                )
                obs_local = obs_utc.astimezone(tz_obj)
                if obs_local.date() != target_date:
                    continue
            except ValueError:
                continue  # Header row or unparseable timestamp
            raw = parts[2].strip()
            try:
                temps.append(float(raw))
            except ValueError:
                continue  # 'M' (missing)
        if not temps:
            return None
        return max(temps) if var == "max" else min(temps)
    except Exception:
        return None


def _fetch_actual_daily_temp(
    lat: float, lon: float, tz: str, target_date: date, var: str
) -> float | None:
    """Fetch observed daily high (var='max') or low (var='min') from Open-Meteo archive.

    Fallback used when no ASOS station is mapped for a city. Prefer
    _fetch_asos_daily_temp for any city with a known ICAO station — Open-Meteo
    uses gridded ERA5 reanalysis which can differ from point station readings
    by up to 3°F at cities where the airport sits in a different microclimate.
    """
    import requests

    daily_var = "temperature_2m_max" if var == "max" else "temperature_2m_min"
    params: dict[str, str | float] = {
        "latitude": lat,
        "longitude": lon,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "daily": daily_var,
        "temperature_unit": "fahrenheit",
        "timezone": tz,
    }
    try:
        resp = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        vals = resp.json().get("daily", {}).get(daily_var, [])
        if vals and vals[0] is not None:
            return float(vals[0])
    except Exception:
        pass
    return None


def audit_settlement(ticker: str, settled_yes: bool) -> bool:
    """Cross-check Kalshi's settlement against ASOS station archive data.

    Uses the ICAO station nearest the city (via IEM ASOS raw hourly METAR
    archive) as an approximate proxy. Falls back to Open-Meteo gridded data
    only when no station is mapped for the city.

    NOTE: this is NOT the same source Kalshi actually settles on. Kalshi's
    rules_primary text states settlement uses the NWS Daily Climatological
    Report (CLI product), which is compiled/rounded differently and can
    legitimately disagree with raw ASOS METAR extremes by ~1 degree near a
    threshold (confirmed 2026-07-05 on KXLOWTMIN-26JUN28-T66: fresh ASOS
    KMSP read 67.0F against a 66F "greater than" threshold — implying YES —
    while Kalshi's real CLI-report-based settlement was NO). A MISMATCH
    warning here means our proxy disagrees with Kalshi, not that Kalshi
    settled incorrectly.

    Logs a WARNING when archive temperature contradicts Kalshi's YES/NO result,
    which can indicate a data source lag, this proxy/CLI-report divergence, or
    (rarely) an actual Kalshi settlement mistake. Skips silently if the ticker
    is unparseable, archive is unavailable, or the condition type can't be
    verified with a single temperature value (e.g. between, precipitation).

    Returns True if settled_temp_f was actually written, False if this call
    skipped for any reason (unparseable ticker/city, no coords, no archive
    data, etc.) — callers that loop over many tickers (e.g. a backfill) should
    use this instead of re-reading the DB, since a False here means the row's
    prior value (if any) was left completely untouched, not confirmed correct.
    """
    try:
        from weather_markets import CITY_COORDS as _coords
        from weather_markets import _metar_station_for_city as _station_for_city
        from weather_markets import _parse_market_condition as _parse_cond
        from weather_markets import parse_city_date as _parse_city_date

        city, target_date = _parse_city_date({"ticker": ticker, "title": ""})
        if not city or not target_date:
            return False

        coords = _coords.get(city)
        if not coords:
            return False
        lat, lon, tz = coords

        # Prefer condition stored in predictions DB — it was recorded with the real
        # Kalshi market title, so direction (above vs below) is correct. Parsing
        # with an empty title falls back to series-ticker heuristics that map
        # KXLOW T-type markets to "below" even when the market is actually "above".
        _db_cond: dict | None = None
        try:
            with _conn() as _con:
                _row = _con.execute(
                    "SELECT condition_type, threshold_lo, threshold_hi"
                    " FROM predictions WHERE ticker = ?",
                    (ticker,),
                ).fetchone()
            if _row:
                _ctype, _lo, _hi = _row
                if _ctype == "above" and _lo is not None:
                    _db_cond = {"type": "above", "threshold": float(_lo)}
                elif _ctype == "below" and _lo is not None:
                    _db_cond = {"type": "below", "threshold": float(_lo)}
                elif _ctype == "between" and _lo is not None and _hi is not None:
                    _db_cond = {
                        "type": "between",
                        "lower": float(_lo),
                        "upper": float(_hi),
                    }
        except Exception:
            pass
        cond = (
            _db_cond
            if _db_cond is not None
            else _parse_cond({"ticker": ticker, "title": ""})
        )
        if not cond:
            return False

        cond_type = cond.get("type", "")

        # Determine which daily temperature variable to fetch.
        # HIGH temp markets (KXHIGH...) need the daily max; LOW temp markets need min.
        # between markets use the same logic — the range is on a specific var.
        ticker_upper = ticker.upper()
        if "HIGH" in ticker_upper:
            var = "max"
        elif "LOWT" in ticker_upper or "LOW" in ticker_upper:
            var = "min"
        elif cond_type == "above":
            var = "max"
        elif cond_type == "below":
            var = "min"
        else:
            return False  # precipitation or unknown — skip

        # Prefer ASOS station data (same source as Kalshi settlement).
        # Fall back to Open-Meteo gridded archive only when no station is mapped.
        station = _station_for_city(city)
        if station:
            actual = _fetch_asos_daily_temp(station, target_date, var, city_tz=tz)
            source = f"ASOS:{station}"
        else:
            actual = _fetch_actual_daily_temp(lat, lon, tz, target_date, var)
            source = "OpenMeteo"
        if actual is None:
            return False

        # Store the observed temperature so we can compute empirical NWS forecast
        # error distributions per city — the foundation for data-driven sigma
        # calibration that will replace the current hardcoded sigma values.
        with _conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ? WHERE ticker = ?",
                (round(actual, 1), ticker),
            )
        _log.debug("settlement_audit: stored actual temp %.1f°F for %s", actual, ticker)

        # Consistency check: only verifiable for above/below single-threshold markets.
        # between markets define a range — a single temp point confirms or denies
        # the range membership, which we can check too. settled_temp_f was already
        # written above regardless of whether this check can run, so every return
        # from here on is still True.
        threshold_desc = ""
        if cond_type == "above":
            threshold = cond.get("threshold")
            if threshold is None:
                return True
            archive_yes = actual > threshold
            threshold_desc = f">{threshold:g}F"
        elif cond_type == "below":
            threshold = cond.get("threshold")
            if threshold is None:
                return True
            archive_yes = actual < threshold
            threshold_desc = f"<{threshold:g}F"
        elif cond_type == "between":
            lo = cond.get("lower")
            hi = cond.get("upper")
            if lo is None or hi is None:
                return True
            archive_yes = lo < actual < hi
            threshold_desc = f"{lo:g}-{hi:g}F"
        else:
            return True

        if archive_yes != settled_yes:
            # cond_type + threshold_desc together give a future reader enough to
            # judge, at a glance, whether this looks like the small (~1F) accepted
            # ASOS-vs-CLI-report proxy gap or something larger worth a fresh look —
            # see this function's docstring for that known, deliberately-unfixed gap.
            _log.warning(
                "settlement_audit MISMATCH %s — Kalshi=%s %s=%.1f°F vs threshold %s (%s)",
                ticker,
                "YES" if settled_yes else "NO",
                source,
                actual,
                threshold_desc,
                cond_type,
            )
            mark_outcome_disputed(ticker)
        else:
            _log.debug(
                "settlement_audit OK %s — Kalshi=%s %s=%.1f°F",
                ticker,
                "YES" if settled_yes else "NO",
                source,
                actual,
            )
        return True
    except Exception as exc:
        _log.debug("audit_settlement: skipped for %s: %s", ticker, exc)
        return False


# Maps our live ensemble model names to their deterministic equivalents in the
# Previous Runs API.  Individual ensemble members are only archived for 3 days;
# the Previous Runs API stores deterministic control-run forecasts at fixed lead
# times (previous_day1 = 24 h ahead, previous_day2 = 48 h ahead) since Jan 2024.
_PREVIOUS_RUN_MODEL_MAP = {
    "icon_seamless": "icon_seamless",
    "gfs_seamless": "gfs_seamless",
    "ecmwf_aifs025_ensemble": "ecmwf_aifs025_single",
}


def _fetch_previous_run_daily(
    lat: float,
    lon: float,
    tz: str,
    target_date: date,
    prev_model: str,
    days_out: int,
    var: str,
) -> float | None:
    """Fetch one model's daily max or min from the Previous Runs API.

    Requests temperature_2m_previous_day{days_out} so the stored ens_mean
    reflects the forecast at the same lead time the live system uses at trade
    placement.  Returns None if the model has no data for this date.
    """
    import requests as _req

    # utc_today(), not date.today(): target_date is UTC-anchored (see
    # _fetch_previous_run_leads's identical fix, tracker.py above) -- a
    # server running ahead of UTC would otherwise miscount past_days near
    # the day boundary (backlog.txt "utils.utc_today() SAYS 'USE EVERYWHERE
    # INSTEAD OF date.today()' -- 17 SITES STILL DON'T").
    past_days = (_utc_today() - target_date).days
    if past_days < 0:
        return None
    lead = max(1, min(days_out, 7))
    hourly_var = f"temperature_2m_previous_day{lead}"
    date_str = target_date.isoformat()

    try:
        resp = _req.get(
            "https://previous-runs-api.open-meteo.com/v1/forecast",
            params={
                "latitude": str(lat),
                "longitude": str(lon),
                "models": prev_model,
                "temperature_unit": "fahrenheit",
                "timezone": tz,
                "hourly": hourly_var,
                "past_days": str(past_days),
                "forecast_days": "1",
            },
            timeout=20,
        )
        resp.raise_for_status()
    except Exception:
        return None

    data = resp.json()
    if not isinstance(data, dict):
        return None
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    vals = [
        v
        for t, v in zip(times, hourly.get(hourly_var, []))
        if date_str in t and v is not None
    ]
    if not vals:
        return None
    return max(vals) if var == "max" else min(vals)


# Forecast run-to-run trend signal (backlog.txt "FORECAST RUN-TO-RUN TREND
# SIGNAL"). Reuses _PREVIOUS_RUN_MODEL_MAP / the Previous Runs API, but unlike
# _fetch_previous_run_daily (built for backfilling PAST, already-settled
# target dates) this is called live, at trade-analysis time, for target dates
# that are usually still in the FUTURE. Live-verified 2026-07-16 against the
# real endpoint: requesting forecast_days sized to reach a future target_date
# (instead of relying on past_days, which _fetch_previous_run_daily hardcodes
# and which returns None outright for a future date) returns real, non-null
# data for all 3 models in _PREVIOUS_RUN_MODEL_MAP, and confirmed the lead
# clamp of 1-7 is correct (lead=8 comes back all-null).
_RUN_TREND_LOOKBACK = 4  # leads N..N+3 (clamped to the API's valid 1-7 range)
_run_trend_cache: ForecastCache[dict | None] = ForecastCache(ttl_secs=4 * 60 * 60)
_RUN_TREND_NEGATIVE_TTL = 30 * 60  # shorter TTL for a failed/empty fetch so a
# transient API hiccup doesn't blank this signal out for the full 4h TTL.


def _fetch_previous_run_leads(
    lat: float,
    lon: float,
    tz: str,
    target_date: date,
    prev_model: str,
    leads: list[int],
    var: str,
) -> dict[int, float]:
    """Fetch several lead offsets for one model in a single Previous Runs API call.

    Unlike _fetch_previous_run_daily, target_date may be in the future:
    forecast_days is sized from today through target_date rather than using
    past_days (which requires target_date <= today). Returns {lead: value}
    for whichever leads had non-null data; missing leads are simply absent
    from the result rather than raising.
    """
    import requests as _req

    date_str = target_date.isoformat()
    # utc_today(), not date.today(): target_date is UTC-anchored (see
    # analyze_trade's own days_out computation against datetime.now(UTC)) --
    # a server running ahead of UTC (e.g. Belgium, UTC+2) would otherwise
    # under-count forecast_days by 1 and could miss the boundary day. Same
    # bug class documented in utc_today()'s own docstring and already hit
    # once in this project's test suite (2026-07-13, TestMonteCarloCholesky).
    forecast_days = max(1, (target_date - _utc_today()).days + 1)
    hourly_vars = [f"temperature_2m_previous_day{lead}" for lead in leads]

    try:
        resp = _req.get(
            "https://previous-runs-api.open-meteo.com/v1/forecast",
            params={
                "latitude": str(lat),
                "longitude": str(lon),
                "models": prev_model,
                "temperature_unit": "fahrenheit",
                "timezone": tz,
                "hourly": ",".join(hourly_vars),
                "forecast_days": str(forecast_days),
            },
            timeout=20,
        )
        resp.raise_for_status()
    except Exception:
        return {}

    try:
        data = resp.json()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    hourly = data.get("hourly", {})
    if not isinstance(hourly, dict):
        return {}
    times = hourly.get("time", [])

    out: dict[int, float] = {}
    for lead, hourly_var in zip(leads, hourly_vars):
        day_vals = [
            v
            for t, v in zip(times, hourly.get(hourly_var, []))
            if date_str in t and v is not None
        ]
        if day_vals:
            out[lead] = max(day_vals) if var == "max" else min(day_vals)
    return out


def get_forecast_run_trend(
    city: str, target_date: date, days_out: int, var: str = "max"
) -> dict | None:
    """Compare today's forecast for target_date against the last few runs.

    lead=N (N = max(1, min(days_out, 7))) is ~today's forecast for
    target_date; lead=N+1 is ~yesterday's forecast for the same date,
    lead=N+2 the day before that, etc. Reading points in that order gives a
    "how has the forecast moved over the last few runs" series. Every point
    is computed identically -- weighted across the same 3 models
    (_PREVIOUS_RUN_MODEL_MAP) using the same _model_weights() weighting
    backfill_emos_data already uses for ens_mean -- so the delta is a real
    apples-to-apples revision signal, not a mismatch between a live ensemble
    mean and a single deterministic control run.

    Only applies to multi-day markets (days_out >= 1); same-day markets use
    the METAR-driven pipeline instead, matching the existing days_out >= 1
    gate on ens_mean backfill. Returns None if days_out < 1, the city has no
    coords, or fewer than 2 leads produced data for any model (can't compute
    a delta). Never raises -- this signal is log-only today (see backlog.txt)
    and must never block a trade decision evaluated at the same time.

    Result shape: {"points": [{"lead": N, "value": V}, ...] lead-ascending
    (so points[0] is the most recent, points[1] the run before that, ...),
    "delta": points[0]["value"] - points[1]["value"] (positive = trending
    warmer/higher), "jumpy": population stdev across all available points}.
    """
    if days_out < 1:
        return None

    cache_key = (city, target_date.isoformat(), days_out, var)
    cached, hit, _ = _run_trend_cache.get_with_ts(cache_key)
    if hit:
        return cached

    try:
        from weather_markets import CITY_COORDS as _coords
        from weather_markets import _model_weights as _wm_weights
    except Exception:
        return None

    coords = _coords.get(city)
    if coords is None:
        return None
    lat, lon, tz = coords

    lead0 = max(1, min(days_out, 7))
    leads = [ld for ld in range(lead0, lead0 + _RUN_TREND_LOOKBACK) if ld <= 7]
    if len(leads) < 2:
        _run_trend_cache.set_with_ttl(cache_key, None, _RUN_TREND_NEGATIVE_TTL)
        return None

    # Wrapped so the function's own "never raises" contract holds without
    # depending on a caller's try/except -- _model_weights()/statistics.pstdev
    # aren't otherwise guarded here (2026-07-16 review finding).
    try:
        weights = _wm_weights(city, month=target_date.month)
        per_lead_weighted: dict[int, list[tuple[float, float]]] = {
            ld: [] for ld in leads
        }
        for ens_model, prev_model in _PREVIOUS_RUN_MODEL_MAP.items():
            w = weights.get(ens_model, 1.0)
            fetched = _fetch_previous_run_leads(
                lat, lon, tz, target_date, prev_model, leads, var
            )
            for ld, val in fetched.items():
                per_lead_weighted[ld].append((w, val))

        points = []
        for ld in leads:
            entries = per_lead_weighted[ld]
            if not entries:
                continue
            w_sum = sum(w for w, _v in entries)
            if w_sum <= 0:
                continue
            w_mean = sum(w * v for w, v in entries) / w_sum
            points.append({"lead": ld, "value": round(w_mean, 3)})

        if len(points) < 2:
            _run_trend_cache.set_with_ttl(cache_key, None, _RUN_TREND_NEGATIVE_TTL)
            return None

        import statistics as _stats

        values = [p["value"] for p in points]
        result = {
            "points": points,
            "delta": round(values[0] - values[1], 3),
            "jumpy": round(_stats.pstdev(values), 3),
        }
    except Exception:
        _run_trend_cache.set_with_ttl(cache_key, None, _RUN_TREND_NEGATIVE_TTL)
        return None

    _run_trend_cache.set(cache_key, result)
    return result


def get_forecast_run_trend_from_analysis(analysis: dict) -> dict | None:
    """Compute the run-to-run trend signal from an analyze_trade() result dict.

    Deliberately NOT called from inside analyze_trade() itself -- a 2026-07-16
    independent review found that fetching this inline (up to 3 sequential
    HTTP calls, up to ~60s worst case on a cache miss) sits on the live
    order-placement critical path: analyze_trade's caller places the order
    only after it returns, so a slow fetch would delay an already-decided
    trade's submission even though the signal itself never affects the
    decision. Call this instead at log_prediction time, which for real
    trades already happens AFTER order placement (see
    order_executor._auto_place_trades) -- fully decoupling the fetch from
    fill timing, and as a side effect skipping the fetch entirely for
    markets that get analyzed but never traded or shadow-logged.

    Extracts city/target_date/days_out/var from the analysis dict (the same
    shape analyze_trade() returns and log_prediction() receives). Returns
    None on any missing/malformed field, matching get_forecast_run_trend's
    own never-raises contract.
    """
    try:
        city = analysis.get("city")
        days_out = analysis.get("days_out")
        var = (analysis.get("condition") or {}).get("var", "max")
        target_date_raw = analysis.get("target_date")
        if city is None or days_out is None or target_date_raw is None:
            return None
        target_date = date.fromisoformat(target_date_raw)
        return get_forecast_run_trend(city, target_date, days_out, var)
    except Exception:
        return None


def backfill_emos_data(force: bool = False) -> tuple[int, int]:
    """Backfill EMOS training data for all settled predictions.

    Part 1 — settled_temp_f: calls audit_settlement for every outcome row where the
    actual observed temperature was not stored (pre-dates the store-temp code).
    With force=True, re-runs audit_settlement for EVERY settled outcome instead,
    including rows that already have a settled_temp_f value — needed after a fix
    to audit_settlement()'s own fetch/threshold logic (the normal NULL-only pass
    can never touch already-populated rows, however stale their value now is;
    see the 2026-07-05 ASOS-window-overreach fix, which needed a one-off script
    for exactly this before this flag existed).

    Part 2 — ens_mean: fetches the deterministic control-run forecast from the
    Previous Runs API (ICON + GFS + ECMWF AIFS single) at the correct lead time
    (previous_day{days_out}) for each multi-day prediction missing ens_mean.
    ens_var is left NULL — individual ensemble members are only stored for 3 days
    and no consistent-scale proxy exists; emos-train handles NULL ens_var by
    using only forward-fill rows (Jun 21 2026+) for variance calibration.

    Returns (settled_temp_filled, ens_filled) counts.
    """
    init_db()

    # ── Part 1: settled_temp_f ────────────────────────────────────────────────
    with _conn() as con:
        if force:
            temp_rows = con.execute(
                "SELECT o.ticker, o.settled_yes FROM outcomes o"
            ).fetchall()
        else:
            temp_rows = con.execute(
                "SELECT o.ticker, o.settled_yes FROM outcomes o WHERE o.settled_temp_f IS NULL"
            ).fetchall()

    label = (
        "all settled outcomes (force)" if force else "outcomes missing settled_temp_f"
    )
    print(f"[backfill] Part 1: {len(temp_rows)} {label}")
    settled_temp_filled = 0
    for row in temp_rows:
        try:
            # audit_settlement()'s return value is the source of truth for whether
            # it actually wrote a value — re-reading the DB afterward can't tell
            # "recomputed and matched" apart from "skipped and left the old value".
            if audit_settlement(row["ticker"], bool(row["settled_yes"])):
                settled_temp_filled += 1
                print(f"  temp OK {row['ticker']}")
        except Exception as exc:
            print(f"  SKIP {row['ticker']}: {exc}")

    # ── Part 2: ens_mean / ens_var ────────────────────────────────────────────
    with _conn() as con:
        # DISTINCT eliminates duplicate rows from multi-day re-scans of the same
        # ticker — each market needs only one API fetch regardless of how many
        # predicted_date rows it accumulated.
        # Filter on ens_mean IS NULL only (not ens_var) so that completed backfill
        # rows — which have ens_mean but intentionally NULL ens_var — are not
        # retried on every subsequent backfill-emos run.
        # DESC order: process newest dates first so recent data is filled before the
        # consecutive-skip circuit breaker aborts on old no-archive rows.
        null_ens_rows = con.execute(
            """
            SELECT DISTINCT p.ticker, p.city, p.market_date, p.condition_type, p.days_out
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.ens_mean IS NULL
              AND p.market_date IS NOT NULL
              AND (p.days_out IS NULL OR p.days_out >= 1)
            ORDER BY p.market_date DESC
            """
        ).fetchall()

    print(
        f"[backfill] Part 2: {len(null_ens_rows)} multi-day predictions missing ens_mean"
    )

    try:
        from weather_markets import CITY_COORDS as _coords
        from weather_markets import _model_weights as _wm_weights
    except Exception as exc:
        print(f"  ERROR: cannot import weather_markets: {exc}")
        return settled_temp_filled, 0

    ens_filled = 0
    consecutive_skip = 0  # circuit breaker: abort if Previous Runs API is down

    for row in null_ens_rows:
        ticker = row["ticker"]
        city = row["city"]
        market_date_str = row["market_date"]
        days_out_val = row["days_out"] or 1  # default to 1 if NULL

        if city not in _coords or not market_date_str:
            continue

        lat, lon, tz = _coords[city]

        # Determine which temperature variable from the MARKET TYPE, not the
        # condition (above/below/between).  KXHIGH markets measure the daily
        # high; KXLOWT markets measure the daily low.  Condition type only says
        # which side of the threshold the bet is on — it must not override this.
        # Matches analyze_trade's own logic: var = "min" if "LOW" in series else "max".
        ticker_upper = ticker.upper()
        if "HIGH" in ticker_upper:
            var = "max"
        elif "LOWT" in ticker_upper or "LOW" in ticker_upper:
            var = "min"
        else:
            var = "max"  # between markets default to high temperature

        try:
            target_date = date.fromisoformat(market_date_str)
        except ValueError:
            continue

        # Fetch the deterministic forecast from each model at the correct lead
        # time.  Individual ensemble members are only stored for 3 days, so we
        # use the Previous Runs API which archives control-run forecasts at fixed
        # lead offsets back to January 2024.  ens_var is left NULL for these
        # backfill rows; emos-train uses forward-fill rows (which have real
        # ensemble variance) for the variance calibration term.
        weights = _wm_weights(city, month=target_date.month)
        w_sum = 0.0
        w_mean = 0.0
        n_models = 0
        for ens_model, prev_model in _PREVIOUS_RUN_MODEL_MAP.items():
            val = _fetch_previous_run_daily(
                lat, lon, tz, target_date, prev_model, days_out_val, var
            )
            if val is None:
                continue
            w = weights.get(ens_model, 1.0)
            w_sum += w
            w_mean += w * val
            n_models += 1

        if n_models == 0:
            consecutive_skip += 1
            print(f"  SKIP {ticker}: no models returned data for {market_date_str}")
            if consecutive_skip >= 5:
                print(
                    "  [backfill] 5 consecutive SKIP rows — Previous Runs API "
                    "unavailable for these dates, stopping Part 2 early."
                )
                break
            continue

        consecutive_skip = 0
        ens_mean_val = round(w_mean / w_sum, 3)

        with _conn() as con:
            con.execute(
                "UPDATE predictions SET ens_mean = ? "
                "WHERE ticker = ? AND ens_mean IS NULL AND days_out IS ?",
                (ens_mean_val, ticker, row["days_out"]),
            )
        ens_filled += 1
        print(
            f"  ens OK {ticker}: mean={ens_mean_val:.1f}°F"
            f" ({n_models} models, days_out={days_out_val})"
        )

    return settled_temp_filled, ens_filled


def sync_outcomes(client) -> int:
    """
    Check settled markets in the DB against Kalshi and record outcomes.
    Returns number of new outcomes recorded.
    """
    init_db()
    with _conn() as con:
        # Include tickers that were marked not_found more than 7 days ago so a
        # transient Kalshi 404 doesn't permanently exclude a valid market.
        pending = con.execute("""
            SELECT DISTINCT ticker FROM predictions p
            WHERE NOT EXISTS (SELECT 1 FROM outcomes o WHERE o.ticker = p.ticker)
              AND (
                p.status IS NULL
                OR p.status = 'active'
                OR (p.status = 'not_found'
                    AND p.not_found_at < datetime('now', '-7 days'))
              )
        """).fetchall()

    count = 0
    now_utc = datetime.now(UTC)
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
                        )
                        hours_since = (now_utc - close_dt).total_seconds() / 3600
                        if hours_since < 1.0:
                            continue  # too soon; wait for finalization to stabilize
                    except (ValueError, TypeError):
                        pass
                if result not in ("yes", "no"):
                    _log.warning(
                        "sync_outcomes: %s voided/cancelled — unexpected result %r, "
                        "stamping status='voided' so it's not retried every cycle",
                        ticker,
                        result,
                    )
                    with _conn() as con:
                        con.execute(
                            "UPDATE predictions SET status = 'voided' WHERE ticker = ?",
                            (ticker,),
                        )
                    continue
                settled_yes = result == "yes"
                if log_outcome(ticker, settled_yes):
                    count += 1
                    # A3: update feature importance log so we can learn which signals predicted wins
                    try:
                        from feature_importance import update_outcome as _fi_update

                        _fi_update(ticker, settled_yes)
                    except Exception:
                        pass
                    # Cross-check Kalshi's outcome against Open-Meteo archive
                    try:
                        audit_settlement(ticker, settled_yes)
                    except Exception:
                        pass
                    # Backfill full OHLC price history for this now-settled market
                    # in one call (candlesticks endpoint takes a start/end range).
                    # sync_outcomes only revisits a ticker while it has no outcome
                    # row yet, so this fires exactly once per market — no per-cycle
                    # polling. Unlocks entry-timing / adverse-selection analysis
                    # (see backlog); failure here must never block outcome recording.
                    # period_interval=60 (hourly, not 1-minute): weather markets can
                    # stay open several days (see MAX_DAYS_OUT), and Kalshi's
                    # candlesticks endpoint caps periods returned per request --
                    # 1-minute resolution over a multi-day window risks silently
                    # truncating/erroring on exactly the long-open markets this
                    # feature targets. Hourly is still plenty for edge-decay/
                    # adverse-selection timing analysis and stays comfortably
                    # under any plausible per-request cap.
                    try:
                        _candle_series = market.get("series_ticker")
                        _candle_open_str = market.get("open_time")
                        if _candle_series and _candle_open_str:
                            _candle_start = datetime.fromisoformat(
                                _candle_open_str.replace("Z", "+00:00")
                            )
                            _candle_end = (
                                datetime.fromisoformat(
                                    close_time_str.replace("Z", "+00:00")
                                )
                                if close_time_str
                                else now_utc
                            )
                            _candles = client.get_candlesticks(
                                _candle_series,
                                ticker,
                                int(_candle_start.timestamp()),
                                int(_candle_end.timestamp()),
                                period_interval=60,
                            )
                            log_price_candles(ticker, _candle_series, 60, _candles)
                    except Exception as _candle_exc:
                        _log.warning(
                            "sync_outcomes: price-history backfill failed for %s: %s",
                            ticker,
                            _candle_exc,
                        )
                    # #55: settle analysis_attempts for this ticker regardless of
                    # was_traded — the outcome is a market fact, not a trade fact.
                    # settle_analysis_attempt (called from paper.py) only ever fires
                    # for TRADED markets, so untraded rows previously never got an
                    # outcome and get_unselected_bias() always returned 0.0.
                    try:
                        with _conn() as con:
                            pending_attempts = con.execute(
                                "SELECT target_date FROM analysis_attempts "
                                "WHERE ticker = ? AND outcome IS NULL",
                                (ticker,),
                            ).fetchall()
                        for attempt_row in pending_attempts:
                            settle_analysis_attempt(
                                ticker, attempt_row["target_date"], int(settled_yes)
                            )
                    except Exception:
                        pass
        except Exception as exc:
            # 404 means the market was not found on Kalshi — stamp not_found_at so
            # sync_outcomes re-attempts after 7 days.  Permanent blacklisting was
            # removed because transient Kalshi 404s (API glitches, load balancer
            # quirks) were silently dropping valid markets from Brier/P&L stats.
            if "404" in str(exc):
                _log.warning(
                    "sync_outcomes: %s not found on Kalshi (404) — will retry after 7 days",
                    ticker,
                )
                with _conn() as con:
                    con.execute(
                        "UPDATE predictions SET status = 'not_found', not_found_at = datetime('now') "
                        "WHERE ticker = ?",
                        (ticker,),
                    )
            else:
                _log.warning(
                    "sync_outcomes: failed to fetch/record %s: %s", ticker, exc
                )
            continue
    return count


def log_member_score(
    city: str,
    model: str,
    predicted_temp: float,
    actual_temp: float,
    target_date_str: str,
    var: str | None = None,
) -> None:
    """Log an ensemble member's temperature prediction vs actuals for accuracy tracking.

    var should be "max" for daily-HIGH markets or "min" for daily-LOW markets —
    daily-high and daily-low forecast errors have different sign/magnitude and
    must not be pooled (see get_dynamic_station_bias).

    Deduplicates on (city, model, target_date, var) via idx_ems_dedup — multiple
    trades settling in the same city/date (e.g. two thresholds on one market)
    would otherwise each insert an identical row, over-weighting that day in
    get_model_weights/get_dynamic_station_bias.
    """
    init_db()
    with _conn() as con:
        con.execute(
            """
            INSERT OR IGNORE INTO ensemble_member_scores
              (city, model, predicted_temp, actual_temp, target_date, var, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (city, model, predicted_temp, actual_temp, target_date_str, var),
        )


def get_member_accuracy(days_back: int = 60) -> dict:
    """
    Per-model MAE filtered to recent predictions, used by learn_seasonal_weights().
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
              AND model != 'blended'
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
            # R25: per-city observation counts so _weights_from_mae can gate on
            # sample size rather than number of distinct cities.
            "city_n_breakdown": {c: len(v) for c, v in city_errs.items()},
        }
    return result


def get_model_brier_scores(days: int = 30) -> dict[str, float]:
    """Return per-model mean absolute error from ensemble_member_scores over the last N days.

    Returns {model_name: mean_abs_error} for models with at least 10 scored rows.
    Lower MAE = better model. Returns empty dict when no data available.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model,
                   AVG(ABS(predicted_temp - actual_temp)) AS mae,
                   COUNT(*) AS n
            FROM   ensemble_member_scores
            WHERE  logged_at >= datetime('now', ? || ' days')
              AND  actual_temp IS NOT NULL
              AND  predicted_temp IS NOT NULL
              AND  model != 'blended'
            GROUP  BY model
            HAVING COUNT(*) >= 10
            """,
            (f"-{days}",),
        ).fetchall()
    return {r[0]: float(r[1]) for r in rows}


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
              AND model != 'blended'
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


def get_model_weights(city: str, window_days: int = 30) -> dict[str, float]:
    """
    Softmax-normalised inverse-MAE weights for each ensemble model.

    Uses ensemble_member_scores for `city` over the last `window_days`.
    Softmax is applied over negative-MAE so lower error → higher weight.
    Falls back to equal weights (each = 1/n) when fewer than 10 observations
    exist for any model.

    Returns a dict summing to 1.0, e.g. {'gfs': 0.42, 'ecmwf': 0.35, 'nbm': 0.23}.
    """
    import math

    MIN_OBSERVATIONS = 10
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model, predicted_temp, actual_temp
            FROM ensemble_member_scores
            WHERE city = ?
              AND predicted_temp IS NOT NULL
              AND actual_temp IS NOT NULL
              AND model != 'blended'
              AND logged_at >= datetime('now', ? || ' days')
            """,
            (city, f"-{window_days}"),
        ).fetchall()

    if not rows:
        return {}

    by_model: dict[str, list[float]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(
            abs(r["predicted_temp"] - r["actual_temp"])
        )

    # Require minimum observations per model; fall back to equal weights otherwise
    if any(len(errs) < MIN_OBSERVATIONS for errs in by_model.values()):
        n = len(by_model)
        return {m: round(1.0 / n, 6) for m in by_model} if n else {}

    mae_per_model = {m: sum(errs) / len(errs) for m, errs in by_model.items()}

    # Softmax over negative MAE: lower error → higher weight
    scores = {m: -mae for m, mae in mae_per_model.items()}
    max_score = max(scores.values())
    exps = {m: math.exp(s - max_score) for m, s in scores.items()}  # numerically stable
    total = sum(exps.values())
    return {m: round(v / total, 6) for m, v in exps.items()}


def get_dynamic_station_bias(
    city: str,
    var: str = "max",
    min_samples: int = 10,
) -> tuple[float, int]:
    """Return mean signed temperature error (predicted - actual) per city from
    real METAR observations logged at settlement.

    Positive return value means the models run warm for this city (they over-predict
    temperature); negative means models run cold (they under-predict).  The caller
    should subtract this from the raw forecast temperature before computing probability.

    Prioritises rows where model = 'blended' (the exact blended forecast_temp used
    at trade entry) when available; falls back to icon_seamless + gfs_seamless
    averages when no blended rows exist yet.

    Only rows tagged with the matching var ("max"/"min") are used — daily-high and
    daily-low forecast errors have different sign/magnitude and must not be pooled.
    Rows logged before the var column existed are NULL and are excluded.

    Returns (mean_signed_error, sample_count).  Returns (0.0, 0) when the city has
    fewer than min_samples observations — caller keeps the static bias table.
    """
    init_db()
    try:
        with _conn() as con:
            # Prefer 'blended' rows (exact forecast_temp recorded since Plan 3 was deployed)
            blended_rows = con.execute(
                """
                SELECT predicted_temp, actual_temp
                FROM ensemble_member_scores
                WHERE city = ? AND model = 'blended' AND var = ?
                  AND predicted_temp IS NOT NULL AND actual_temp IS NOT NULL
                """,
                (city, var),
            ).fetchall()

            if len(blended_rows) >= min_samples:
                errors = [r["predicted_temp"] - r["actual_temp"] for r in blended_rows]
                return round(sum(errors) / len(errors), 4), len(errors)

            # Fall back to icon_seamless + gfs_seamless only (matches docstring;
            # 'blended' rows are derived from these and would otherwise be
            # triple-counted alongside their own components).
            all_rows = con.execute(
                """
                SELECT predicted_temp, actual_temp
                FROM ensemble_member_scores
                WHERE city = ? AND var = ?
                  AND model IN ('icon_seamless', 'gfs_seamless')
                  AND predicted_temp IS NOT NULL AND actual_temp IS NOT NULL
                """,
                (city, var),
            ).fetchall()

            if len(all_rows) < min_samples:
                return 0.0, len(all_rows)

            errors = [r["predicted_temp"] - r["actual_temp"] for r in all_rows]
            return round(sum(errors) / len(errors), 4), len(errors)

    except Exception as exc:
        _log.debug("get_dynamic_station_bias(%s): %s", city, exc)
        return 0.0, 0


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
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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

    # Walk threshold from high to low, accumulate TPR/FPR. Group tied
    # probabilities into a single point per distinct threshold (the standard
    # tie treatment) instead of one point per row -- per-row points within a
    # tie group make AUC depend on arbitrary DB scan order (a tie group could
    # score as a full-area or zero-area staircase depending on whether
    # positives or negatives happen to come first in that scan).
    tp = fp = 0
    roc_full: list[tuple[float, float]] = [(0.0, 0.0)]
    for _prob, group in itertools.groupby(sorted_rows, key=lambda r: r["our_prob"]):
        for r in group:
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
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


# ── P9.1: Strategy version performance comparison ─────────────────────────────

_RETIRED_PATH = _project_root() / "data" / "retired_strategies.json"
_PINS_PATH = _project_root() / "data" / "strategy_pins.json"


def _get_strategy_pins() -> dict[str, str]:
    """Return {method: pinned_until_iso} for currently active (non-expired) pins.

    Expired and malformed entries are pruned from the returned dict on every
    read (a single corrupted entry can never silently clear all pins), but NOT
    written back to disk here — see the comment below for why. The on-disk
    file still gets pruned, just lazily, on the next real write (unretire_strategy
    or the cron ensemble-pin auto-renew), not eagerly on every read.
    """
    if not _PINS_PATH.exists():
        return {}
    try:
        import json as _json

        raw = _json.loads(_PINS_PATH.read_text(encoding="utf-8"))
    except Exception as _e:
        _log.warning(
            "strategy_pins: failed to read %s — treating all pins as empty: %s",
            _PINS_PATH,
            _e,
        )
        return {}
    # Keep only entries that parse correctly and have not yet expired.
    # Handles naive datetimes written by older code by treating them as UTC.
    now = datetime.now(UTC)
    active: dict[str, str] = {}
    for method, until_str in raw.items():
        try:
            until = datetime.fromisoformat(until_str)
            if until.tzinfo is None:
                until = until.replace(tzinfo=UTC)
            if now < until:
                active[method] = until_str
        except Exception:
            pass  # malformed entry — discard silently
    # Prune in-memory only — do NOT write the pruned dict back here. This
    # function runs from multiple processes (cron + CLI) with no lock around
    # read-then-write; a write-on-read could race with unretire_strategy's own
    # read-modify-write and silently erase a pin it just added. Real writers
    # (unretire_strategy, auto-retire) already save a freshly-pruned dict via
    # this same function, so expired entries still get dropped from disk the
    # next time any real write happens — just not eagerly on every read.
    return active


def _save_strategy_pins(pins: dict[str, str]) -> None:
    import json as _json
    import os as _os
    import tempfile as _tempfile

    _PINS_PATH.parent.mkdir(exist_ok=True)
    with _tempfile.NamedTemporaryFile(
        "w",
        dir=_PINS_PATH.parent,
        prefix=".pins_",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        _json.dump(pins, tmp, indent=2)
        tmp_name = tmp.name
    _os.replace(tmp_name, _PINS_PATH)


def is_strategy_pinned(method: str) -> bool:
    """Return True if method has an active retirement-immunity pin."""
    pins = _get_strategy_pins()
    until_str = pins.get(method)
    if not until_str:
        return False
    try:
        until = datetime.fromisoformat(until_str)
        # Treat naive datetimes as UTC so an old pin written without a timezone
        # suffix never raises TypeError on comparison with datetime.now(UTC).
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        return datetime.now(UTC) < until
    except Exception:
        return False


def get_brier_by_version(min_samples: int = 10) -> dict[str, dict]:
    """P9.1: Brier score and sample count grouped by edge_calc_version.

    Returns {version: {"brier": float, "n": int}} for versions with enough settled
    predictions. Enables formal comparison across strategy releases.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.edge_calc_version, p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND p.edge_calc_version IS NOT NULL
        """).fetchall()

    by_version: dict[str, list[float]] = {}
    for r in rows:
        by_version.setdefault(r["edge_calc_version"], []).append(
            (r["our_prob"] - r["settled_yes"]) ** 2
        )

    return {
        v: {"brier": round(sum(errs) / len(errs), 4), "n": len(errs)}
        for v, errs in by_version.items()
        if len(errs) >= min_samples
    }


def get_pnl_by_signal_source(min_samples: int = 10) -> dict[str, dict]:
    """
    Compute Brier score and win rate grouped by signal_source.
    Reveals which signal drives the most profitable trades.

    Despite the name, this is a calibration hit-rate, not real trade P&L —
    it has never joined against placed-trade data. Rows may include
    is_shadow=1 predictions (analyzed and gate-passing, but never actually
    traded, e.g. during TRADING_PAUSED); those are included in brier/win_rate
    (so the score stays representative of forecast quality), but n_shadow is
    reported separately so a caller can tell how many of the n samples had no
    real money behind them.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                COALESCE(p.signal_source, 'unknown') AS source,
                p.our_prob,
                o.settled_yes,
                p.is_shadow
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
            """
        ).fetchall()

    groups: dict[str, list[tuple[float, bool, bool]]] = {}
    for source, our_prob, settled_yes, is_shadow in rows:
        groups.setdefault(source, []).append(
            (float(our_prob), bool(settled_yes), bool(is_shadow))
        )

    result = {}
    for source, samples in groups.items():
        if len(samples) < min_samples:
            continue
        brier = sum((p - (1 if y else 0)) ** 2 for p, y, _ in samples) / len(samples)
        wins = sum(1 for p, y, _ in samples if (y and p > 0.5) or (not y and p <= 0.5))
        result[source] = {
            "brier": round(brier, 4),
            "n": len(samples),
            "win_rate": round(wins / len(samples), 3),
            "n_shadow": sum(1 for _, _, shadow in samples if shadow),
        }
    return result


# ── P9.5: Strategy retirement ─────────────────────────────────────────────────


def get_retired_strategies() -> dict[str, dict]:
    """P9.5: Load retired strategy methods from disk.

    Returns {method: {"retired_at": str, "reason": str, "brier": float}}.
    """
    if not _RETIRED_PATH.exists():
        return {}
    try:
        import json as _json

        with open(_RETIRED_PATH) as f:
            return _json.load(f)
    except Exception:
        return {}


def _save_retired_strategies(retired: dict) -> None:
    import json as _json
    import os as _os
    import tempfile as _tempfile

    _RETIRED_PATH.parent.mkdir(exist_ok=True)
    fd, tmp = _tempfile.mkstemp(
        dir=_RETIRED_PATH.parent, prefix=".retired_", suffix=".json"
    )
    try:
        with _os.fdopen(fd, "w") as f:
            _json.dump(retired, f, indent=2)
        _os.replace(tmp, _RETIRED_PATH)
    except Exception:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise


def auto_retire_strategies(
    min_samples: int = 20,
    retire_threshold: float = 0.25,
    current_directional_accuracy: float | None = None,
    dir_accuracy_guard: float = 0.65,
    rolling_window: int = 20,
) -> list[str]:
    """P9.5: Auto-retire forecasting methods whose Brier score exceeds retire_threshold.

    Brier score > 0.25 means worse than random chance. Methods are persisted to
    data/retired_strategies.json and can be unretired via unretire_strategy().

    Args:
        min_samples: minimum settled predictions required before a method is eligible.
        retire_threshold: Brier score above which a method is considered failing.
        current_directional_accuracy: system-wide multi-day directional accuracy (0–1).
            When provided, methods are NOT retired if accuracy >= dir_accuracy_guard
            because elevated Brier in that case reflects miscalibrated probabilities,
            not a wrong-direction forecasting failure. Calibration is fixable; bad
            direction is not.
        dir_accuracy_guard: directional accuracy threshold below which the guard is
            inactive and Brier-based retirement proceeds normally. Default 0.65.
        rolling_window: methods are NOT retired if their rolling Brier over the last
            `rolling_window` settled predictions is already back at/under
            retire_threshold — a lifetime average can stay elevated long after a
            method has recovered, since old bad trades never roll off it.

    Returns list of newly retired method names.
    """
    now_str = datetime.now(UTC).isoformat()
    scores = brier_score_by_method(min_samples=min_samples)
    rolling_scores = brier_score_by_method_rolling(window=rolling_window, min_samples=1)
    retired = get_retired_strategies()
    newly_retired: list[str] = []

    for method, brier in scores.items():
        if method not in retired and brier > retire_threshold:
            if is_strategy_pinned(method):
                _log.info(
                    "strategy_retirement: skipping re-retirement of pinned method=%s "
                    "(Brier %.4f > threshold %.4f — pin still active)",
                    method,
                    brier,
                    retire_threshold,
                )
                continue
            if (
                current_directional_accuracy is not None
                and current_directional_accuracy >= dir_accuracy_guard
            ):
                _log.info(
                    "strategy_retirement: skipping method=%s "
                    "(Brier %.4f > threshold %.4f but directional_accuracy=%.2f >= guard=%.2f "
                    "— elevated Brier is a calibration issue, not a forecasting failure)",
                    method,
                    brier,
                    retire_threshold,
                    current_directional_accuracy,
                    dir_accuracy_guard,
                )
                continue
            rolling_brier = rolling_scores.get(method)
            if rolling_brier is not None and rolling_brier <= retire_threshold:
                _log.info(
                    "strategy_retirement: skipping method=%s (lifetime Brier %.4f > "
                    "threshold %.4f but rolling last-%d Brier %.4f <= threshold — "
                    "recent performance recovered)",
                    method,
                    brier,
                    retire_threshold,
                    rolling_window,
                    rolling_brier,
                )
                continue
            retired[method] = {
                "retired_at": now_str,
                "reason": (
                    f"Brier {brier:.4f} (lifetime) / "
                    f"{rolling_brier:.4f} (last {rolling_window}) "
                    if rolling_brier is not None
                    else f"Brier {brier:.4f} (lifetime) "
                )
                + f"> threshold {retire_threshold:.4f}",
                "brier": brier,
                "rolling_brier": rolling_brier,
            }
            newly_retired.append(method)
            _log.warning(
                "strategy_retirement: retired method=%s brier=%.4f threshold=%.4f",
                method,
                brier,
                retire_threshold,
            )

    if newly_retired:
        _save_retired_strategies(retired)

    return newly_retired


def unretire_strategy(method: str, pin_hours: float = 72.0) -> bool:
    """P9.5: Manually un-retire a strategy method. Returns True if it was retired.

    Also writes a retirement-immunity pin for ``pin_hours`` (default 72 h) so
    that the very next cron run does not immediately re-retire the method if
    its Brier is still above the threshold.  Pass pin_hours=0 to skip the pin.
    """
    retired = get_retired_strategies()
    if method in retired:
        del retired[method]
        _save_retired_strategies(retired)
        _log.info("strategy_retirement: un-retired method=%s", method)
        if pin_hours > 0:
            pins = _get_strategy_pins()
            from datetime import timedelta as _td

            pins[method] = (datetime.now(UTC) + _td(hours=pin_hours)).isoformat()
            _save_strategy_pins(pins)
            _log.info(
                "strategy_retirement: pinned method=%s for %.0f h (until %s)",
                method,
                pin_hours,
                pins[method][:19],
            )
        return True
    return False


# ── P10.1: Drift detection ────────────────────────────────────────────────────


def detect_brier_drift(
    min_weeks: int = 6,
    degradation_threshold: float = 0.05,
) -> dict:
    """P10.1: Detect slow Brier score degradation over time.

    Splits available weekly Brier scores into an early half and recent half.
    Flags drift when recent_avg - early_avg > degradation_threshold.

    Returns:
        {
            "drifting": bool,
            "early_brier": float | None,
            "recent_brier": float | None,
            "delta": float | None,
            "weeks_analyzed": int,
            "message": str,
        }
    """
    weekly = get_brier_over_time(weeks=24)
    n = len(weekly)

    if n < min_weeks:
        return {
            "drifting": False,
            "early_brier": None,
            "recent_brier": None,
            "delta": None,
            "weeks_analyzed": n,
            "message": f"Insufficient data: {n} weeks (need {min_weeks})",
        }

    mid = n // 2
    early = weekly[:mid]
    recent = weekly[mid:]

    early_avg = sum(w["brier"] for w in early) / len(early)
    recent_avg = sum(w["brier"] for w in recent) / len(recent)
    delta = recent_avg - early_avg
    drifting = delta > degradation_threshold

    if drifting:
        _log.warning(
            "drift_detection: Brier degraded early=%.4f recent=%.4f delta=+%.4f (threshold=%.4f)",
            early_avg,
            recent_avg,
            delta,
            degradation_threshold,
        )

    return {
        "drifting": drifting,
        "early_brier": round(early_avg, 4),
        "recent_brier": round(recent_avg, 4),
        "delta": round(delta, 4),
        "weeks_analyzed": n,
        "message": (
            f"Drift detected: Brier degraded +{delta:.4f} (early={early_avg:.4f} → recent={recent_avg:.4f})"
            if drifting
            else f"No drift: delta={delta:+.4f} (early={early_avg:.4f}, recent={recent_avg:.4f})"
        ),
    }


def format_brier_alert(scores: list[float]) -> str:
    """Return a multi-line BrierAlert string with explanation and actionable next steps.

    Args:
        scores: The two most recent weekly Brier scores that exceeded the threshold.
    """
    from utils import BRIER_ALERT_THRESHOLD

    scores_str = ", ".join(f"{s:.4f}" for s in scores)
    return (
        f"[BrierAlert] Brier score has exceeded {BRIER_ALERT_THRESHOLD} for two consecutive"
        f" weeks ({scores_str}).\n"
        f"  What this means: your model's probability forecasts are poorly calibrated.\n"
        f"  Next steps:\n"
        f"    1. Run: py main.py calibrate             (trains temperature scaling + recalibrates blend weights)\n"
        f"    2. Run: py main.py validate              (shows calibration curve — which buckets are off and by how much)\n"
        f"    3. Run: py main.py backtest --days 180   (shows synthetic archive Brier + live model calibration curve)\n"
        f"    4. Temperature scaling is the primary fix — check data/temperature_scale.json exists after step 1\n"
        f"  Live trading will continue but consider pausing until Brier < {BRIER_ALERT_THRESHOLD}."
    )


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
                """INSERT INTO analysis_attempts
                   (ticker, city, condition, target_date, analyzed_at,
                    forecast_prob, market_prob, days_out, was_traded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ticker, target_date) DO UPDATE SET
                       analyzed_at    = excluded.analyzed_at,
                       forecast_prob  = excluded.forecast_prob,
                       market_prob    = excluded.market_prob,
                       days_out       = excluded.days_out,
                       was_traded     = MAX(analysis_attempts.was_traded,
                                            excluded.was_traded)""",
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


def batch_log_analysis_attempts(attempts: list[dict]) -> None:
    """#perf: Bulk-insert analysis attempts in a single transaction (much faster than
    calling log_analysis_attempt per row when scanning 100+ markets)."""
    if not attempts:
        return
    init_db()
    from datetime import UTC as _UTC

    analyzed_at = datetime.now(_UTC).isoformat()
    rows = []
    for a in attempts:
        td = a.get("target_date")
        target_str = (
            td.isoformat() if td is not None and hasattr(td, "isoformat") else str(td)
        )
        rows.append(
            (
                a.get("ticker", ""),
                a.get("city"),
                a.get("condition"),
                target_str,
                analyzed_at,
                float(a.get("forecast_prob", 0.0)),
                float(a.get("market_prob", 0.0)),
                int(a.get("days_out", 0)),
                1 if a.get("was_traded") else 0,
            )
        )
    try:
        with _conn() as con:
            con.executemany(
                """INSERT INTO analysis_attempts
                   (ticker, city, condition, target_date, analyzed_at,
                    forecast_prob, market_prob, days_out, was_traded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ticker, target_date) DO UPDATE SET
                       analyzed_at    = excluded.analyzed_at,
                       forecast_prob  = excluded.forecast_prob,
                       market_prob    = excluded.market_prob,
                       days_out       = excluded.days_out,
                       was_traded     = MAX(analysis_attempts.was_traded,
                                            excluded.was_traded)""",
                rows,
            )
    except Exception as exc:
        _log.warning("batch_log_analysis_attempts failed: %s", exc)


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
    """#55: Mean (forecast_prob - outcome) for untraded markets in this city.

    KNOWN LIMITATION: outcome is only populated for analysis_attempts rows
    whose ticker also has a predictions row (settled via sync_outcomes' new
    settlement block, see there) — this covers attempts that passed the edge
    filter but weren't traded (e.g. TRADING_PAUSED shadow predictions), not
    the majority of attempts logged via cron's batch_log_analysis_attempts
    for markets that never passed the edge filter at all (no predictions row
    is ever written for those). On the live DB as of 2026-07-10 that's ~98%
    of the untraded population, so this function currently reflects a
    selection-biased subset, not the full "markets we rejected" population
    its docstring implies. Fixing this fully would need a separate
    settlement sweep over analysis_attempts tickers lacking a predictions
    row (~2,000 tickers on the live DB, i.e. ~2,000 extra Kalshi API calls
    per cron cycle) — not done here since this function has zero production
    callers today. Build that sweep before wiring this into anything real.
    """
    init_db()
    try:
        with _conn() as con:
            if condition_type:
                rows = con.execute(
                    """SELECT forecast_prob, outcome FROM analysis_attempts
                       WHERE city=? AND condition=? AND was_traded=0
                         AND outcome IS NOT NULL AND forecast_prob IS NOT NULL""",
                    (city, condition_type),
                ).fetchall()
            else:
                rows = con.execute(
                    """SELECT forecast_prob, outcome FROM analysis_attempts
                       WHERE city=? AND was_traded=0
                         AND outcome IS NOT NULL AND forecast_prob IS NOT NULL""",
                    (city,),
                ).fetchall()

            if not rows:
                return 0.0
            errors = [fp - o for fp, o in rows]
            return round(sum(errors) / len(errors), 4)
    except Exception as exc:
        _log.warning("get_unselected_bias failed for %s: %s", city, exc)
        return 0.0


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
                JOIN outcomes_valid o ON a.ticker = o.ticker
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
               FROM multiday_predictions
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


# ── B2: Dynamic Correlation Matrix ────────────────────────────────────────────


def get_recent_city_correlations(days: int = 60, min_pairs: int = 5) -> dict:
    """Compute pairwise city temperature correlations from recent settled outcomes.

    Returns {(city_a, city_b): correlation_coefficient} for pairs with enough data.
    Falls back to empty dict when insufficient data.
    """
    init_db()
    # Plain date cutoff (not a datetime isoformat) so it matches market_date's
    # 'YYYY-MM-DD' format under lexicographic comparison.
    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.city, o.settled_temp_f, p.market_date
            FROM   predictions p
            JOIN   outcomes_valid o ON o.ticker = p.ticker
            WHERE  (p.days_out IS NULL OR p.days_out >= 1)
              AND  p.market_date >= ?
              AND  o.settled_temp_f IS NOT NULL
              AND  p.city IS NOT NULL
              AND  UPPER(p.ticker) LIKE '%HIGH%'
            """,
            (cutoff,),
        ).fetchall()

    # Restricted to daily-HIGH markets above — mixing HIGH and LOW temps in one
    # per-city series would corrupt the correlation (a city's LOW and HIGH on
    # the same day are ~20-30F apart and not the same physical quantity).
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    for city, temp, market_date in rows:
        date_str = str(market_date)[:10]
        by_date[date_str][city] = float(temp)

    city_data: dict[str, list[float]] = defaultdict(list)
    date_index: dict[str, list[str]] = defaultdict(list)
    for date_str, city_temps in sorted(by_date.items()):
        for city, temp in city_temps.items():
            city_data[city].append(temp)
            date_index[city].append(date_str)

    cities = list(city_data.keys())
    correlations = {}
    for i, c1 in enumerate(cities):
        for c2 in cities[i + 1 :]:
            dates1 = set(date_index[c1])
            dates2 = set(date_index[c2])
            common = sorted(dates1 & dates2)
            if len(common) < min_pairs:
                continue
            v1 = [city_data[c1][date_index[c1].index(d)] for d in common]
            v2 = [city_data[c2][date_index[c2].index(d)] for d in common]
            n = len(v1)
            mx = sum(v1) / n
            my = sum(v2) / n
            num = sum((a - mx) * (b - my) for a, b in zip(v1, v2))
            d1 = math.sqrt(sum((a - mx) ** 2 for a in v1))
            d2 = math.sqrt(sum((b - my) ** 2 for b in v2))
            if d1 > 0 and d2 > 0:
                correlations[(c1, c2)] = round(num / (d1 * d2), 3)
    return correlations


def get_edge_realization_by_city() -> list[dict]:
    # Compare declared edge at entry vs actual win rate to see which cities deliver on predicted edge.
    # edge is signed (blended_prob - market_prob): negative edge means the model
    # recommended the NO side, for which settled_yes=0 is a WIN. win_rate must be
    # side-adjusted, not the raw market YES-rate, or a city that's consistently
    # correct on the NO side displays as a 0% "loser" with negative mean_edge.
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT sub.city,
                   AVG(ABS(sub.edge)) as mean_edge,
                   AVG(CASE WHEN sub.edge >= 0 THEN CAST(o.settled_yes AS REAL)
                            ELSE 1.0 - CAST(o.settled_yes AS REAL) END) as win_rate,
                   COUNT(*) as n
            FROM (
                SELECT ticker, city, edge,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY predicted_at DESC) as rn
                FROM   multiday_predictions
                WHERE  edge IS NOT NULL
            ) sub
            JOIN   outcomes_valid o ON o.ticker = sub.ticker
            WHERE  sub.rn = 1
            GROUP  BY sub.city
            HAVING COUNT(*) >= 5
            ORDER  BY mean_edge DESC
            """
        ).fetchall()
    return [
        {
            "city": r[0],
            "mean_edge": round(r[1], 4),
            "win_rate": round(r[2], 3),
            "n": r[3],
        }
        for r in rows
    ]


def vacuum_database() -> None:
    # Reclaim free pages after bulk deletes — VACUUM cannot run in a transaction
    import sqlite3 as _sqlite3_vac

    with _sqlite3_vac.connect(str(DB_PATH), isolation_level=None) as con:
        before = con.execute("PRAGMA page_count").fetchone()[0]
        con.execute("PRAGMA wal_checkpoint(FULL)")
        con.execute("VACUUM")
        after = con.execute("PRAGMA page_count").fetchone()[0]
    _log.info(
        "VACUUM complete: page_count %d → %d (freed %d pages)",
        before,
        after,
        before - after,
    )


def prune_old_analysis_attempts(days: int = 30) -> int:
    # Remove stale analysis records to keep the table from growing indefinitely
    from datetime import UTC, datetime, timedelta

    init_db()
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM analysis_attempts WHERE analyzed_at < ?", (cutoff,)
        )
        n = cur.rowcount
    _log.info("pruned %d old analysis_attempts (older than %d days)", n, days)
    return n
