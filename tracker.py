"""
Prediction tracker — SQLite-backed log of every prediction we make.
After markets settle, records outcomes so we can:
  - Compute Brier scores (are our probabilities well-calibrated?)
  - Detect per-city/season bias and correct for it
  - Show a history of past calls
"""

from __future__ import annotations

import contextlib
import itertools
import logging
import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

from forecast_cache import ForecastCache
from paths import DB_PATH
from safe_io import project_root as _project_root
from utils import sql_normalize_iso_column
from utils import utc_today as _utc_today

_log = logging.getLogger(__name__)

DB_PATH.parent.mkdir(exist_ok=True)

_db_initialized = False

_SCHEMA_VERSION = 61  # increment when _MIGRATIONS list grows

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
    # v45 -> v47: liquidity-aware dynamic edge threshold (backlog.txt
    # "LIQUIDITY-AWARE SIZING + DYNAMIC EDGE THRESHOLD"), 2 columns added as
    # 2 separate migration steps (v46/v47). liquidity_edge_scale is
    # weather_markets._liquidity_edge_scale()'s multiplier (>=1.0, raised in
    # thin books); gated_edge = adjusted_edge / liquidity_edge_scale.
    # Log-only -- NEVER used for STRONG/MED/MIN signal classification
    # (deliberately computed at the scan-loop level, not inside
    # analyze_trade()). See the backlog entry's ENABLEMENT TRIGGER: revisit
    # once enough settled trades exist to check whether trades gated_edge
    # would have downgraded a tier actually underperformed trades that
    # stayed at the same tier under both.
    "ALTER TABLE predictions ADD COLUMN liquidity_edge_scale REAL",  # v46
    "ALTER TABLE predictions ADD COLUMN gated_edge REAL",  # v47
    # v47 -> v49: trade_history — public trade-flow history captured per
    # settled market (backfilled once, from sync_outcomes, via Kalshi's
    # public GET /markets/trades endpoint), table + index as 2 separate
    # migration steps (v48/v49) matching this list's one-ALTER/CREATE-per-
    # entry convention (same shape as price_history's own table+index pair).
    # Same "data accumulates regardless of process uptime" property that
    # justified price_history's candlestick capture (backlog.txt "HISTORICAL
    # MARKET-PRICE CAPTURE"), but with direction (taker_outcome_side) that
    # OHLC candles lack -- unlocks adverse-selection analysis (informed flow
    # vs. our own fill times, joined against execution_log's filled_at/
    # market_mid_at_fill) and "did informed flow precede settlement-
    # direction moves" (backlog.txt "PUBLIC TRADES REST BACKFILL"). trade_id
    # is Kalshi's own globally unique identifier per trade, so it's the
    # natural dedup key (unlike price_history, which needed a composite key
    # since candlesticks have no natural single-field ID).
    """CREATE TABLE IF NOT EXISTS trade_history (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id           TEXT    NOT NULL UNIQUE,
        ticker             TEXT    NOT NULL,
        count              REAL,
        yes_price          REAL,
        no_price           REAL,
        taker_outcome_side TEXT,
        taker_book_side    TEXT,
        is_block_trade     INTEGER,
        created_time       TEXT,
        logged_at          TEXT    NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_trade_history_ticker "
    "ON trade_history(ticker, created_time)",
    # v49 -> v50: probation predictions -- fresh, post-retirement evidence for
    # a retired forecasting method (backlog.txt "AUTO UN-RETIREMENT"). Distinct
    # from is_shadow: analyze_trade()'s retired-method gate returns None before
    # any prediction is logged, so a retired method could never generate new
    # evidence of recovery -- auto_retire_strategies()'s rolling-Brier
    # "recovery" check was only ever measuring old pre-retirement predictions
    # rolling through the window. check_retirement_probation() logs these via
    # analyze_trade(bypass_retirement_check=True) purely to feed
    # brier_score_probation_rolling(), which auto-unretirement gates on. Kept
    # as its own column rather than folded into is_shadow so the probation
    # query stays a clean, auditable is_probation=1 filter instead of also
    # needing to exclude ordinary shadow rows for other (non-retired) methods.
    "ALTER TABLE predictions ADD COLUMN is_probation INTEGER DEFAULT 0",
    # v50 -> v51, v51 -> v52: generic ground-truth columns for market types
    # other than daily temperature (backlog.txt "NO MARKET-TYPE SEAM").
    # settled_temp_f stays as the daily-HIGH/LOW column, untouched, with every
    # existing read/write site unmodified -- these are purely additive, for
    # new market types (starting with KXTEMPxxxH hourly-directional) going
    # forward. No backfill: rows logged before these columns existed can't be
    # recovered, same reasoning as the v34->v35 ensemble_member_scores.var
    # migration's own documented gap.
    "ALTER TABLE outcomes ADD COLUMN settled_value REAL",
    "ALTER TABLE outcomes ADD COLUMN settled_var TEXT",
    # v52 -> v53: single source of truth for which physical quantity ("max"
    # daily/hourly-high-role or "min" daily/hourly-low-role) a prediction is
    # about (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2
    # handoff item 2 -- the var-derivation duplicate-and-dangerous-default
    # bug). Previously derived independently at 5 separate call sites from
    # ticker substrings, which never match KXTEMPxxxH tickers ("HIGH"/"LOW"/
    # "LOWT" don't appear in them) and silently defaulted to "max". Populated
    # once by log_prediction() from analysis["condition"]["var"]; all other
    # sites now prefer this stored value, falling back to the old substring
    # derivation only for rows logged before this column existed. No
    # backfill -- pre-migration rows can't be recovered, same reasoning as
    # the v34->v35 ensemble_member_scores.var migration.
    "ALTER TABLE predictions ADD COLUMN var TEXT",
    # v53 -> v56: log-only calibration/covariate columns (backlog.txt "RICHER
    # ML CALIBRATION FEATURES" + "FORECAST-CONDITION COVARIATES FOR SIGMA").
    # All three are already computed at trade time (weather_markets.py's
    # analyze_trade result dict / forecast dict) and were being discarded
    # before this -- threading them through here only starts the
    # accumulation clock; ml_bias.py's feature vector and get_historical_sigma
    # are NOT changed by this migration, retraining/covariate use is a
    # separate future step once enough rows exist. No backfill -- pre-
    # migration rows can't be recovered, same reasoning as every other
    # column added this way in this list.
    "ALTER TABLE predictions ADD COLUMN ensemble_spread_f REAL",
    "ALTER TABLE predictions ADD COLUMN model_disagreement_f REAL",
    "ALTER TABLE predictions ADD COLUMN precip_sum_in REAL",
    # v56 -> v57: log-only NBM-native quantile probability (backlog.txt "NBM
    # PROBABILISTIC QUANTILES"). Computed by analyze_trade() via the new
    # mos.fetch_nbm_quantiles() + nws.nws_prob_from_quantiles() pair but NOT
    # blended into forecast_prob/our_prob or any live sizing decision --
    # ship log-only first, verify correlation with settlement before ever
    # wiring it in. No backfill, same reasoning as every other column added
    # this way in this list.
    "ALTER TABLE predictions ADD COLUMN nbm_quantile_prob REAL",
    # v57 -> v58: log-only max pairwise gap between ecmwf_aifs025_ensemble's
    # member-vote probability and icon/gfs's (backlog.txt "3-WAY
    # MODEL_CONSENSUS CHECK"). Computed by analyze_trade() but NOT folded
    # into model_consensus -- zero settled ecmwf_aifs025_ensemble
    # observations exist yet to pick a defensible 3-way threshold, so ship
    # log-only first and let this start the accumulation clock. No backfill,
    # same reasoning as every other column added this way in this list.
    "ALTER TABLE predictions ADD COLUMN ecmwf_consensus_gap_prob REAL",
    # v58 -> v59: generic log-only signal storage (backlog.txt "SIGNAL
    # GRADUATION IS A CONVENTION, NOT A MECHANISM"). Every prior log-only
    # signal (run_trend, ensemble_spread_f, model_disagreement_f,
    # precip_sum_in, nbm_quantile_prob, ecmwf_consensus_gap_prob above) cost
    # its own named migration + log_prediction() kwarg + 4 SQL edits --
    # per the entry, "its marginal cost is currently ~6 touch points per
    # signal" and "the signature grows one kwarg per signal, forever".
    # signal_values is a single JSON dict column (mirrors the
    # blend_sources/run_trend_points JSON-column precedent already
    # established above) that a FUTURE new log-only signal can use instead:
    # zero new migration, zero new log_prediction parameter, zero new
    # order_executor.py wiring -- _prediction_kwargs_from_analysis already
    # reads a.get("signals") unconditionally. Storage-only, deliberately
    # scoped down from the entry's full (a)+(b)+(c) proposal: no signal
    # registry, no auto-population from analyze_trade() (there is no
    # `signals` dict there yet -- a first consumer must create it, add it to
    # analyze_trade()'s result dict, AND read it back via json_extract() or
    # equivalent, since nothing queries this column yet either), no
    # graduation-report command, no auto-activation-notification reuse, and
    # the existing named columns are NOT retrofitted onto this (would need a
    # backfill/consumer-migration pass for each, out of scope here). No
    # backfill for this column itself, same reasoning as every other column
    # added this way.
    "ALTER TABLE predictions ADD COLUMN signal_values TEXT",
    # Per-model implied probability + Brier score for ensemble_member_scores,
    # feeding the quarantine mechanism's planned MAE->Brier swap.
    "ALTER TABLE ensemble_member_scores ADD COLUMN implied_prob REAL",
    "ALTER TABLE ensemble_member_scores ADD COLUMN brier REAL",
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


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """AUD-0048: every one of this module's 100+ `with _conn() as con:` call
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
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=10000")
    try:
        with con:
            yield con
    finally:
        con.close()


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
    liquidity_edge_scale: float | None = None,
    gated_edge: float | None = None,
    is_shadow: bool = False,
    is_probation: bool = False,
    ensemble_spread_f: float | None = None,
    model_disagreement_f: float | None = None,
    precip_sum_in: float | None = None,
    nbm_quantile_prob: float | None = None,
    ecmwf_consensus_gap_prob: float | None = None,
    signals: dict[str, float] | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Save a prediction to the database.
    Stores both the raw (pre-bias-correction) probability and the adjusted one (#53).
    #37: Optionally stores the NWP forecast cycle (00z/06z/12z/18z).
    #84: Optionally stores blend_sources dict (model weights) as JSON.
    P9.1: Optionally stores edge_calc_version for strategy version tracking.
    ensemble_spread_f/model_disagreement_f/precip_sum_in: optional scalars
    from weather_markets.analyze_trade()'s result dict / forecast dict
    (backlog.txt "RICHER ML CALIBRATION FEATURES" + "FORECAST-CONDITION
    COVARIATES FOR SIGMA"). Stored log-only; not consumed by ml_bias.py's
    training feature vector or get_historical_sigma yet -- this only starts
    the accumulation clock those entries require before retraining/covariate
    use can happen.
    nbm_quantile_prob: optional scalar from analyze_trade()'s NBM-native
    quantile probability (backlog.txt "NBM PROBABILISTIC QUANTILES"), via
    mos.fetch_nbm_quantiles() + nws.nws_prob_from_quantiles(). Stored
    log-only; never blended into forecast_prob/our_prob or any sizing
    decision.
    ecmwf_consensus_gap_prob: optional scalar from analyze_trade()'s max
    pairwise gap between ecmwf_aifs025_ensemble's probability and icon/gfs's
    (backlog.txt "3-WAY MODEL_CONSENSUS CHECK"). Stored log-only; does not
    feed model_consensus (still icon-vs-gfs only) until enough settled
    ecmwf_aifs025_ensemble observations exist to pick a defensible threshold.
    signals: optional generic dict of {name: value} for any FUTURE log-only
    signal (backlog.txt "SIGNAL GRADUATION IS A CONVENTION, NOT A
    MECHANISM"), stored as JSON in a single column. This is the graduation
    path going forward -- a new signal adds a key here instead of its own
    migration/kwarg/SQL-edit set. The existing named scalars above
    (ensemble_spread_f, nbm_quantile_prob, etc.) predate this mechanism and
    are NOT retrofitted onto it.
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
    liquidity_edge_scale/gated_edge: optional scalars from
    weather_markets._liquidity_edge_scale() (backlog.txt "LIQUIDITY-AWARE
    SIZING + DYNAMIC EDGE THRESHOLD"). Stored log-only; NEVER used for
    STRONG/MED/MIN signal classification anywhere in this codebase.
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
    is_probation: True for a prediction generated by
    check_retirement_probation() -- a retired method's forecast, computed via
    analyze_trade(bypass_retirement_check=True) purely to measure whether it
    has genuinely recovered. Like is_shadow, Brier/calibration queries do NOT
    filter it out (a probation prediction is a real forecast); a dedicated
    is_probation=1 filter is used only by brier_score_probation_rolling() for
    the auto-unretirement decision itself. The UPSERT MIN()s this the same way
    as is_shadow, for the same reason (a later real write always clears it).
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
    # Prefer analysis["days_out"] (analyze_trade's own value, computed
    # against the market's CITY-LOCAL today per backlog.txt "ANALYZE_TRADE'S
    # past_date GATE...") over recomputing here from UTC -- recomputing would
    # silently disagree with the value analyze_trade itself used for this
    # same trade during the ~4-8h evening window each day where UTC's date
    # has already rolled over but the city's hasn't, polluting the
    # calibration/analytics buckets this data feeds with two different
    # answers for the same trade. Falls back to the old UTC-based clamp only
    # when the caller doesn't supply analysis["days_out"] (e.g. a shadow/
    # lookup write built from a bare market dict rather than a real
    # analyze_trade() result).
    _analysis_days_out = analysis.get("days_out")
    if _analysis_days_out is not None:
        days_out = _analysis_days_out
    elif market_date is not None:
        # max(0, ...) matches the clamp already used at weather_markets.py's
        # days_out call sites: from 00:00 UTC until local midnight (a same-day
        # evening window for US cities), _utc_today() is already local-tomorrow,
        # which would otherwise store days_out=-1 and drop the row from both the
        # same-day and multiday analytics buckets.
        days_out = max(0, (market_date - _utc_today()).days)
    else:
        days_out = None
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
    liquidity_edge_scale = (
        round(liquidity_edge_scale, 4) if liquidity_edge_scale is not None else None
    )
    gated_edge = round(gated_edge, 6) if gated_edge is not None else None
    signal_values_json = _json.dumps(signals) if signals is not None else None

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
           implied_mean, implied_sigma, fit_residual,
           liquidity_edge_scale, gated_edge, is_probation, var,
           ensemble_spread_f, model_disagreement_f, precip_sum_in,
           nbm_quantile_prob, ecmwf_consensus_gap_prob, signal_values)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            liquidity_edge_scale = excluded.liquidity_edge_scale,
            gated_edge       = excluded.gated_edge,
            -- MIN(): a real-trade write (is_shadow=0) still clears the flag, but
            -- a shadow/lookup write (is_shadow=1, e.g. cmd_market) can never
            -- un-flag an already trade-backed row for the same (ticker, date).
            is_shadow        = MIN(predictions.is_shadow, excluded.is_shadow),
            -- Same MIN() reasoning as is_shadow: a later real write always
            -- clears is_probation, but a probation write can never re-flag a
            -- row that already has a real (or shadow) prediction on it.
            is_probation     = MIN(predictions.is_probation, excluded.is_probation),
            -- Plain overwrite (no MIN()/coalesce): a same-day re-analysis of
            -- the same ticker must update var if it changed, not silently
            -- keep the first-ever value forever (backlog.txt "HOURLY-
            -- DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item 2).
            var              = excluded.var,
            ensemble_spread_f    = excluded.ensemble_spread_f,
            model_disagreement_f = excluded.model_disagreement_f,
            precip_sum_in         = excluded.precip_sum_in,
            nbm_quantile_prob     = excluded.nbm_quantile_prob,
            ecmwf_consensus_gap_prob = excluded.ecmwf_consensus_gap_prob,
            signal_values         = excluded.signal_values
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
        liquidity_edge_scale,
        gated_edge,
        int(is_probation),
        cond.get("var"),
        ensemble_spread_f,
        model_disagreement_f,
        precip_sum_in,
        nbm_quantile_prob,
        ecmwf_consensus_gap_prob,
        signal_values_json,
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


def mark_outcome_undisputed(ticker: str) -> None:
    """Clear a ticker's disputed flag (opus-review-caught, 2026-08-10):
    mark_outcome_disputed() is this repo's only writer of disputed=1, and
    audit_settlement()'s daily-branch mismatch check is its only caller --
    every disputed row in production was set by comparing the OLD ASOS-proxy
    temperature against Kalshi's real YES/NO result, a comparison now known
    to legitimately disagree with Kalshi's real CLI-report settlement by
    ~1 degree near a threshold. Once the daily branch reads Kalshi's own
    settled figure directly, a ticker that no longer mismatches was flagged
    for a reason that's since been proven unreliable and should not stay
    permanently excluded from Brier/calibration scoring (outcomes_valid has
    no other path back to inclusion -- there was no un-dispute function
    before this one)."""
    init_db()
    try:
        with _conn() as con:
            con.execute("UPDATE outcomes SET disputed = 0 WHERE ticker = ?", (ticker,))
    except Exception as exc:
        _log.debug("mark_outcome_undisputed: failed for %s: %s", ticker, exc)


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


def log_trades(ticker: str, trades: list[dict]) -> int:
    """Bulk-insert public trade-flow history for a market. Idempotent --
    re-running for the same trade_id is a no-op (Kalshi's trade_id is
    globally unique, so it's the dedup key -- see trade_history's UNIQUE
    constraint). Returns the number of newly-inserted rows.
    """
    if not trades:
        return 0
    init_db()
    rows = []
    for t in trades:
        trade_id = t.get("trade_id")
        if not trade_id:
            continue
        rows.append(
            (
                trade_id,
                ticker,
                _fp_count(t.get("count_fp")),
                _candle_dollars(t, "yes_price_dollars"),
                _candle_dollars(t, "no_price_dollars"),
                t.get("taker_outcome_side"),
                t.get("taker_book_side"),
                int(bool(t.get("is_block_trade"))),
                t.get("created_time"),
                datetime.now(UTC).isoformat(),
            )
        )
    if not rows:
        return 0
    with _conn() as con:
        cur = con.executemany(
            """
            INSERT OR IGNORE INTO trade_history
            (trade_id, ticker, count, yes_price, no_price,
             taker_outcome_side, taker_book_side, is_block_trade,
             created_time, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def get_trade_history(ticker: str) -> list[sqlite3.Row]:
    """Return all logged public trades for a ticker, oldest first."""
    init_db()
    with _conn() as con:
        return con.execute(
            "SELECT * FROM trade_history WHERE ticker = ? ORDER BY created_time",
            (ticker,),
        ).fetchall()


def get_trade_flow_settlement_correlation(
    min_trades_per_market: int = 10,
    min_candles_per_market: int = 4,
    min_markets: int = 15,
    min_early_trades: int = 3,
) -> dict[str, int | float | None]:
    """Correlation-check for the PUBLIC TRADE-FLOW SIGNAL backlog entry's
    "did informed flow precede settlement-direction moves" caution-flag
    hypothesis -- log-only research, not wired into trading. Reports a raw
    Pearson r with no significance test attached (n is typically small,
    e.g. n=42, r=-0.035 as of 2026-08-03; n=92, r=0.036 as of 2026-08-22) --
    read it as directional, not conclusive.

    For each ticker with both trade_history and price_history rows, splits
    the trade series at its own time midpoint (half the trades happened
    before this point) and computes:
      - early signed flow: (yes-taker volume - no-taker volume) / total
        volume in the early half, in [-1, 1] -- requires at least
        min_early_trades contributing trades, not just nonzero volume, so a
        single trade at a timestamp tie can't swing it to +-1.0
      - late price drift: the last logged candle with a real price_close
        (24% of price_history rows have a NULL close -- no trades printed
        in that period -- so this walks backward past any NULL tail rather
        than trusting candles[-1] blindly) minus the earliest candle at/
        after the trade-series midpoint that also has a real close (walks
        forward past any NULL-close candles at that boundary rather than
        taking the first candle regardless of whether it has a price) --
        both ends aligned to one actual clock via epoch-timestamp
        comparison, not independently split per series. If either search
        can't find a real price, the market is skipped rather than falling
        back to an index-based split, which could measure a window
        entirely before the early-flow window and invert the very lead-lag
        relationship this function exists to test.
    then Pearson-correlates early flow against late drift across markets
    (same manual formula as get_recent_city_correlations -- not because
    scipy is unavailable elsewhere in this project, but to match that
    function's own established convention). Candles are filtered to the
    earliest candle's own period_interval first (no ticker has logged more
    than one resolution as of 2026-08-03, but mixing OHLC resolutions in
    one ordered series would silently corrupt the walk if that ever
    changes).

    Returns {"n": int, "r": float | None, "markets_considered": int,
    "markets_skipped_thin": int, "markets_skipped_no_price": int} -- r is
    None below min_markets or when either series has zero variance.
    "markets_skipped_thin" covers below-floor trade/candle counts and
    below-floor early-half volume; "markets_skipped_no_price" covers a
    ticker that cleared those floors but has no usable (non-NULL) price at
    one or both ends of the drift window.
    """
    init_db()
    with _conn() as con:
        tickers = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT t.ticker FROM trade_history t "
                "JOIN price_history p ON p.ticker = t.ticker"
            ).fetchall()
        ]

    flows: list[float] = []
    drifts: list[float] = []
    skipped_thin = 0
    skipped_no_price = 0
    for ticker in tickers:
        trades = get_trade_history(ticker)
        candles = get_price_history(ticker)
        if len(trades) < min_trades_per_market or len(candles) < min_candles_per_market:
            skipped_thin += 1
            continue

        # Keep only the earliest candle's own resolution -- not a majority
        # vote, just enough to guarantee one ticker's series is never a
        # silent interleave of two OHLC granularities.
        first_interval = candles[0]["period_interval"]
        candles = [c for c in candles if c["period_interval"] == first_interval]
        if len(candles) < min_candles_per_market:
            skipped_thin += 1
            continue

        trade_epochs: dict[int, float] = {}
        for i, t in enumerate(trades):
            ct = t["created_time"]
            if not ct:
                continue
            try:
                trade_epochs[i] = datetime.fromisoformat(
                    ct.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, AttributeError, TypeError):
                continue
        if len(trade_epochs) < min_trades_per_market:
            skipped_thin += 1
            continue
        mid_epoch = sorted(trade_epochs.values())[len(trade_epochs) // 2]

        early_yes = 0.0
        early_no = 0.0
        early_trade_count = 0
        for i, t in enumerate(trades):
            epoch = trade_epochs.get(i)
            count = t["count"]
            if epoch is None or count is None or epoch >= mid_epoch:
                continue
            side = t["taker_outcome_side"]
            if side == "yes":
                early_yes += count
                early_trade_count += 1
            elif side == "no":
                early_no += count
                early_trade_count += 1
        early_total = early_yes + early_no
        if early_total <= 0 or early_trade_count < min_early_trades:
            skipped_thin += 1
            continue
        early_flow = (early_yes - early_no) / early_total

        mid_candle_price = None
        for c in candles:
            if c["end_period_ts"] >= mid_epoch and c["price_close"] is not None:
                mid_candle_price = c["price_close"]
                break
        last_price = None
        for c in reversed(candles):
            if c["price_close"] is not None:
                last_price = c["price_close"]
                break
        if mid_candle_price is None or last_price is None:
            skipped_no_price += 1
            continue
        late_drift = last_price - mid_candle_price

        flows.append(early_flow)
        drifts.append(late_drift)

    n = len(flows)
    result: dict[str, int | float | None] = {
        "n": n,
        "r": None,
        "markets_considered": len(tickers),
        "markets_skipped_thin": skipped_thin,
        "markets_skipped_no_price": skipped_no_price,
    }
    if n < min_markets:
        return result

    mx = sum(flows) / n
    my = sum(drifts) / n
    num = sum((a - mx) * (b - my) for a, b in zip(flows, drifts))
    d1 = math.sqrt(sum((a - mx) ** 2 for a in flows))
    d2 = math.sqrt(sum((b - my) ** 2 for b in drifts))
    if d1 > 0 and d2 > 0:
        result["r"] = round(num / (d1 * d2), 3)
    return result


def get_price_convergence_by_market_age(
    min_candles_per_market: int = 8,
    min_candles_per_half: int = 2,
    min_markets: int = 15,
) -> dict[str, int | float | None]:
    """Precursor check for the MARKET_LIFECYCLE_V2 WS CHANNEL backlog entry's
    own "cheap precursor available now with zero new infra" instruction: use
    existing candle history to check whether early-captured prices sit
    further from eventual settlement than later-captured prices.

    IMPORTANT (added after independent review found the original framing
    overclaimed): this statistic CANNOT distinguish real exploitable
    mispricing from ordinary price-uncertainty resolution in a perfectly
    efficient market. For ANY process whose price converges to a known
    terminal value (efficient or not), E[|price_t - settlement|] is
    monotonically decreasing as t approaches settlement, purely because
    "late" is closer in time to the point being measured against -- a
    zero-edge market produces the same qualitative shape this function
    reports. A martingale simulation (driftless, no informational edge,
    same 39-hourly-step/binary-settlement shape as the real data)
    reproduces fraction_early_greater=0.904 almost exactly at moderate
    information-arrival rates. So a positive result here is NOT evidence
    that early entry captures real edge, and does NOT by itself support or
    refute the market_lifecycle_v2 candidate -- it only confirms markets
    resolve uncertainty over time, which was never in doubt. A real test of
    "does exploitable edge decay with market age" needs to compare market
    price against an independent fair-value estimate (e.g. this bot's own
    `predictions.our_prob`) at varying market ages, not against the
    market's own eventual settlement -- that comparison is NOT implemented
    here and is the actual next step if this candidate is revisited.

    Time zero is each market's own first CAPTURED candle, not open_time
    (which is fetched live from the Kalshi API only at backfill time and
    never persisted to price_history). In practice this is usually a close
    proxy for true listing time, not a weak one: sync_outcomes's
    candlestick backfill fetches the FULL [open_time, close_time] range at
    settlement time regardless of when the capture code itself shipped, so
    the first captured candle for a settled market is typically close to
    real market open (confirmed empirically 2026-08-22: 239/326 tickers in
    the live DB have a first candle before the capture code's own
    2026-07-12 ship date, and 311/326 land at exactly 15:00 UTC, a listing-
    time artifact). Retained as "captured window" language regardless,
    since it's not a documented guarantee for every market.

    For each ticker with price_history rows: finds settlement price as the
    last candle with a real (non-NULL) price_close, walking backward past
    any NULL tail (24% of rows have a NULL close -- same convention as
    get_trade_flow_settlement_correlation above). This settlement candle is
    itself a member of the "late" half below whenever the late half has any
    real-priced candles, contributing a guaranteed |settlement-settlement|
    = 0 -- an expected consequence of using each market's own last real
    price as its own fair-value proxy, not a bug, but it mechanically
    deflates mean_late_mispricing (and thus inflates mean_diff and
    fraction_early_greater) versus a design that measured against an
    external reference instead. Candles are filtered to the earliest
    candle's own period_interval first, same interleave guard as that
    function. Splits the (already end_period_ts-ordered) candle series at
    its own median-position candle's timestamp into an early half and late
    half, then computes mean |price_close - settlement_price| (distance
    from each market's own eventual close) for each half using only
    candles with a real close -- requires at least min_candles_per_half
    real-priced candles on each side, defaulting to 2 so neither half's
    average is normally reported from a single candle. The internal check
    is separately floored at a minimum of 1 regardless of the caller-
    supplied value (a floor of 0 would let the code below divide by zero,
    not report a single-candle average) -- a caller who explicitly passes
    0 or 1 DOES get a single-candle average, same as passing 1 directly.

    Reports the per-market paired difference (early - late) across markets
    -- not a two-variable correlation like the trade-flow function above,
    since this measures the SAME quantity at two points in one market's
    life, not two different variables.

    markets_skipped_thin counts tickers below min_candles_per_market,
    checked both before and after the period_interval filter -- the
    pre-filter check is, like the settlement-price-None check below,
    structurally redundant with its post-filter sibling (filtering can only
    shrink the candle list, so anything failing the pre-filter check also
    fails the post-filter one); kept for the same early-exit-clarity reason,
    not because a test can independently isolate it. markets_skipped_no_price
    counts
    tickers that cleared that floor but have no usable price: either no
    real close anywhere (settlement walk-back fails) or too few real-priced
    candles in one half. The first of those two is, given
    min_candles_per_half enforced >=1, always ALSO caught by the second --
    a non-None settlement_price requires at least one real close among
    `candles`, so if early_prices or late_prices clears the floor, a real
    close necessarily exists and settlement_price cannot be None. It is
    kept as an explicit, separately-checked branch for early-exit clarity
    and to guard the arithmetic below against a None subtraction, not
    because it fires independently of the half-floor check at any floor
    >=1.

    Returns {"n": int, "mean_early_mispricing": float | None,
    "mean_late_mispricing": float | None, "mean_diff": float | None,
    "fraction_early_greater": float | None, "markets_considered": int,
    "markets_skipped_thin": int, "markets_skipped_no_price": int} -- the
    float fields are None below min_markets. No significance test is
    attached, and per the IMPORTANT note above, the sign/direction of this
    result carries no information about real edge either way -- unlike the
    sibling trade-flow function's r (a genuine, merely underpowered,
    two-variable relationship), do NOT read a positive result here as even
    weak directional support.
    """
    init_db()
    with _conn() as con:
        tickers = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT ticker FROM price_history"
            ).fetchall()
        ]

    early_vals: list[float] = []
    late_vals: list[float] = []
    skipped_thin = 0
    skipped_no_price = 0
    for ticker in tickers:
        candles = get_price_history(ticker)
        if len(candles) < min_candles_per_market:
            skipped_thin += 1
            continue

        # Same interleave guard as get_trade_flow_settlement_correlation: no
        # ticker has logged more than one resolution as of 2026-08-22, but
        # mixing OHLC resolutions in one ordered series would silently
        # corrupt the early/late split if that ever changes.
        first_interval = candles[0]["period_interval"]
        candles = [c for c in candles if c["period_interval"] == first_interval]
        if len(candles) < min_candles_per_market:
            skipped_thin += 1
            continue

        settlement_price = None
        for c in reversed(candles):
            if c["price_close"] is not None:
                settlement_price = c["price_close"]
                break
        if settlement_price is None:
            skipped_no_price += 1
            continue

        mid_epoch = candles[len(candles) // 2]["end_period_ts"]
        early_prices = [
            c["price_close"]
            for c in candles
            if c["end_period_ts"] < mid_epoch and c["price_close"] is not None
        ]
        late_prices = [
            c["price_close"]
            for c in candles
            if c["end_period_ts"] >= mid_epoch and c["price_close"] is not None
        ]
        # Floored at 1 regardless of the caller-supplied min_candles_per_half
        # -- a mean computed from zero candles would raise ZeroDivisionError
        # below rather than falling through to a clean skip.
        half_floor = max(min_candles_per_half, 1)
        if len(early_prices) < half_floor or len(late_prices) < half_floor:
            skipped_no_price += 1
            continue

        early_vals.append(
            sum(abs(p - settlement_price) for p in early_prices) / len(early_prices)
        )
        late_vals.append(
            sum(abs(p - settlement_price) for p in late_prices) / len(late_prices)
        )

    n = len(early_vals)
    result: dict[str, int | float | None] = {
        "n": n,
        "mean_early_mispricing": None,
        "mean_late_mispricing": None,
        "mean_diff": None,
        "fraction_early_greater": None,
        "markets_considered": len(tickers),
        "markets_skipped_thin": skipped_thin,
        "markets_skipped_no_price": skipped_no_price,
    }
    # Floored at 1 for the same reason as half_floor above -- min_markets=0
    # would otherwise let n=0 through to a division by n below.
    if n < max(min_markets, 1):
        return result

    diffs = [e - late for e, late in zip(early_vals, late_vals)]
    result["mean_early_mispricing"] = round(sum(early_vals) / n, 3)
    result["mean_late_mispricing"] = round(sum(late_vals) / n, 3)
    result["mean_diff"] = round(sum(diffs) / n, 3)
    result["fraction_early_greater"] = round(sum(1 for d in diffs if d > 0) / n, 3)
    return result


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

    Excludes the same _excluded_brier_condition_types() population as
    brier_score() (backlog.txt "SEVERAL BRIER-FAMILY FUNCTIONS STILL HAVE NO
    CONDITION_TYPE FILTER" -- previously unfiltered).
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _excluded_brier_condition_types()
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT p.method, p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.method IS NOT NULL
              AND {cond_clause}
            """,
            cond_params,
        ).fetchall()

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

    Excludes the same _excluded_brier_condition_types() population as
    brier_score() (backlog.txt "SEVERAL BRIER-FAMILY FUNCTIONS STILL HAVE NO
    CONDITION_TYPE FILTER" -- previously unfiltered).
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _excluded_brier_condition_types()
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT p.method, p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.method IS NOT NULL
              AND {cond_clause}
            ORDER BY o.settled_at DESC
            """,
            cond_params,
        ).fetchall()

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


def brier_by_condition_type_rolling(
    method: str = "ensemble", window: int = 20, min_samples: int = 8
) -> dict[str, dict]:
    """Rolling Brier score AND directional accuracy per condition_type, for
    one method's settled multi-day predictions.

    Windowed PER condition_type (not a shared last-N-overall window then
    split), since condition types settle at very different rates -- 'below'
    markets are far rarer than 'above'/'between' for this bot's real trade
    mix, so a shared window would leave 'below' chronically under-
    represented. Surfaces the exact asymmetry a manual per-condition-type
    breakdown found by hand (2026-08-12 investigation): a method's overall
    Brier/win-rate can look merely mediocre while one condition_type is
    actually dragging it down and running worse than a coin flip, invisible
    to brier_score_by_method[_rolling]'s method-only grouping.

    Returns {condition_type: {"n": int, "brier": float,
    "directional_accuracy": float}} for condition types with at least
    min_samples settled predictions in their own trailing window. Excludes
    disputed outcomes via outcomes_valid, matching every other Brier query.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.condition_type, p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.method = ? AND p.our_prob IS NOT NULL
              AND p.condition_type IS NOT NULL
            ORDER BY o.settled_at DESC
            """,
            (method,),
        ).fetchall()

    by_type_recent: dict[str, list[tuple[float, int]]] = {}
    for r in rows:
        bucket = by_type_recent.setdefault(r["condition_type"], [])
        if len(bucket) < window:
            bucket.append((r["our_prob"], r["settled_yes"]))

    result: dict[str, dict] = {}
    for cond_type, pairs in by_type_recent.items():
        n = len(pairs)
        if n < min_samples:
            continue
        brier = sum((p - y) ** 2 for p, y in pairs) / n
        correct = sum(1 for p, y in pairs if (p > 0.5) == (y == 1))
        result[cond_type] = {
            "n": n,
            "brier": round(brier, 4),
            "directional_accuracy": round(correct / n, 4),
        }
    return result


def check_condition_type_weakness(
    window: int = 20, min_samples: int = 8, directional_floor: float = 0.40
) -> list[str]:
    """Warn (never halt) when a (method, condition_type) pair's rolling
    directional accuracy drops below directional_floor.

    Complements the WIN_RATE_COLLAPSE anomaly (alerts.py, whole multi-day
    pool) and brier_score_by_method[_rolling] (per-method only): neither
    would have surfaced the 'below'-market-specific weakness found by hand
    2026-08-12, since 'above'/'between' were healthy enough to keep the
    method-level aggregate merely mediocre rather than clearly broken.
    Intentionally warn-only -- unlike WIN_RATE_COLLAPSE this has no halt
    threshold wired in ALERT_HALT_THRESHOLDS, since a single condition_type
    slice is a smaller, noisier sample than the pools that gate live
    trading today; it exists to surface the split for a human to check, not
    to auto-halt on it.
    """
    init_db()
    with _conn() as con:
        methods = [
            r["method"]
            for r in con.execute(
                "SELECT DISTINCT method FROM multiday_predictions "
                "WHERE method IS NOT NULL"
            ).fetchall()
        ]

    alerts_out: list[str] = []
    for method in methods:
        breakdown = brier_by_condition_type_rolling(
            method, window=window, min_samples=min_samples
        )
        for cond_type, stats in breakdown.items():
            if stats["directional_accuracy"] < directional_floor:
                alerts_out.append(
                    f"CONDITION-TYPE WEAKNESS: method={method} "
                    f"condition_type={cond_type} "
                    f"directional_accuracy={stats['directional_accuracy']:.0%} "
                    f"(n={stats['n']}, floor={directional_floor:.0%}) "
                    f"brier={stats['brier']:.4f}"
                )
    return alerts_out


def check_sameday_condition_type_weakness(
    min_samples: int = 5, bias_floor: float = 0.15
) -> list[str]:
    """Warn (never halt) when a same-day (days_out=0) condition_type's
    predicted-vs-actual bias exceeds bias_floor -- batch-40 "Between-bracket
    calibration design", Decision 1's alert half.

    check_condition_type_weakness() above is this function's multi-day
    counterpart but cannot see same-day rows at all (it reads
    multiday_predictions, days_out>=1 by construction) -- and a between
    condition_type only ever produces a days_out=0 row (see
    weather_markets.is_between_bracket_ticker's docstring: a between
    condition is only ever scored via _metar_lock_in), so between weakness
    was structurally invisible to every existing alert before this. Reads
    get_sameday_calibration()'s new by_condition_type breakdown rather than
    a separate query, so this always alerts on exactly what the dashboard
    (/api/sameday-calibration) shows.

    Uses |bias| (mean_prob - mean_actual), not directional_accuracy, since
    that is what get_sameday_calibration()'s breakdown already computes and
    what the file's own skeptic-verified evidence is expressed in (between
    YES-locks: 89.6% predicted vs 70.4% actual, bias +0.192, n=27;
    NO-locks: 93.0% vs 50.0%, bias +0.430, n=6 -- both would already trip a
    0.15 floor). min_samples defaults lower than check_condition_type_weakness's
    8 (between's settled sample accrues far slower -- 1 shadow prediction
    total as of this batch landing -- so a higher floor would likely never
    fire in practice for a long time). Intentionally warn-only, same
    reasoning as check_condition_type_weakness: a single condition_type
    same-day slice is too small/noisy a sample to auto-halt on.

    Skips the "unspecified" bucket (NULL condition_type rows) -- unlike
    'between'/'above'/'below', it isn't a real, currently-tradeable market
    family an operator could act on; it's a data-hygiene artifact of rows
    logged before the condition_type column was reliably populated (found
    live: all 8 real unspecified rows in production predate 2026-06-25,
    long before this function shipped). Alerting on it would just be noise
    with no actionable fix.
    """
    breakdown = get_sameday_calibration().get("by_condition_type", {})
    alerts_out: list[str] = []
    for cond_type, stats in breakdown.items():
        if cond_type == "unspecified":
            continue
        if stats["n"] < min_samples:
            continue
        if abs(stats["bias"]) > bias_floor:
            alerts_out.append(
                f"SAMEDAY CONDITION-TYPE WEAKNESS: condition_type={cond_type} "
                f"bias={stats['bias']:+.3f} (predicted={stats['mean_prob']:.3f} "
                f"actual={stats['mean_actual']:.3f}, n={stats['n']}, "
                f"floor={bias_floor:.2f}) brier={stats['brier']:.4f}"
            )
    return alerts_out


def brier_score_probation_rolling(
    method: str, window: int = 20, min_samples: int = 15
) -> float | None:
    """Rolling Brier score over a retired method's PROBATION-only predictions
    (is_probation=1), used to decide auto-unretirement (backlog.txt "AUTO
    UN-RETIREMENT").

    Deliberately separate from brier_score_by_method_rolling(): that function
    mixes is_probation rows in with everything else (correct for the live
    retirement-decision path, since a probation row is a real forecast), but
    auto-unretirement needs a signal that is *exclusively* fresh, deliberately
    -generated post-retirement evidence -- otherwise a rolling window still
    mostly full of old pre-retirement rows would look "recovered" long before
    any genuine new evidence exists (the exact gap that motivated this
    feature). Excludes same-day trades (days_out=0) via multiday_predictions,
    matching every other method-level Brier query's convention.

    Returns None if fewer than min_samples probation predictions have settled.

    Excludes the same _excluded_brier_condition_types() population as
    brier_score() (backlog.txt "SEVERAL BRIER-FAMILY FUNCTIONS STILL HAVE NO
    CONDITION_TYPE FILTER" -- this function gates auto-unretirement of a
    retired method and was previously unfiltered).
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _excluded_brier_condition_types()
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.method = ? AND p.is_probation = 1 AND p.our_prob IS NOT NULL
              AND {cond_clause}
            ORDER BY o.settled_at DESC
            LIMIT ?
            """,
            (method, *cond_params, window),
        ).fetchall()

    if len(rows) < min_samples:
        return None
    errs = [(r["our_prob"] - r["settled_yes"]) ** 2 for r in rows]
    return sum(errs) / len(errs)


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


# Every function below that scores/counts settled multi-day predictions for a
# calibration or live-trading-readiness purpose excludes this same 6-type
# condition_type set (backlog.txt "BRIER-FAMILY CONDITION_TYPE EXCLUSION LIST
# HAS NO COUPLING TO RAIN/SNOW/HURRICANE GRADUATION GATES" and "SEVERAL
# BRIER-FAMILY FUNCTIONS STILL HAVE NO CONDITION_TYPE FILTER") -- previously
# duplicated as a hardcoded tuple literal in 7 separate functions in this
# file alone (plus 5 more sites in calibration.py/ml_bias.py/main.py, out of
# this fix's scope -- those live in other files this change does not touch).
# Consolidated here as the single source of truth, matching this codebase's
# established convention for shared classification data (e.g.
# weather_markets._KXRAIN_MONTHLY_CITY).
_GATE_COUPLED_EXCLUDED_CONDITION_TYPES: tuple[tuple[str, str], ...] = (
    ("precip_month_total", "_rain_gates_active"),
    ("snow_month_total", "_snow_gates_active"),
    ("hurricane_count", "_hurricane_count_gates_active"),
    ("hurricane_next_event", "_hurricane_next_event_gates_active"),
    ("storm_order", "_storm_order_gates_active"),
)


# backlog.txt opus-review finding M5 (batch-06): NOT every consumer of the
# 6-type exclusion is a graduation/live-trading-readiness signal that should
# start counting a market family's rows the moment it goes live. Some are
# fitting a temperature-SCALE-specific calibration curve or circuit-breaker
# window that stays structurally invalid for a non-temperature type
# regardless of shadow/live status -- exactly the same reasoning that already
# keeps 'between' permanently excluded from every consumer (structural
# calibration-gap mismatch, not shadow-status). Use this constant, not
# _excluded_brier_condition_types(), for any consumer whose OWN docstring
# gives a scale/distribution-shape/not-yet-validated reason rather than a
# shadow-only-market-family reason.
_ALWAYS_EXCLUDED_CONDITION_TYPES: frozenset[str] = frozenset(
    {"between"} | {ct for ct, _ in _GATE_COUPLED_EXCLUDED_CONDITION_TYPES}
)


def _excluded_brier_condition_types() -> frozenset[str]:
    """Condition types to exclude from Brier/calibration-QUALITY-SIGNAL
    queries right now -- i.e. functions whose own docstring's reason for
    excluding a type is that market family being shadow-only (not yet
    receiving real capital), not a structural/scale mismatch. See
    _ALWAYS_EXCLUDED_CONDITION_TYPES's docstring for the distinction and
    which consumers use which.

    Dynamically coupled to each shadow-only market family's own live-trading
    gate (weather_markets._rain_gates_active() etc.): a condition_type is
    excluded only while its family's gate is still inactive (env flag unset
    or sample floor not yet cleared). The moment a family actually goes live,
    its settled rows start counting toward every calibration/gate value this
    exclusion feeds -- closing the gap where a market family receiving real
    capital could be permanently excluded from the Brier value that gates ALL
    live trading, with nothing to notice or adjust (backlog.txt finding this
    generalizes from). Fails closed: if a gate's own state (or even
    weather_markets itself) can't be determined/imported, every gate-backed
    condition_type stays excluded, and a warning is logged so a rename/typo
    that silently kills the coupling (opus-review finding L1) doesn't go
    unnoticed the way count_settled_snow_predictions()'s own pre-fix
    silent-freeze bug once did.

    'between' is NOT gate-coupled and is always excluded unconditionally --
    unlike the 5 types above, this exclusion isn't about shadow status. It's
    excluded because it has a genuinely different, structurally larger
    calibration gap than above/below (T~=6.8 temperature-scaling factor vs.
    global/above/below's much smaller correction -- see backlog.txt's EMOS
    confirm-gate opus-review finding #4) that would distort a shared
    aggregate Brier score meant to represent overall model quality. This
    exclusion is permanent by design, not a graduation-pending status --
    even once weather_markets._between_metar_gates_active() (added batch-40
    "Between-bracket calibration design") lets between trade with real
    capital again, its rows must NOT be added back into this shared-
    aggregate exclusion set, since the scale-mismatch reason above is
    independent of trading status. That gate function answers a different
    question than this one (may a between trade use real capital right
    now?, not does a between row belong in the shared aggregate?) and must
    stay uncoupled from _GATE_COUPLED_EXCLUDED_CONDITION_TYPES for that
    reason -- see _between_metar_gates_active()'s own docstring.

    Deliberate no-fix decisions from opus review (documented per-finding,
    not silently dropped):
    L5 (no memoization -- up to 5 gate-check queries + connections per call,
    x12 call sites): not cached, since a gate's live state can change
    mid-process and this feeds a live-trading safety value -- staleness
    risk outweighs the query cost, which is small relative to this
    codebase's cron/dashboard call cadence (not a per-trade hot path).
    L6 (paper.graduation_check() calls count_settled_predictions() then
    brier_score() separately, each recomputing this set -- a gate flip
    between the two calls could theoretically make count and score
    disagree): accepted as a benign, exceedingly narrow race (a gate flip
    requires both an env var change AND crossing a 20-row sample floor,
    not something that happens between two sequential function calls in
    practice); threading one shared snapshot through both calls would
    require editing paper.py, which is out of this batch's file scope
    (paper.py is owned by batch-04, "Concurrency / locking").
    """
    excluded = {"between"}
    try:
        import weather_markets as _wm
    except Exception as exc:
        _log.warning(
            "_excluded_brier_condition_types: weather_markets import failed "
            "(%s) -- failing closed, excluding all gate-backed types",
            exc,
        )
        return _ALWAYS_EXCLUDED_CONDITION_TYPES

    for condition_type, gate_fn_name in _GATE_COUPLED_EXCLUDED_CONDITION_TYPES:
        try:
            gate_fn = getattr(_wm, gate_fn_name)
            if not gate_fn():
                excluded.add(condition_type)
        except Exception as exc:
            _log.warning(
                "_excluded_brier_condition_types: gate check %s failed (%s) "
                "-- failing closed, excluding %s",
                gate_fn_name,
                exc,
                condition_type,
            )
            excluded.add(condition_type)
    return frozenset(excluded)


def _condition_type_not_in_sql(excluded: frozenset[str]) -> tuple[str, list[str]]:
    """Build the "(p.condition_type IS NULL OR p.condition_type NOT IN (...))"
    clause fragment plus its params list, sized to `excluded`'s current
    length -- exclusion count varies at runtime now that it's gate-coupled,
    so this can't be a fixed-arity literal the way the old hardcoded tuple
    was. Params are sorted for deterministic query text/logs across process
    restarts (a plain frozenset's iteration order depends on PYTHONHASHSEED)
    -- opus-review finding L3.

    Requires a non-empty `excluded` -- `NOT IN ()` (zero elements) is a
    SQLite-specific extension most other engines reject, and nothing else
    in this codebase should ever assume it works (opus-review finding L4).
    Not reachable via either real caller today ('between' is always present
    in both _excluded_brier_condition_types() and
    _ALWAYS_EXCLUDED_CONDITION_TYPES), but asserted explicitly rather than
    silently relying on that invariant holding forever."""
    assert excluded, "condition_type exclusion set must never be empty"
    params = sorted(excluded)
    placeholders = ", ".join("?" * len(params))
    clause = f"(p.condition_type IS NULL OR p.condition_type NOT IN ({placeholders}))"
    return clause, params


def _paper_trade_excluded_condition_type(ticker: str) -> str | None:
    """Classify a paper-trade ticker into one of the 6
    _excluded_brier_condition_types() buckets, or None if it isn't one of
    them. Paper trade records carry no condition_type column of their own --
    only ticker/var -- so this derives the same classification predictions
    rows get from log_prediction's analysis dict purely from the ticker
    string, reusing weather_markets.py's existing per-family ticker
    classifiers rather than inventing a new parsing scheme (backlog.txt
    "BRIER_SCORE()'S PAPER_TRADES.DB FALLBACK HAS NO CONDITION_TYPE
    FILTER"). Keep this in sync with _excluded_brier_condition_types()'s
    6-type vocabulary if that set ever changes.

    'between' is identified by the ticker's own "-B<value>" strike suffix --
    the same regex weather_markets._parse_market_condition() uses to tell
    bucket markets from above/below directional ones. Unlike above/below
    (which need title text to disambiguate direction), 'between' is fully
    determined by the ticker alone, so no title/subtitle lookup is needed
    here -- convenient, since paper trade records don't carry the market
    title anyway. The B-suffix check runs LAST, after the snow/precip
    guard below -- _parse_market_condition() itself checks its snow/ice and
    precip branches (weather_markets.py's SNOW_SERIES/PRECIP_SERIES
    substring checks) BEFORE ever reaching its own T/B temperature regex, so
    a (currently-hypothetical) daily KXSNOW*/KXICE*/KXRAIN*/KXPRECIP*
    ticker ending in "-B<n>" must be excluded from the 'between' match here
    too, or it would be misclassified (opus-review finding L2) -- it isn't
    one of this function's 6 excluded types either way (precip_snow/
    precip_any/precip_above aren't excluded from Brier), so the correct
    result for it is None, not 'between'.

    Fails OPEN (returns None -- not excluded) whenever the ticker can't be
    matched to a known excluded pattern, INCLUDING when classification
    itself raises (weather_markets import failure, unexpected non-str
    input) -- deliberately the opposite posture from
    _excluded_brier_condition_types()'s fail-CLOSED exception handling
    (opus-review findings M2/M3): that function gates which market
    families count toward a live-trading safety value, so an unknown state
    defaults to the safer "stays excluded" outcome; this function's job is
    narrower (classify one already-included paper trade's ticker), and a
    genuinely unclassifiable/malformed ticker should default to "leave it
    in the population" -- the same missing-data convention this exact
    fallback already applies to a missing `days_out` field. Matches every
    sibling ticker classifier's own no-exception contract
    (is_hurricane_count_ticker etc.) from the caller's perspective, even
    though internally it now catches rather than never raising in the
    first place."""
    try:
        if not isinstance(ticker, str) or not ticker:
            return None
        import re

        from weather_markets import (
            _KXRAIN_MONTHLY_CITY,
            _KXSNOW_MONTHLY_CITY,
            is_hurricane_count_ticker,
            is_hurricane_next_event_ticker,
            is_storm_order_ticker,
        )

        ticker_upper = ticker.upper()
        if is_hurricane_count_ticker(ticker_upper):
            return "hurricane_count"
        if is_hurricane_next_event_ticker(ticker_upper):
            return "hurricane_next_event"
        if is_storm_order_ticker(ticker_upper):
            return "storm_order"
        if any(ticker_upper.startswith(p) for p in _KXRAIN_MONTHLY_CITY):
            return "precip_month_total"
        if any(ticker_upper.startswith(p) for p in _KXSNOW_MONTHLY_CITY):
            return "snow_month_total"
        # Mirrors weather_markets._parse_market_condition()'s own
        # SNOW_SERIES={"KXSNOW","KXICE"}/PRECIP_SERIES={"KXRAIN","KXSNOW",
        # "KXPRECIP"} substring checks, which run before that function's T/B
        # regex -- see docstring note above (opus-review finding L2).
        if any(s in ticker_upper for s in ("KXSNOW", "KXICE", "KXRAIN", "KXPRECIP")):
            return None
        if re.search(r"-B\d+(?:\.\d+)?$", ticker_upper):
            return "between"
        return None
    except Exception as exc:
        _log.warning(
            "_paper_trade_excluded_condition_type: classification failed for "
            "%r (%s) -- treating as not-excluded",
            ticker,
            exc,
        )
        return None


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

    Primary-source query excludes condition_type='between'/'precip_month_total'/
    'snow_month_total'/'hurricane_count'/'hurricane_next_event'/'storm_order' — the
    same exclusion list (exact-match, case-sensitive, no whitespace normalization —
    matches how every sibling query already does it, and how log_prediction always
    writes condition_type: lowercase, from a fixed set of literals in
    weather_markets.py, so this is a real constraint today, not just a documented
    assumption) count_settled_predictions() and calibration.py's grid search already
    use, added here 2026-08 (max-depth audit AUD-0004) after this function's lack of
    any condition_type filter was found to silently let shadow-only non-temperature
    predictions (routed in since 6845b62c/9a7583aa, 2026-08-06/07) contaminate the
    value graduation_check() gates ALL live trading on. The filter lives in the
    WHERE clause (applied before last_n's LIMIT), so last_n=50 now means the 50
    most recent TEMPERATURE-only settled predictions -- reaching further back in
    time than a naive "take the last 50 of any type, then filter" would, which is
    the statistically correct behavior for a sample-validity window (this
    function's own last_n docstring above: "lets old bad weeks age out").

    IMPACT ON TODAY'S GATE (verified independently twice, by two different opus
    reviewers, against real production data 2026-08-18): unfiltered last-50-of-
    any-type Brier = 0.2169 (<=0.23 -- PASSES graduation_check()'s criterion);
    true last-50-temperature-only Brier (this fix) = 0.2397 (>0.23 -- FAILS it).
    This fix DOES flip graduation_check()'s Brier sub-check from pass to fail on
    today's real data (sample guard is separately satisfied: count_settled_
    predictions()=83 >= MIN_BRIER_SAMPLES=30, so the Brier value is genuinely
    decisive, not skipped). An earlier version of this docstring claimed the
    opposite ("both land above the threshold, the fix does not flip the gate") --
    that was a transcription error, caught by review before commit; corrected here
    since this docstring is the permanent in-code record of the audit's single
    most consequential finding.

    UPDATE 2026-08-20 (backlog.txt "BRIER-FAMILY CONDITION_TYPE EXCLUSION LIST
    HAS NO COUPLING..." / "SEVERAL BRIER-FAMILY FUNCTIONS STILL HAVE NO
    CONDITION_TYPE FILTER" / "PAPER_TRADES.DB FALLBACK HAS NO CONDITION_TYPE
    FILTER" -- all three closed together): the exclusion list is no longer a
    static hardcoded tuple. count_settled_predictions_rolling,
    brier_score_rolling_with_n, get_brier_over_time,
    brier_score_by_method(_rolling), and brier_score_probation_rolling now
    reference _excluded_brier_condition_types() (dynamic, gate-coupled --
    see that function's own docstring), the same source this function uses.
    get_rolling_win_rate, get_metar_lockout_calibration_data,
    get_multiday_calibration_cli, and get_sameday_calibration_cli reference
    _ALWAYS_EXCLUDED_CONDITION_TYPES instead (opus-review finding M5,
    corrected during this same fix): their own docstrings give a
    structural/scale-mismatch reason for the exclusion, not a shadow-
    market-family one, so gate-coupling them would have been wrong, not
    just imprecise -- see _ALWAYS_EXCLUDED_CONDITION_TYPES's docstring for
    the distinction. The paper-trade fallback below is now filtered too,
    via _paper_trade_excluded_condition_type().

    NOT "every sibling" (opus-review finding M4, corrected here): this
    module still has unfiltered condition_type-adjacent functions this fix
    did not touch -- get_brier_by_days_out, get_brier_by_tier,
    brier_skill_score, get_brier_by_version, get_pnl_by_signal_source, and
    get_sameday_calibration() (the dashboard-facing sibling of
    get_sameday_calibration_cli, which deliberately differs from it by
    design -- see get_sameday_calibration_cli()'s own docstring). None of
    these were named by any of the 3 backlog entries this fix closes; see
    backlog.txt "MORE BRIER-FAMILY FUNCTIONS WITH NO CONDITION_TYPE FILTER,
    FOUND VIA ADJACENCY" for the follow-up. All 5 gate-backed types
    currently resolve to "still excluded" everywhere in this file (no
    RAIN/SNOW/HURRICANE*/STORM_ORDER_TRADING_ENABLED flag is set today), so
    the PRIMARY-SOURCE query's value is unchanged today -- purely closes
    the forward-looking gap there.

    Correction (opus-review finding I1): that "unchanged today" claim does
    NOT extend to the paper-trade fallback below. Unlike the 5 gate-backed
    types, 'between' is excluded from paper trades too and 'between'-bracket
    trading is live today -- so in the (currently rare, DB-state-dependent)
    case where the primary query returns 0 rows and the fallback is
    actually reached, this fix CAN change today's real return value: any
    'between' paper trades that would previously have counted in the
    fallback are now excluded, which can turn a real Brier number into
    None where the un-fixed code would have returned a contaminated value.
    Fail-safe direction (None makes graduation_check() decline to authorize
    rather than authorize on contaminated data), but it is a real value
    change on that specific path, not zero.

    Two non-test callers saw a value shift from the original 2026-08 filter
    (both audited, neither broken, unaffected by this update since the
    exclusion set is unchanged today): alerts.py's Black Swan Brier-collapse
    check (threshold 0.30) sees a HIGHER all-time value -- makes that halt
    strictly MORE likely to fire (fail-safe direction); main.py's
    backtest-drift warning (fires when recent_brier > all_time_brier + 0.05)
    compares against a higher all_time_brier too -- makes that warning LESS
    likely to fire, and backtest.py's train_brier side of that comparison has
    no condition_type concept of its own, so the comparison is asymmetrically
    filtered.
    """
    init_db()
    table = "multiday_predictions" if min_days_out > 0 else "predictions"
    excluded = _excluded_brier_condition_types()
    cond_clause, cond_params = _condition_type_not_in_sql(excluded)
    with _conn() as con:
        query = f"""
            SELECT p.our_prob, o.settled_yes
            FROM {table} p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND {cond_clause}
        """
        params: list = list(cond_params)
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
            ticker = t.get("ticker")
            if ticker and _paper_trade_excluded_condition_type(ticker) in excluded:
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

    Use this at display sites that need to show the sample count alongside the
    score. Excludes the same _excluded_brier_condition_types() population as
    brier_score() (backlog.txt "SEVERAL BRIER-FAMILY FUNCTIONS STILL HAVE NO
    CONDITION_TYPE FILTER" -- this function feeds main.py/output_formatters.py/
    pdf_report.py/web_app.py display paths and was previously undocumented-
    inconsistent with its cutoff_days-wrapper sibling brier_score_rolling()).
    """
    init_db()
    days = weeks * 7
    cond_clause, cond_params = _condition_type_not_in_sql(
        _excluded_brier_condition_types()
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_at >= datetime('now', '-{days} days')
              AND {cond_clause}
            """,
            cond_params,
        ).fetchall()
    n = len(rows)
    if not rows:
        return None, 0
    brier = sum((r["our_prob"] - r["settled_yes"]) ** 2 for r in rows) / n
    return round(brier, 4), n


def count_settled_predictions_rolling(weeks: int = 3) -> int:
    """Count multi-day predictions whose outcome settled within the last
    `weeks` weeks. Feeds weather_markets._regime_blend_settled_count() ->
    is_regime_blend_active() (a live regime-blend-weight activation gate) --
    same temperature-only maturity semantics as count_settled_predictions(),
    so it carries the same exclusion (backlog.txt "COUNT_SETTLED_
    PREDICTIONS() HAS NO CONDITION_TYPE FILTER", found via adjacency during
    that entry's own independent review: a live-trading-readiness gate
    should not count monthly rain/snow or two-sided 'between' rows any more
    here than it does in count_settled_predictions()).
    Now sourced from _excluded_brier_condition_types() (dynamic, gate-coupled)
    instead of a hardcoded tuple duplicate of count_settled_predictions()'s own.
    """
    init_db()
    days = weeks * 7
    cond_clause, cond_params = _condition_type_not_in_sql(
        _excluded_brier_condition_types()
    )
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM multiday_predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            "WHERE p.our_prob IS NOT NULL "
            f"  AND o.settled_at >= datetime('now', '-{days} days') "
            f"  AND {cond_clause}",
            cond_params,
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

    Excludes condition_type='between'/'precip_month_total'/'snow_month_total'/
    'hurricane_count'/'hurricane_next_event'/'storm_order' (same rationale as
    count_settled_predictions() -- found via adjacency during that entry's
    review; the 2 hurricane types added 2026-08-07, opus-review-caught, when
    the time-to-next-event model's own review found this list had never been
    extended for hurricane_count either; 'storm_order' added the same day
    when that model's own review found the same gap): this feeds
    paper.is_accuracy_halted(), the live circuit breaker that halts new
    trades on a bad win rate. A monthly rain/snow/hurricane row entering the
    rolling window carries an entirely different win-rate distribution than
    a directional temperature call and could either mask real temperature-
    model degradation or falsely trip the halt on unrelated volatility.

    Now sourced from _ALWAYS_EXCLUDED_CONDITION_TYPES, NOT the dynamic
    gate-coupled _excluded_brier_condition_types() (opus-review finding M5,
    batch-06): this function's own exclusion rationale above is structural
    (a different win-rate distribution shape that could mask/falsely-trip
    the circuit breaker) not shadow-market-family status -- that reasoning
    doesn't stop applying the moment a family goes live, so it must stay
    permanently excluded like 'between', not auto-include once a gate flips.
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _ALWAYS_EXCLUDED_CONDITION_TYPES
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT o.settled_yes, p.our_prob
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND {cond_clause}
            ORDER BY o.settled_at DESC
            LIMIT ?
            """,
            (*cond_params, window),
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
    """Return the number of settled multi-day predictions counted toward the
    live-trading maturity gates. Feeds the ENABLE_MICRO_LIVE graduation gate
    and the F3 auto-calibration trigger (cron.py) plus its console reminder
    and the dashboard mirror (web_app.py) -- all four are calibration-gate
    consumers that should count the same population F3's own calibration
    math (calibration.py) and the CLI calibration curves
    (get_multiday_calibration_cli below) already train on.

    Uses multiday_predictions view (days_out >= 1 or NULL) so same-day METAR
    trades don't inflate calibration gates or the graduation threshold — those
    are assessed on multi-day ensemble performance, not same-day observations.
    Also excludes condition_type='between' and 'precip_month_total'/
    'snow_month_total' (backlog.txt "COUNT_SETTLED_PREDICTIONS() HAS NO
    CONDITION_TYPE FILTER"), matching every sibling calibration query's
    exclusion (calibration.py's grid search, get_multiday_calibration_cli/
    get_sameday_calibration_cli below). On this repo's live data (2026-07-30)
    100% of the resulting count drop (102 -> 61) was 'between' rows -- zero
    monthly rain/snow rows have settled yet, so that part of the exclusion is
    prospective (protects against contamination the moment they do settle),
    while 'between' was the one actually inflating the gate's evidence base
    today. NOT fully "temperature-only" despite the maturity-gate framing
    above: daily precipitation condition types (weather_markets.py's
    precip_any/precip_above/precip_snow) are NOT excluded here -- this
    matches every one of the sibling queries' own gap (none of them exclude
    those either), so it isn't a regression introduced by this filter, but
    it also isn't closed. Zero such rows are settled today; extending the
    exclusion everywhere this pattern appears is a separate, larger change
    than this fix's scope.

    Counts raw ROWS, not distinct temperature-observation events (backlog.txt
    "COUNT_SETTLED_PREDICTIONS() COUNTS RAW ROWS, NOT DISTINCT TEMPERATURE-
    OBSERVATION EVENTS", re-examined 2026-07-31 -- deliberate, not an
    oversight). count_settled_snow_predictions() below counts distinct
    (ticker prefix, year, month) accrual events instead for the identical-
    looking reason (its 7 sibling KXDENSNOWM brackets all settle from one
    real monthly snowfall total), but that precedent does not carry over
    cleanly here:
    (1) This function's own population must match calibration.py's grid
        search / get_multiday_calibration_cli's training population (see
        above) -- both train on raw rows. Switching this counter to distinct
        events would decouple the maturity gate from the population it is
        supposed to gate access to, trading one mismatch for another.
    (2) A city+date pair here can legitimately hold TWO independent real
        observations, not one -- KXHIGH* (the day's high) and KXLOW* (the
        day's low) -- distinguishable only by ticker prefix, since the `var`
        column that should carry this is mostly NULL on live data. A naive
        (city, market_date) distinct-event key (the direct analog of snow's
        approach) would silently merge those two into one event, which is a
        new correctness bug, not a fix.
    (3) Checked live data (2026-07-31): grouping correctly by (city,
        market_date, high-or-low-from-ticker-prefix) yields 61 distinct
        events against 61 raw rows -- there are zero actual duplicate-
        ladder-bracket rows today, so hardening this now would change
        nothing while adding a second ticker-prefix parser to maintain.
    Revisit if/when live data ever shows the same city+date+high-or-low
    combination settling more than once (i.e. real ladder-bracket
    duplication, not a high/low pair) -- that would be the actual trigger
    condition this entry was watching for, and did not find.

    UPDATE 2026-08-20 (backlog.txt "BRIER-FAMILY CONDITION_TYPE EXCLUSION LIST
    HAS NO COUPLING TO RAIN/SNOW/HURRICANE GRADUATION GATES"): the exclusion
    list above is no longer a static hardcoded tuple -- it's now
    _excluded_brier_condition_types(), dynamically coupled to each shadow-only
    market family's own live-trading gate (weather_markets._rain_gates_active()
    etc.). Once RAIN_TRADING_ENABLED (or the snow/hurricane/storm-order
    equivalent) flips and that family's own sample floor clears, its settled
    rows start counting toward this maturity gate too -- closing the exact gap
    this backlog entry named ("the moment that flips, this function
    permanently excludes the calibration of a market family receiving real
    capital, with nothing to notice or adjust"). No gate is active today, so
    this changes zero live values now.
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _excluded_brier_condition_types()
    )
    with _conn() as con:
        row = con.execute(
            f"""
            SELECT COUNT(*) FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE {cond_clause}
            """,
            cond_params,
        ).fetchone()
    return row[0] if row else 0


def clamp_last_calibration_count(last_cal_count: int, current_settled: int) -> int:
    """Clamp a `.last_calibration_count` sentinel value against today's live
    count_settled_predictions() before computing "settled since last
    calibration". Shared by cron.py's real F3 auto-calibration trigger and
    web_app.py's dashboard mirror (backlog.txt "COUNT_SETTLED_PREDICTIONS()
    HAS NO CONDITION_TYPE FILTER" resolution, 2026-07-30) -- without this,
    a sentinel written under count_settled_predictions()'s counting basis
    BEFORE that fix (2026-07-30) can exceed today's narrower count with zero
    new trades settled, silently requiring far more than the usual +25
    settlements to re-trigger (stranding the gate on a basis change, not on
    real data). Self-heals in both directions for any future basis change:
    narrower -> resets to "as of today"; wider -> sentinel stays unchanged
    since real accumulation still governs when it's already ahead.
    """
    return min(last_cal_count, current_settled)


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


def count_settled_hourly_predictions() -> int:
    """Count settled KXTEMPxxxH hourly predictions (backlog.txt "HOURLY-
    DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item 5, the shadow-only
    rollout gate). Mirrors count_settled_sameday_predictions()/count_
    settled_below_predictions()'s exact shape. Ticker prefix set imported
    from weather_markets (same single-source-of-truth dict Step 1
    established) rather than hardcoded, so this can't independently drift.
    """
    init_db()
    try:
        from weather_markets import _KXTEMP_HOURLY_CITY

        prefixes = list(_KXTEMP_HOURLY_CITY)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE ({where_sql})",
            params,
        ).fetchone()
    return row[0] if row else 0


def count_settled_rain_predictions() -> int:
    """Count settled KXRAIN*M monthly-rain predictions (backlog.txt "RAIN /
    SNOW / HURRICANE MARKETS" Step 2 handoff item 7, the shadow-only
    rollout gate). Mirrors count_settled_hourly_predictions()'s exact
    shape. Ticker prefix set imported from weather_markets (same single-
    source-of-truth dict Step 1 established) rather than hardcoded, so
    this can't independently drift."""
    init_db()
    try:
        from weather_markets import _KXRAIN_MONTHLY_CITY

        prefixes = list(_KXRAIN_MONTHLY_CITY)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE ({where_sql})",
            params,
        ).fetchone()
    return row[0] if row else 0


def count_settled_market_implied_rain_events() -> int:
    """Count DISTINCT settled monthly-rain accrual events (ticker prefix,
    year, month) with a market-implied distribution fitted (implied_mean
    populated), NOT raw prediction rows -- sample-floor counter for
    backlog.txt "RAIN'S MARKET-IMPLIED DISTRIBUTION ... HAS NO GRADUATION/
    SAMPLE-FLOOR TRACKING OF ITS OWN", feeding
    weather_markets.SIGNAL_REGISTRY's "market_implied_rain" entry.

    implied_mean/implied_sigma are a single shared column pair populated for
    BOTH the existing "market_implied" (temperature) registry entry and rain
    events (via compute_market_implied_distributions()'s
    market_implied_rain_event_key() branch) -- the temperature entry's own
    count_settled_signal_rows("implied_mean") already excludes rain rows
    correctly (its require_settled_temp=True default; rain outcomes never
    populate settled_temp_f), but nothing counted the rain-only subset.

    Opus-review-caught (2026-08-01, before this ever shipped live): a raw-row
    count would inflate the floor the same way count_settled_snow_predictions()
    was rewritten to fix on 2026-07-30 -- resolve_market_implied_for_analysis()
    hands the SAME fitted result to every sibling bracket in one city-month's
    ladder, and each bracket re-logs on every scan-day for the whole accrual
    month (predictions' unique index is (ticker, predicted_date), not one row
    per event), so sample_floor=20 raw rows could clear on as few as ~7 real
    independent city-months rather than 20. Verified zero live implied_mean
    rain rows exist yet (new code, no shipped gate to avoid disrupting --
    matches count_settled_snow_predictions()'s own "safe to design the floor
    correctly from the start" reasoning, not count_settled_rain_predictions()'s
    "already live, don't shift it" one). Ticker-prefix filtering (mirrors
    count_settled_rain_predictions()'s/count_settled_snow_predictions()'s
    exact shape, same _KXRAIN_MONTHLY_CITY single-source-of-truth dict)
    rather than a settled_value/settled_temp_f column check -- avoids relying
    on those two columns staying mutually exclusive forever, and matches
    every other rain-specific counter's existing precedent."""
    init_db()
    try:
        from weather_markets import _KXRAIN_MONTHLY_CITY, _parse_monthly_ticker_month

        prefixes = list(_KXRAIN_MONTHLY_CITY)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT p.ticker FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE p.implied_mean IS NOT NULL AND ({where_sql})",
            params,
        ).fetchall()
    events: set[tuple[str, int, int]] = set()
    for row in rows:
        ticker = row["ticker"]
        parsed = _parse_monthly_ticker_month(ticker)
        if parsed is None:
            # Same silent-freeze guard count_settled_snow_predictions() added
            # (opus-review-caught round 2 there): an unparseable ticker must
            # warn, not vanish silently from the count.
            _log.warning(
                "count_settled_market_implied_rain_events: could not parse "
                "accrual month from settled ticker %r -- excluded from the "
                "count",
                ticker,
            )
            continue
        prefix = next((p for p in prefixes if ticker.upper().startswith(p)), None)
        if prefix is None:
            continue
        events.add((prefix, parsed[0], parsed[1]))
    return len(events)


def count_settled_snow_predictions() -> int:
    """Count DISTINCT settled monthly-snow accrual events (ticker prefix,
    year, month), NOT raw prediction rows -- opus-review-caught (2026-07-30):
    Denver's own KXDENSNOWM ladder alone has 7 sibling brackets that all
    settle from the SAME real snowfall observation for a given month, so a
    raw-row floor could clear the 20-sample threshold with as few as ~3
    real months of data, not 20 independent real-world observations. Unlike
    count_settled_rain_predictions() (which counts raw rows and is already
    live/shipped -- rain has 11 cities' worth of decorrelation across those
    rows, and changing its counting semantics now would shift an already-
    accumulating live gate's count out from under it), this function is
    new code with zero live predictions logged yet, so it's safe to design
    the floor correctly from the start rather than inherit the same gap.
    Ticker prefix set imported from weather_markets (same single-source-of-
    truth dict Snow Step 1 established) rather than hardcoded, so this
    can't independently drift."""
    init_db()
    try:
        from weather_markets import _KXSNOW_MONTHLY_CITY, _parse_monthly_ticker_month

        prefixes = list(_KXSNOW_MONTHLY_CITY)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT p.ticker FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE ({where_sql})",
            params,
        ).fetchall()
    events: set[tuple[str, int, int]] = set()
    for row in rows:
        ticker = row["ticker"]
        parsed = _parse_monthly_ticker_month(ticker)
        if parsed is None:
            # Opus-review-caught gap (round 2): silently dropping an
            # unparseable ticker (vs. the old row-counting version, which
            # at least counted it) means a real Kalshi ticker-format
            # change would freeze this gate at 0 forever with zero signal
            # that anything is wrong. Log loudly instead.
            _log.warning(
                "count_settled_snow_predictions: could not parse accrual "
                "month from settled ticker %r -- excluded from the count",
                ticker,
            )
            continue
        prefix = next((p for p in prefixes if ticker.upper().startswith(p)), None)
        if prefix is None:
            continue
        events.add((prefix, parsed[0], parsed[1]))
    return len(events)


# batch-40 follow-up (found live 2026-08-24, the morning after batch-40
# shipped, from cmd_cron's own real production output): between-bucket
# METAR lock-in was disabled 2026-06-29 (a broken implementation that
# compared the INSTANTANEOUS METAR reading against the bucket, not the
# daily running extreme -- the AC3 violation weather_markets._metar_lock_in's
# own between-branch comment documents) and re-enabled 2026-08-09 (bded3d6a,
# "re-enable between-bucket METAR lock-in on the daily extreme, not
# instantaneous temp"). Rows predicted before the re-enable measure DELETED
# code, not the current implementation -- batch-40's own handoff explicitly
# flagged this exact contamination ("do NOT cite the n=70 between rows with
# Brier 0.2825 -- 69/70 predate the 2026-06-29 implementation replacement
# and measure deleted code"), but batch-40's own new code (this function,
# and get_sameday_calibration()'s new by_condition_type breakdown) didn't
# actually filter it out -- confirmed live: of the 70 real between/
# days_out=0/metar_lockout rows in production, 69 have predicted_at
# '2026-06-03...' (pre-disable) and exactly 1 has predicted_at
# '2026-08-13...' (post-re-enable, the single real shadow prediction
# batch-40's own handoff cited). Without this cutoff,
# _between_metar_gates_active()'s 20-sample floor could clear almost
# entirely on dead-code residue with zero real evidence about the CURRENT
# formula -- exactly the failure mode Decision 2's shadow-only posture
# exists to prevent. Date-only (not the commit's exact time) since there is
# a multi-day gap with zero between rows on either side of it in the real
# data, so second-level precision cannot matter.
_BETWEEN_METAR_REENABLED_AT = "2026-08-09"


def count_settled_between_predictions() -> int:
    """Count settled between-bracket METAR-lock predictions -- batch-40
    "Between-bracket calibration design", Decision 1/2's sample-floor
    counter for weather_markets._between_metar_gates_active().

    Unlike count_settled_rain_predictions()/count_settled_snow_predictions()
    (ticker-prefix filtered), between shares its ticker family with
    above/below (same KXHIGH*/KXLOW* series -- see
    weather_markets.is_between_bracket_ticker's own docstring for why a
    ticker-prefix filter can't distinguish them), so this filters by
    condition_type='between' AND method='metar_lockout' AND days_out=0
    instead -- the exact same WHERE clause get_metar_lockout_calibration_data()
    already uses to SELECT between-eligible METAR-lock rows (that function
    excludes 'between' via _ALWAYS_EXCLUDED_CONDITION_TYPES; this counts the
    complementary population). No raw-row-vs-distinct-event inflation risk
    here the way count_settled_snow_predictions() had to fix for: each
    settled between ticker is its own distinct market/outcome (unlike a
    monthly ladder's shared sibling brackets), so a raw-row count is already
    a real per-market count.

    Also excludes any row predicted before _BETWEEN_METAR_REENABLED_AT --
    see that constant's own comment for why (dead-code contamination found
    live the day after this function first shipped).
    """
    init_db()
    with _conn() as con:
        row = con.execute(
            """
            SELECT COUNT(*) FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.condition_type = 'between'
              AND p.method = 'metar_lockout'
              AND p.days_out = 0
              AND p.predicted_at >= ?
            """,
            (_BETWEEN_METAR_REENABLED_AT,),
        ).fetchone()
    return row[0] if row else 0


def count_settled_hurricane_predictions() -> int:
    """Count DISTINCT settled hurricane-season-count events -- (basin,
    count_type, season_year), NOT raw prediction rows -- backlog.txt
    "HURRICANE MARKETS" season-count model's shadow-only rollout gate.
    Same raw-row-vs-distinct-event inflation risk count_settled_snow_
    predictions()/count_settled_market_implied_rain_events() were already
    fixed for: a single basin/count_type/season (e.g. Atlantic major-
    hurricane-count 2026) settles up to ~9 sibling strikes (KXHURCTOTMAJ's
    T3..T9 ladder) all from the SAME real season-end count, so a raw-row
    floor could clear 20 on as few as ~3 real seasons, not 20 independent
    real-world outcomes. New code, zero live predictions logged yet, so
    it's safe to design the floor correctly from the start (same reasoning
    count_settled_snow_predictions' own docstring gives).

    Ticker-only classification via weather_markets._hurricane_count_key_
    from_ticker (derives basin/count_type/season_year from the settled
    ticker string alone, same single-source-of-truth function
    _parse_hurricane_count_condition uses) rather than a hardcoded prefix
    list, so this can't independently drift from the real parser."""
    init_db()
    try:
        from weather_markets import (
            _HURRICANE_COUNT_SERIES,
            _hurricane_count_key_from_ticker,
        )

        prefixes = list(_HURRICANE_COUNT_SERIES)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT p.ticker FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE ({where_sql})",
            params,
        ).fetchall()
    events: set[tuple[str, str, int]] = set()
    for row in rows:
        ticker = row["ticker"]
        key = _hurricane_count_key_from_ticker(ticker)
        if key is None:
            # Opus-review-caught (2026-08-03): the SQL LIKE prefix for
            # "KXHURRICANE" also matches "KXHURRICANENAMES" (a different,
            # unsupported series -- storm-name-order markets, not one of
            # the 5 count series). That ticker is never actually logged as
            # a prediction today, but IF it (or any other lookalike) ever
            # were, warning here on every single call would desensitize the
            # exact alarm this warning exists to raise (a real ticker-
            # format change silently freezing the gate at 0) -- only warn
            # when the series prefix is genuinely one of the 5 supported
            # series and STILL failed to parse, matching
            # _parse_hurricane_count_condition's own real-failure-vs-wrong-
            # family distinction.
            if ticker.upper().split("-")[0] in _HURRICANE_COUNT_SERIES:
                _log.warning(
                    "count_settled_hurricane_predictions: could not parse "
                    "basin/count_type/season_year from settled ticker %r -- "
                    "excluded from the count",
                    ticker,
                )
            continue
        events.add(key)
    return len(events)


def count_settled_hurricane_next_event_predictions() -> int:
    """Count DISTINCT settled time-to-next-event tickers -- backlog.txt
    "HURRICANE MARKETS" time-to-next-event model's shadow-only rollout gate
    (2026-08-07). One combined counter/floor across both KXNEXTHURDATE and
    KXNEXTCAT5HURDATE, matching count_settled_hurricane_predictions' own
    precedent of one combined floor across all of ITS series/count-types
    rather than a floor per subtype.

    Unlike the season-count model, this market family has NO sibling-ladder-
    bracket-per-event risk -- each ticker is its own atomic "before <date>?"
    question, not one of several brackets sharing a settlement, so the
    ticker itself already IS the distinct-event key (no basin/event_type/
    date extraction needed, unlike count_settled_hurricane_predictions'
    _hurricane_count_key_from_ticker). Confirmed live (not assumed):
    log_prediction()'s own UPSERT already collapses repeated per-cron-cycle
    logging of the same open ticker into one row under normal operation, so
    that specific risk doesn't reach this query in practice -- COUNT(DISTINCT
    ticker) is kept anyway as cheap, always-correct defense-in-depth against
    any raw-row duplication (a future log_prediction change, a manual
    backfill, disputed-then-relogged rows), matching this codebase's general
    "prefer DISTINCT over trusting an upstream invariant" habit.

    Opus-review-caught: the SQL LIKE prefix (used only as a coarse pre-
    filter, for the same reason count_settled_hurricane_predictions()'s own
    LIKE prefix is coarse) is broader than is_hurricane_next_event_ticker()'s
    series-EXACT match -- a hypothetical "KXNEXTHURDATE2" series would
    inflate this count without ever being real-gated by
    _hurricane_next_event_gates_active(). Currently unreachable (any such
    ticker contains "HUR", so analyze_trade()'s blanket guard returns None
    and no prediction row is ever written for it) but the sibling counter
    already defends against exactly this shape via ticker-derived key
    validation, so filtering to exact series membership in Python here too,
    not trusting the coarse SQL filter alone."""
    init_db()
    try:
        from weather_markets import _HURRICANE_NEXT_EVENT_SERIES

        prefixes = list(_HURRICANE_NEXT_EVENT_SERIES)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT p.ticker FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE ({where_sql})",
            params,
        ).fetchall()
    return sum(1 for row in rows if row["ticker"].upper().split("-")[0] in prefixes)


def count_settled_storm_order_predictions() -> int:
    """Count DISTINCT settled storm-order tickers -- backlog.txt "HURRICANE
    MARKETS" storm-order model's shadow-only rollout gate (2026-08-07). One
    counter/floor across the 1 KXFIRSTHURRICANE series, mirroring
    count_settled_hurricane_next_event_predictions()'s exact shape.

    Same "ticker itself already IS the distinct-event key" reasoning as that
    function: each of the up-to-21 per-name tickers in a season is its own
    atomic "will <name> be the first hurricane" question, not one of several
    brackets sharing a settlement, so no basin/position/season_year
    extraction is needed here -- COUNT(DISTINCT ticker) is enough, same
    defense-in-depth-against-raw-row-duplication reasoning that function's
    own docstring gives.

    Same coarse-SQL-LIKE-prefix-then-Python-exact-filter shape as that
    function too, for the same reason: the LIKE prefix is only a pre-filter,
    is_storm_order_ticker()'s series-EXACT match is the real gate."""
    init_db()
    try:
        from weather_markets import _STORM_ORDER_SERIES

        prefixes = list(_STORM_ORDER_SERIES)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT p.ticker FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE ({where_sql})",
            params,
        ).fetchall()
    return sum(1 for row in rows if row["ticker"].upper().split("-")[0] in prefixes)


def count_settled_holiday_temp_predictions() -> int:
    """Count DISTINCT settled holiday-temp EVENTS (city, target_date), NOT
    raw ticker rows -- batch-51 item 2's own dedicated shadow-only rollout
    gate (2026-08-24).

    Opus-review-caught: the original version of this function counted
    distinct TICKERS, on the mistaken assumption (corrected 2026-08-24,
    after the review) that KXHOLIDAYTMAX/TMIN are single-binary-threshold
    markets with no ladder. Live-re-verified: KXHOLIDAYTMIN genuinely is
    (1 ticker/city/holiday), but KXHOLIDAYTMAX is NOT -- it has 3 sibling
    threshold brackets per city per holiday (confirmed live: SFO's Jul 4
    2026 event alone has KXHOLIDAYTMAX-260704100-SFO/-26070475-SFO/
    -26070485-SFO, all settling from the SAME real max-temp observation).
    Counting raw tickers would let 3 correlated siblings inflate the count
    3x for one real observation -- exactly the same failure mode already
    fixed once in this file for count_settled_snow_predictions() (Denver's
    7-bracket KXDENSNOWM ladder) and count_settled_hurricane_predictions()
    (7 sibling season-count strikes) -- see either docstring for the fuller
    "as few as ~3 real observations could clear a 20-sample floor" framing,
    which applies here identically. Given the episodic ~2x/year listing
    cadence, this matters more than usual: without the fix, a single Labor
    Day listing across 20 cities x up to 3 TMAX brackets could clear the
    entire 20-sample floor off ONE calendar date's weather, exactly the
    kind of non-independent-observation gate-clearing the floor exists to
    prevent.

    Event key is (series-without-threshold via weather_markets.
    parse_city_date, city, target_date) -- reuses the same positional
    ticker parser item 2's own implementation already established, rather
    than a second independent parser that could drift out of sync with it.
    Ticker-prefix membership (via is_holiday_temp_ticker, not
    condition_type) is still what isolates this family's rows from the
    already-graduated daily-temp population sharing the same "above"/
    "below" condition_type -- that part of the original design was correct
    and is unchanged."""
    init_db()
    try:
        from weather_markets import _KXHOLIDAY_TEMP_SUFFIX_SERIES, parse_city_date

        prefixes = list(_KXHOLIDAY_TEMP_SUFFIX_SERIES)
    except Exception:
        return 0
    if not prefixes:
        return 0
    where_sql = " OR ".join(["p.ticker LIKE ?"] * len(prefixes))
    params = tuple(f"{p}%" for p in prefixes)
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT p.ticker FROM predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE ({where_sql})",
            params,
        ).fetchall()
    events: set[tuple[str, str, str]] = set()
    for row in rows:
        ticker = row["ticker"]
        series = ticker.upper().split("-")[0]
        if series not in prefixes:
            continue
        city, target_date = parse_city_date({"ticker": ticker})
        if city is None or target_date is None:
            _log.warning(
                "count_settled_holiday_temp_predictions: could not parse "
                "city/date from settled ticker %r -- excluded from the count",
                ticker,
            )
            continue
        events.add((series, city, target_date.isoformat()))
    return len(events)


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


def count_emos_variance_ready_predictions() -> int:
    """Count multiday_predictions rows with ens_mean, settled_temp_f, AND
    ens_var all populated -- the population EMOS actually uses to fit its
    c/d (variance) parameters, not just a/b.

    count_emos_ready_predictions() counts ens_mean+settled_temp_f rows
    regardless of ens_var, so it clears the Gneiting 2005 40-row floor
    earlier than the variance fit's real data actually does whenever
    backfilled Previous-Runs-API rows (which never carry ens_var) make up
    part of the total. This stricter count is what should gate any
    "EMOS is READY" message -- fitting c/d on fewer than 40 real ens_var
    rows (see main._cmd_emos_train's own >= 10 floor, well below the
    40-row statistical minimum) understates the sample the fit is really
    built on.
    """
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM multiday_predictions p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            "WHERE p.ens_mean IS NOT NULL AND o.settled_temp_f IS NOT NULL "
            "AND p.ens_var IS NOT NULL"
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


# AUD-0052: count_settled_signal_rows() interpolates column/json_key
# straight into its SQL (SQLite has no placeholder syntax for identifiers),
# so it trusts every caller to only ever pass a fixed literal -- true today
# (every weather_markets.py SIGNAL_REGISTRY call site and every test call
# site passes a hardcoded string, not derived/external input), but nothing
# enforced it. This allowlist is a defense-in-depth check independent of
# that caller discipline, not a reaction to any actual bad caller found.
# Whoever adds a new SIGNAL_REGISTRY entry (_count_signal_column/
# _count_signal_json_key in weather_markets.py) must add its column/
# json_key name here too, or the new call raises ValueError.
_SIGNAL_COLUMN_ALLOWLIST = frozenset(
    {
        "run_trend_delta",
        "implied_mean",
        "gated_edge",
        "ensemble_spread_f",
        "nbm_quantile_prob",
        "ecmwf_consensus_gap_prob",
    }
)
_SIGNAL_JSON_KEY_ALLOWLIST = frozenset(
    {
        "rain_forecast_blend_prob",
    }
)


def count_settled_signal_rows(
    column: str | None = None,
    *,
    json_key: str | None = None,
    multiday: bool = False,
    require_settled_temp: bool = True,
) -> int:
    """Count settled predictions with a non-NULL value for a logged signal.

    Generic sample-floor counter for backlog.txt's "SIGNAL GRADUATION IS A
    CONVENTION" registry (weather_markets.SIGNAL_REGISTRY) — covers both a
    signal with its own dedicated column on `predictions` (column=, e.g.
    "run_trend_delta") and a key inside the generic `signal_values` JSON
    column (json_key=, for any future signal shipped only through
    log_prediction(signals=...) with no dedicated migration). Exactly one
    of column/json_key must be given — raises ValueError otherwise, rather
    than silently ignoring whichever one wasn't meant. `column`/`json_key`
    are always registry-defined literals in every real caller today, same
    as count_settled_hourly_predictions'/count_settled_rain_predictions'
    own dynamic WHERE-clause construction — but unlike those two, this
    function additionally enforces that trust boundary itself (AUD-0052:
    _SIGNAL_COLUMN_ALLOWLIST/_SIGNAL_JSON_KEY_ALLOWLIST below, checked
    before either name is interpolated into SQL) as defense-in-depth
    independent of caller discipline, rather than relying on it alone.

    Joins outcomes_valid (excludes disputed rows, matching every other
    calibration-adjacent count in this file) and requires a real settled
    temperature, not just any settled-outcome row — matches the literal
    condition backlog.txt's own run_trend ENABLEMENT TRIGGER text specifies
    (`run_trend_delta IS NOT NULL AND settled_temp_f IS NOT NULL`).

    multiday=True switches from `predictions` to the `multiday_predictions`
    view (days_out >= 1 or NULL) — pass this for a signal whose own
    production logic is genuinely restricted to multi-day markets (e.g.
    run_trend: get_forecast_run_trend's own docstring says "Only applies to
    multi-day markets", same-day uses the METAR pipeline instead), matching
    count_settled_predictions'/count_emos_ready_predictions' own precedent
    of using that view specifically "so same-day METAR trades don't inflate
    ... the graduation threshold." Leave False (the default) for a signal
    that's genuinely computed for same-day markets too (e.g. gated_edge, a
    liquidity gate with no days_out restriction) — using the multiday view
    there would silently undercount real same-day samples, not just guard
    against noise.

    require_settled_temp=False drops the settled_temp_f requirement entirely
    -- pass this for a signal whose market family never populates that
    column in the first place (e.g. KXRAIN*M monthly-rain rows, which write
    settled_value not settled_temp_f -- see audit_settlement()'s own rain
    branch). Leaving the default True for such a signal doesn't just
    undercount, it makes the count permanently 0 regardless of how much real
    settled data accumulates, since settled_temp_f can never be non-NULL for
    that row -- a bug initially caught by opus review 2026-07-28 (found the
    exact same class of gap count_settled_rain_predictions() above already
    exists specifically to avoid, by having no settled_temp_f filter at
    all). Matches count_settled_rain_predictions()'s own join exactly when
    False.
    """
    if (column is None) == (json_key is None):
        raise ValueError(
            "count_settled_signal_rows: pass exactly one of column= or json_key="
        )
    init_db()
    if json_key:
        if json_key not in _SIGNAL_JSON_KEY_ALLOWLIST:
            raise ValueError(
                f"count_settled_signal_rows: json_key={json_key!r} is not in "
                "_SIGNAL_JSON_KEY_ALLOWLIST -- add it there if this is a real "
                "new signal, not a typo/derived value"
            )
        where = f"json_extract(p.signal_values, '$.{json_key}') IS NOT NULL"
    else:
        if column not in _SIGNAL_COLUMN_ALLOWLIST:
            raise ValueError(
                f"count_settled_signal_rows: column={column!r} is not in "
                "_SIGNAL_COLUMN_ALLOWLIST -- add it there if this is a real "
                "new signal, not a typo/derived value"
            )
        where = f"p.{column} IS NOT NULL"
    if require_settled_temp:
        where += " AND o.settled_temp_f IS NOT NULL"
    table = "multiday_predictions" if multiday else "predictions"
    with _conn() as con:
        row = con.execute(
            f"SELECT COUNT(*) FROM {table} p "
            "JOIN outcomes_valid o ON p.ticker = o.ticker "
            f"WHERE {where}"
        ).fetchone()
    return row[0] if row else 0


def count_model_observations(model: str) -> int:
    """Count settled (predicted_temp AND actual_temp populated) rows in
    ensemble_member_scores for one model.

    Used by the signal-graduation registry's sample-floor check for tracked
    ensemble models that aren't per-prediction columns (GEM/UKMO graduation,
    3-way ECMWF consensus) — mirrors get_member_accuracy()'s own filter
    (predicted_temp/actual_temp both non-NULL, model != 'blended' is
    irrelevant here since callers always pass a real model name) but scoped
    to one model and returning a plain count instead of a full MAE breakdown.
    """
    init_db()
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM ensemble_member_scores "
            "WHERE model = ? AND predicted_temp IS NOT NULL AND actual_temp IS NOT NULL",
            (model,),
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
    """Return rows for EMOS fitting: {ens_mean, ens_var, settled_temp_f,
    city, market_date}.

    Excludes rows where ens_mean or settled_temp_f is NULL.
    ens_var may be NULL for backfill rows — callers must handle None.
    Only multi-day predictions (days_out >= 1 or NULL).

    city/market_date (audit batch-28 item 3 review follow-up, round 2):
    main.py's _cmd_emos_train needs these to group rows before its temporal
    train/held-out split -- multiple predictions of the same (city,
    market_date) (different days_out, different cron cycles) share the same
    settled_temp_f label and near-identical ens_mean, so a plain row-level
    split can put part of one real "event" in training and part in the
    held-out set, leaking that event's outcome into the fit the held-out
    check is supposed to be validating against.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.ens_mean, p.ens_var, o.settled_temp_f, p.city, p.market_date
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
            "city": r[3],
            "market_date": r[4],
        }
        for r in rows
    ]


def get_metar_lockout_calibration_data() -> list[dict]:
    """Return rows for ml_bias.fit_metar_calibration(): {our_prob, settled_yes}
    for METAR-locked same-day above/below predictions.

    Scoped to condition_type NULL/above/below (same exclusion list as
    get_sameday_calibration_cli) -- between/precip/etc. share the lock-in
    formula but weren't part of the calibration gap this measures, and are
    deliberately excluded from correction until validated separately.

    Now sourced from _ALWAYS_EXCLUDED_CONDITION_TYPES, NOT the dynamic
    gate-coupled _excluded_brier_condition_types() (opus-review finding M5,
    batch-06): "until validated separately" above is a validation-pending
    reason, not a shadow-market-family one -- there's no mechanism that
    would ever mark a type "validated" the moment a live-trading gate
    flips, so coupling this to those gates was simply wrong, not just
    imprecise.

    COALESCE(p.raw_prob, p.our_prob), NOT a bare `our_prob` (audit batch-28
    item 1): `our_prob` is the value AFTER this same METAR beta-calibration
    already ran once (weather_markets.analyze_trade applies
    apply_metar_calibration and stores the result as our_prob); `raw_prob`
    is the pre-calibration reconstruction log_prediction added specifically
    so a retrain fits on the true raw series. Selecting our_prob here would
    have each weekly retrain fit on its own prior output -- generation 1
    corrects (0.07->0.57 on the documented two-band geometry), generation 2
    fits an exact identity transform on the now-already-corrected values,
    generation 3 reverts -- oscillating rather than converging.

    COALESCE only falls back to our_prob when raw_prob is NULL -- rows
    written before the raw_prob column existed at all (independent review,
    audit batch-28 item 1 follow-up: NOT, as an earlier version of this
    docstring claimed, "any row predating the fix" -- a row written after
    the column existed but before the 2026-08-16 fix that made `bias`
    non-zero on the metar_locked path has a real, non-NULL raw_prob that's
    already equal to our_prob, so COALESCE selects that already-calibrated
    value for it too. That historical contamination window is small
    (2026-08-16 landed the same day as the raw_prob column) and not
    separately excluded here -- fixing it would need a predicted_at cutover
    filter, deliberately not added since the affected row count is tiny and
    self-dilutes out of a growing training set over time).
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _ALWAYS_EXCLUDED_CONDITION_TYPES
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT COALESCE(p.raw_prob, p.our_prob), o.settled_yes
            FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND p.days_out = 0
              AND p.method = 'metar_lockout'
              AND {cond_clause}
            """,
            cond_params,
        ).fetchall()
    return [{"our_prob": float(r[0]), "settled_yes": int(r[1])} for r in rows]


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

    Excludes the same _excluded_brier_condition_types() population as
    brier_score() (backlog.txt "SEVERAL BRIER-FAMILY FUNCTIONS STILL HAVE NO
    CONDITION_TYPE FILTER" -- this function feeds cron.py's operator-facing
    two-consecutive-weeks Brier alert, previously unfiltered).
    """
    init_db()
    # SQLite-format cutoff (not Python isoformat) -- predicted_at is written by
    # SQLite's datetime('now') as 'YYYY-MM-DD HH:MM:SS'. A Python isoformat
    # cutoff ('...T...+00:00') compares lexicographically below every row on
    # the boundary date (' ' < 'T'), silently dropping the whole boundary day.
    cutoff = (datetime.now(UTC) - timedelta(weeks=weeks)).strftime("%Y-%m-%d %H:%M:%S")
    table = "multiday_predictions" if min_days_out > 0 else "predictions"
    cond_clause, cond_params = _condition_type_not_in_sql(
        _excluded_brier_condition_types()
    )
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
              AND {cond_clause}
            GROUP BY week
            ORDER BY week
            """,
            (cutoff, *cond_params),
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
      by_condition_type — {condition_type: {n, brier, mean_prob, mean_actual, bias}}
                    batch-40 "Between-bracket calibration design", Decision 1:
                    same-shape breakdown as by_time_of_day, but split by
                    p.condition_type instead of local_hour. Added because this
                    was previously the one surface with between rows that
                    pooled every condition_type together with no split --
                    invisible the same way brier_by_condition_type_rolling()
                    is invisible to between (that function reads
                    multiday_predictions, which excludes days_out=0 entirely,
                    so it never sees a between row at all; a between trade
                    only ever exists via a same-day METAR lock -- see
                    weather_markets.is_between_bracket_ticker's docstring).
                    NULL condition_type rows (pre-dating that column, or a
                    logging path that never set it) are grouped under the key
                    "unspecified" rather than silently dropped. The
                    'between' slice specifically excludes rows predicted
                    before _BETWEEN_METAR_REENABLED_AT (see that constant's
                    own comment) -- dead-code-era rows from before the
                    2026-08-09 re-enable, found contaminating this exact
                    breakdown live the day after it shipped. This exclusion
                    applies ONLY to the by_condition_type breakdown, not to
                    the top-level n/brier/calibration_buckets/by_time_of_day
                    above, which keep this function's original "includes
                    ALL condition types" pooled contract unchanged.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.our_prob, o.settled_yes, p.local_hour, p.condition_type,
                   p.predicted_at
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

    # batch-40 Decision 1: condition_type breakdown, same shape as by_tod
    # above. Grouped in Python (not SQL GROUP BY) to reuse the same `rows`
    # fetch and the same n/brier/mean/bias arithmetic as by_tod, rather than
    # a second query. 'between' rows predating the re-enable are skipped
    # here only -- `rows` itself (and therefore `curve`/`by_tod` above,
    # already computed) are untouched, preserving this function's existing
    # pooled contract.
    by_cond: dict[str, dict] = {}
    cond_members: dict[str, list[tuple[float, int]]] = {}
    for r in rows:
        key = r["condition_type"] or "unspecified"
        if key == "between" and r["predicted_at"] < _BETWEEN_METAR_REENABLED_AT:
            continue
        cond_members.setdefault(key, []).append(
            (float(r["our_prob"]), int(r["settled_yes"]))
        )
    for cond_type, members in cond_members.items():
        n = len(members)
        probs = [p for p, _ in members]
        actuals = [a for _, a in members]
        brier = sum((p - a) ** 2 for p, a in members) / n
        mean_prob = sum(probs) / n
        mean_actual = sum(actuals) / n
        by_cond[cond_type] = {
            "n": n,
            "brier": round(brier, 4),
            "mean_prob": round(mean_prob, 4),
            "mean_actual": round(mean_actual, 4),
            "bias": round(mean_prob - mean_actual, 4),
        }

    return {
        **curve,
        "t_sameday": t_sameday,
        "by_time_of_day": by_tod,
        "by_condition_type": by_cond,
    }


def get_multiday_calibration_cli() -> dict:
    """Calibration analytics for multi-day (days_out IS NULL OR >=1) predictions,
    scoped to match what the CLI (validate/backtest) has always shown: excludes
    condition_type='between', matching train_all_temperature_scaling()'s own
    exclusion (ml_bias.py) and both CLI blocks' pre-existing behavior. Also
    excludes 'precip_month_total', 'snow_month_total', 'hurricane_count',
    'hurricane_next_event', and 'storm_order' (backlog.txt "RAIN / SNOW /
    HURRICANE MARKETS" Step 2 / Snow Step 2 / HURRICANE MARKETS' three
    hurricane sub-models) for the same reason -- an inches-scale or
    basin/season-shaped probability doesn't belong in a °F-tuned multiday
    calibration curve.

    Returns {n, gate, gate_met, brier, t_multiday, calibration_buckets} — same shape
    as get_sameday_calibration() minus the sameday-only by_time_of_day breakdown.
    t_multiday is read from temperature_scale.json's "global" key — confirmed via
    apply_temperature_scaling() (ml_bias.py): days_out=0 uses "sameday" exclusively,
    everything else falls back to condition_type then "global", so "global" IS the
    multiday T, not a separate catch-all.

    Now sourced from _ALWAYS_EXCLUDED_CONDITION_TYPES, NOT the dynamic
    gate-coupled _excluded_brier_condition_types() (opus-review finding M5,
    batch-06): the "inches-scale/basin-shaped probability doesn't belong in
    a °F-tuned calibration curve" reason above is a physical-scale mismatch
    for fitting the temperature_scale.json T-parameter, not a shadow-
    market-family one -- it stays true forever regardless of any
    RAIN/SNOW/HURRICANE_TRADING_ENABLED flag, so this must stay permanently
    excluded like 'between', not auto-include once a gate flips. Matches
    ml_bias.py's train_all_temperature_scaling() (still a static hardcoded
    tuple, out of this fix's file scope) by construction now, not just
    coincidentally today (backlog.txt follow-up still filed for the
    ml_bias.py/calibration.py/main.py sites to migrate onto this shared
    constant when their own batch touches those files).
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _ALWAYS_EXCLUDED_CONDITION_TYPES
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT p.our_prob, o.settled_yes
            FROM multiday_predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND {cond_clause}
            """,
            cond_params,
        ).fetchall()

    t_multiday = _read_temperature_scale_key("global")
    curve = _calibration_curve(
        [(float(r["our_prob"]), int(r["settled_yes"])) for r in rows]
    )
    return {**curve, "t_multiday": t_multiday}


def get_sameday_calibration_cli() -> dict:
    """Same population as get_sameday_calibration() but excludes
    condition_type='between', 'precip_month_total', 'snow_month_total',
    'hurricane_count', 'hurricane_next_event', and 'storm_order', matching
    the CLI's (validate/backtest) existing scope. The dashboard-
    facing get_sameday_calibration() deliberately keeps 'between' rows —
    the two differ by 69 rows on this repo's live data (2026-07-08) and are NOT
    interchangeable.

    Returns {n, gate, gate_met, brier, t_sameday, calibration_buckets} — no
    by_time_of_day breakdown (the CLI doesn't currently surface it; dashboard's
    get_sameday_calibration() remains the source for that).

    Now sourced from _ALWAYS_EXCLUDED_CONDITION_TYPES, NOT the dynamic
    gate-coupled _excluded_brier_condition_types() (opus-review finding M5,
    batch-06) -- same °F-scale-mismatch reasoning as
    get_multiday_calibration_cli(), see that function's docstring for the
    full explanation and the ml_bias.py/calibration.py/main.py note.
    """
    init_db()
    cond_clause, cond_params = _condition_type_not_in_sql(
        _ALWAYS_EXCLUDED_CONDITION_TYPES
    )
    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
              AND p.days_out = 0
              AND {cond_clause}
            """,
            cond_params,
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


def _fetch_asos_observations(
    station: str, target_date: date, city_tz: str = "UTC"
) -> list[tuple[datetime, float]]:
    """Fetch every IEM ASOS METAR reading on `target_date`'s LOCAL calendar
    day for `station`, as (local_datetime, temp_f) pairs.

    Extracted from _fetch_asos_daily_temp() (backlog.txt "HOURLY-DIRECTIONAL
    TEMPERATURE MARKETS" Step 2) so the daily max/min reduction and the new
    hour-specific "nearest reading" reduction (_fetch_asos_hour_temp) share
    the identical fetch/parse/local-day-filter logic rather than risk two
    independently-drifting copies of it. See the original function's
    docstring for why the UTC sts/ets window and local-day filter are built
    the way they are (US cities' local midnight straddles two UTC dates).

    Returns [] on any fetch or parse error, or if no readings fall on the
    target local day.
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
        observations: list[tuple[datetime, float]] = []
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
                observations.append((obs_local, float(raw)))
            except ValueError:
                continue  # 'M' (missing)
        return observations
    except Exception:
        return []


def _fetch_asos_daily_temp(
    station: str, target_date: date, var: str, city_tz: str = "UTC"
) -> float | None:
    """Fetch daily high (var='max') or low (var='min') from IEM ASOS archive.

    Uses Iowa Environmental Mesonet hourly ASOS observations for the exact
    ICAO station Kalshi uses for settlement — a point reading, not a grid cell.
    See _fetch_asos_observations() for the fetch/parse/local-day-filter logic.

    Falls back to None on any fetch or parse error.

    No production callers as of 2026-08-10 -- audit_settlement()'s daily
    branch (its only former caller) now reads Kalshi's own settled
    expiration_value directly instead (backlog.txt "DATA-DRIVEN SIGMA FROM
    SETTLED HISTORY + CLI-REPORT SETTLEMENT FETCH", finding F1). Retained,
    not deleted, because tests/test_tracker.py's TestFetchAsosDailyTemp
    exercises it directly as a standalone unit and _fetch_actual_daily_temp
    (below) still needs a documented ASOS-vs-OpenMeteo comparison point.
    """
    observations = _fetch_asos_observations(station, target_date, city_tz)
    if not observations:
        return None
    temps = [t for _, t in observations]
    return max(temps) if var == "max" else min(temps)


def _fetch_asos_hour_temp(
    station: str, target_date: date, hour: int, city_tz: str = "UTC"
) -> float | None:
    """Fetch the ASOS reading nearest local `hour` on `target_date`, for
    KXTEMPxxxH hourly settlement (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE
    MARKETS" Step 2 handoff item 3). Reduction change, not a new data source
    -- the raw METAR feed already has hourly-resolution readings; this picks
    the observation closest to the target hour instead of the whole day's
    max()/min() (_fetch_asos_daily_temp above).

    METAR observations aren't always exactly on the hour (routine reports
    commonly land at :51-:56 past) -- "nearest" is measured in wall-clock
    minutes from target_date at hour:00 local, not an exact-hour match.

    Falls back to None on any fetch/parse error or if no readings exist for
    the target local day.
    """
    from zoneinfo import ZoneInfo

    observations = _fetch_asos_observations(station, target_date, city_tz)
    if not observations:
        return None
    target_dt = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour,
        0,
        0,
        tzinfo=ZoneInfo(city_tz),
    )
    _, nearest_temp = min(
        observations, key=lambda obs: abs((obs[0] - target_dt).total_seconds())
    )
    return nearest_temp


def _fetch_actual_daily_temp(
    lat: float, lon: float, tz: str, target_date: date, var: str
) -> float | None:
    """Fetch observed daily high (var='max') or low (var='min') from Open-Meteo archive.

    Fallback used when no ASOS station is mapped for a city. Prefer
    _fetch_asos_daily_temp for any city with a known ICAO station — Open-Meteo
    uses gridded ERA5 reanalysis which can differ from point station readings
    by up to 3°F at cities where the airport sits in a different microclimate.

    No production callers as of 2026-08-10, same as _fetch_asos_daily_temp
    above -- see that function's docstring.
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


_settlement_client = None
_settlement_client_env: str | None = None


def _get_settlement_kalshi_client():
    """Lazily build a KalshiClient from env vars, mirroring main.py's
    build_client() shape, so audit_settlement() (and its other 2 callers,
    backfill_emos_data() and the manual-recompute site, neither of which
    has a client of its own) can fetch a single rain market's raw data on
    demand without threading a client parameter through every call site.
    Cached at module level so repeated audit_settlement() calls in a
    sync_outcomes loop don't rebuild it. Deliberately re-fetches rather
    than reusing sync_outcomes' own already-fetched `market` dict (that
    call site is the only one of the 3 that has it handy) -- trades one
    redundant API call per settling ticker for keeping this function's
    signature unchanged for its other 2 callers. Cheap for rain/snow
    (~10/month); UPDATE 2026-08-10: the daily HIGH/LOW branch now makes
    this same trade too (previously ASOS/OpenMeteo, no Kalshi call at all)
    -- still one extra call per settling ticker, same negligible-per-call
    cost, just a higher-volume caller than rain/snow (backlog.txt
    "DATA-DRIVEN SIGMA FROM SETTLED HISTORY + CLI-REPORT SETTLEMENT FETCH",
    finding F1).

    Rebuilds if KALSHI_ENV changes since the cached client was built
    (review-caught: main.py's build_client() re-reads it fresh every call
    specifically to survive a cmd_settings runtime reload -- this cache
    would otherwise keep fetching from the old environment after a live
    env flip)."""
    global _settlement_client, _settlement_client_env
    import os

    _current_env = os.getenv("KALSHI_ENV", "demo")
    if _settlement_client is None or _settlement_client_env != _current_env:
        from kalshi_client import KalshiClient

        _settlement_client = KalshiClient(
            key_id=os.getenv("KALSHI_KEY_ID"),
            private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
            env=_current_env,
        )
        _settlement_client_env = _current_env
    return _settlement_client


def audit_settlement(ticker: str, settled_yes: bool) -> bool:
    """Write outcomes.settled_temp_f / settled_value from Kalshi's own
    settlement data where possible, cross-checking our own condition/
    threshold parsing against it.

    Daily HIGH/LOW temperature markets (backlog.txt "DATA-DRIVEN SIGMA FROM
    SETTLED HISTORY + CLI-REPORT SETTLEMENT FETCH", finding F1 in
    docs/feature-scan-2026-08-09.md): reads market.get("expiration_value")
    directly once status="finalized" — the literal CLI-report figure Kalshi
    settled on — mirroring the monthly rain/snow branches below. This
    REPLACES the IEM ASOS raw-METAR archive proxy this branch used before
    2026-08-10: that proxy was confirmed to legitimately disagree with
    Kalshi's real CLI-report-based settlement by ~1 degree near a threshold
    (2026-07-05, KXLOWTMIN-26JUN28-T66: fresh ASOS KMSP read 67.0F against a
    66F "greater than" threshold — implying YES — while Kalshi's real
    settlement was NO). expiration_value is populated identically across
    every strike in a daily HIGH/LOW event regardless of threshold (live-
    verified 2026-08-09/2026-08-10 across 18 of the 36 tracked daily series,
    including a same-event cross-strike check), so no HIGH/LOW (var)
    derivation is needed for this branch. A MISMATCH warning on this path
    now means our own condition/threshold parsing disagrees with Kalshi's
    real settlement — i.e. a bug worth investigating, not proxy/CLI noise.

    HOURLY temperature markets (KXTEMPxxxH, handled further below) are
    unaffected by the above and still derive settled_value from the IEM
    ASOS raw-METAR archive — Kalshi has no analogous single-hour
    expiration_value to read, so the same proxy caveat (and the
    proxy/CLI-report divergence risk) still applies there.

    Logs a WARNING when the settled temperature contradicts Kalshi's YES/NO
    result. Skips silently if the ticker is unparseable, settlement data is
    unavailable, or the condition type can't be verified with a single
    temperature value (e.g. between, precipitation).

    Returns True if settled_temp_f was actually written, False if this call
    skipped for any reason (unparseable ticker/city, no coords, not yet
    finalized, no expiration_value, etc.) — callers that loop over many
    tickers (e.g. a backfill) should use this instead of re-reading the DB,
    since a False here means the row's prior value (if any) was left
    completely untouched, not confirmed correct.
    """
    try:
        from weather_markets import _KXRAIN_MONTHLY_CITY, _KXSNOW_MONTHLY_CITY
        from weather_markets import CITY_COORDS as _coords
        from weather_markets import _metar_station_for_city as _station_for_city
        from weather_markets import _parse_market_condition as _parse_cond
        from weather_markets import parse_city_date as _parse_city_date

        # ── Monthly rain settlement (backlog.txt "RAIN / SNOW / HURRICANE
        # MARKETS" Step 2 handoff item 5) ─────────────────────────────────────
        # Checked FIRST, before the city/target_date early-return below --
        # parse_city_date() always returns target_date=None for KXRAIN*M
        # tickers (no day component, by design), so that early return would
        # otherwise always fire before this ticker-prefix check is ever
        # reached (unlike the hourly branch further below, which works
        # precisely because hourly tickers DO have a real target_date).
        # Settlement is simpler than the hourly/daily paths: Kalshi's own
        # market data carries the literal settled monthly total
        # (expiration_value) once status="finalized" -- no independent
        # ground-truth re-derivation needed here, just read it. settled_var
        # deliberately left untouched (NULL) -- resolved this session: it's
        # a max/min-hour discriminator with no analog for a monthly total,
        # and has zero production readers today.
        if ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY)):
            try:
                client = _get_settlement_kalshi_client()
                market = client.get_market(ticker)
            except Exception as exc:
                _log.warning(
                    "audit_settlement[%s]: rain market fetch failed: %s", ticker, exc
                )
                return False
            if market.get("status") != "finalized":
                return False
            exp_val = market.get("expiration_value")
            if exp_val is None:
                _log.warning(
                    "audit_settlement[%s]: finalized but no expiration_value", ticker
                )
                return False
            try:
                settled_value = float(exp_val)
            except (TypeError, ValueError):
                _log.warning(
                    "audit_settlement[%s]: non-numeric expiration_value=%r",
                    ticker,
                    exp_val,
                )
                return False
            with _conn() as con:
                cur = con.execute(
                    "UPDATE outcomes SET settled_value = ? WHERE ticker = ?",
                    (settled_value, ticker),
                )
            if cur.rowcount < 1:
                _log.warning(
                    "audit_settlement[%s]: no matching outcomes row -- "
                    "settled_value not actually written",
                    ticker,
                )
                return False
            return True

        # ── Monthly snow settlement (backlog.txt "RAIN / SNOW / HURRICANE
        # MARKETS" Snow Step 2) ─────────────────────────────────────────────────
        # Same shape and reasoning as the monthly rain branch just above --
        # checked before the city/target_date early-return for the same
        # reason (parse_city_date() always returns target_date=None for
        # these tickers too).
        if ticker.upper().startswith(tuple(_KXSNOW_MONTHLY_CITY)):
            try:
                client = _get_settlement_kalshi_client()
                market = client.get_market(ticker)
            except Exception as exc:
                _log.warning(
                    "audit_settlement[%s]: snow market fetch failed: %s", ticker, exc
                )
                return False
            if market.get("status") != "finalized":
                return False
            exp_val = market.get("expiration_value")
            if exp_val is None:
                _log.warning(
                    "audit_settlement[%s]: finalized but no expiration_value", ticker
                )
                return False
            try:
                settled_value = float(exp_val)
            except (TypeError, ValueError):
                _log.warning(
                    "audit_settlement[%s]: non-numeric expiration_value=%r",
                    ticker,
                    exp_val,
                )
                return False
            with _conn() as con:
                cur = con.execute(
                    "UPDATE outcomes SET settled_value = ? WHERE ticker = ?",
                    (settled_value, ticker),
                )
            if cur.rowcount < 1:
                _log.warning(
                    "audit_settlement[%s]: no matching outcomes row -- "
                    "settled_value not actually written",
                    ticker,
                )
                return False
            return True

        city, target_date = _parse_city_date({"ticker": ticker, "title": ""})
        if not city or not target_date:
            return False

        coords = _coords.get(city)
        if not coords:
            return False
        _, _, tz = coords

        # ── Hourly settlement (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE
        # MARKETS" Step 2 handoff item 3) ────────────────────────────────────
        # KXTEMPxxxH tickers settle into settled_value/settled_var, not
        # settled_temp_f -- an entirely different write target, so this
        # branches off before any of the daily-specific var/condition-type
        # logic below (which assumes the market is about the day's high/low,
        # not one specific hour).
        from weather_markets import _KXTEMP_HOURLY_CITY
        from weather_markets import parse_ticker_hour as _parse_ticker_hour

        if any(ticker.upper().startswith(p) for p in _KXTEMP_HOURLY_CITY):
            hour = _parse_ticker_hour(ticker)
            if hour is None:
                return False
            hourly_var: str | None = None
            # batch-52: also pull condition_type/threshold_lo/threshold_hi
            # here (mirrors the daily branch's own predictions-table read
            # below) -- needed for the Miami index cross-check further down;
            # unused for the other 5 cities but harmless to fetch always
            # rather than duplicating this SELECT a second time.
            #
            # opus review L-7: this DOES widen the failure surface of code
            # shared by all 6 cities, not just Miami -- the broad `except
            # Exception: pass` below now covers a 4-column query where it
            # previously covered a 1-column one. If condition_type/
            # threshold_lo/threshold_hi were ever unavailable for a row,
            # hourly_var would silently go None too and settled_var would
            # be written NULL for EVERY hourly city, not just Miami. Judged
            # acceptable rather than splitting into two separate queries:
            # all 4 columns are in the base predictions schema (this file's
            # own CREATE TABLE), so this is a real but practically
            # unreachable coupling, not a live risk -- documented explicitly
            # here rather than left as an implicit "harmless" assumption.
            hourly_cond_type: str | None = None
            hourly_threshold_lo: float | None = None
            hourly_threshold_hi: float | None = None
            try:
                with _conn() as _con:
                    _hv_row = _con.execute(
                        "SELECT var, condition_type, threshold_lo, threshold_hi"
                        " FROM predictions WHERE ticker = ?",
                        (ticker,),
                    ).fetchone()
                if _hv_row:
                    if _hv_row[0]:
                        hourly_var = _hv_row[0]
                    hourly_cond_type = _hv_row[1]
                    hourly_threshold_lo = _hv_row[2]
                    hourly_threshold_hi = _hv_row[3]
            except Exception:
                pass
            station = _station_for_city(city)
            if not station:
                return False
            actual_value = _fetch_asos_hour_temp(station, target_date, hour, city_tz=tz)
            if actual_value is None:
                return False
            with _conn() as con:
                cur = con.execute(
                    "UPDATE outcomes SET settled_value = ?, settled_var = ? WHERE ticker = ?",
                    (round(actual_value, 1), hourly_var, ticker),
                )
            if cur.rowcount < 1:
                _log.warning(
                    "audit_settlement[%s]: no matching outcomes row -- "
                    "settled_value not actually written",
                    ticker,
                )
                return False

            # ── Miami index cross-check (batch-52 item 4) ───────────────────
            # KXTEMPMIAH settles on the Kalshi Weather Index, not KMIA METAR
            # -- settled_value above is still METAR-sourced (unchanged, kept
            # consistent with the other 5 cities' write shape -- opus review
            # I-1: no production code actually reads outcomes.settled_value
            # for hourly today, so this is a schema-consistency choice, not
            # an active "existing use" being preserved), but for Miami
            # specifically we ALSO compare Kalshi's real settled_yes against
            # what the index would have said, since that's the market's
            # actual settlement source. Deliberately best-effort/log+alert
            # only (no new DB column) -- "record both index and METAR and
            # alert on disagreement" per batch-52's own item 4 wording, kept
            # proportionate to a rank-6 city (batch-52 "Key risks").
            # Never lets a failure here affect the return value below --
            # settled_value was already durably written above regardless.
            #
            # opus review M-4: neither this batch nor Kalshi's public docs
            # establish the EXACT settlement instant/aggregation KXTEMPMIAH
            # uses (index value at the top of the hour? a windowed
            # aggregate?) -- the 5-minute tolerance_min below and the
            # "near the target hour" framing in the alert text are a
            # reasonable approximation, not a confirmed match to Kalshi's
            # real methodology. A MISMATCH alert on this path should be
            # read as "the index disagrees with Kalshi near this hour,
            # investigate" -- not an automatic proof of a real settlement
            # error. Filed as its own backlog entry (search "Miami hourly
            # settlement-instant") pending either Kalshi documenting this
            # or empirical correlation once enough real settlements exist.
            if city == "Miami":
                try:
                    import zoneinfo as _zi_miami

                    from kalshi_weather_index import (
                        get_miami_index_reading_near as _index_near,
                    )

                    _target_local = datetime(
                        target_date.year,
                        target_date.month,
                        target_date.day,
                        hour,
                        tzinfo=_zi_miami.ZoneInfo(tz),
                    )
                    _target_epoch = _target_local.timestamp()
                    _client = _get_settlement_kalshi_client()
                    _index_reading = _index_near(
                        _client, _target_epoch, tolerance_min=5.0
                    )
                    if _index_reading is not None:

                        def _implied_yes(temp_f: float) -> bool | None:
                            if (
                                hourly_cond_type == "above"
                                and hourly_threshold_lo is not None
                            ):
                                return temp_f > hourly_threshold_lo
                            if (
                                hourly_cond_type == "below"
                                and hourly_threshold_lo is not None
                            ):
                                return temp_f < hourly_threshold_lo
                            if (
                                hourly_cond_type == "between"
                                and hourly_threshold_lo is not None
                                and hourly_threshold_hi is not None
                            ):
                                return (
                                    hourly_threshold_lo < temp_f < hourly_threshold_hi
                                )
                            return None

                        _index_yes = _implied_yes(_index_reading["temp_f"])
                        _metar_yes = _implied_yes(actual_value)
                        _log.info(
                            "audit_settlement[%s]: Miami index cross-check -- "
                            "Kalshi=%s index=%.1fF(status=%s,implied=%s) "
                            "metar=%.1fF(implied=%s)",
                            ticker,
                            "YES" if settled_yes else "NO",
                            _index_reading["temp_f"],
                            _index_reading.get("status"),
                            _index_yes,
                            actual_value,
                            _metar_yes,
                        )
                        # Only a "normal"-status index point disagreeing with
                        # Kalshi's real settlement is alert-worthy -- a
                        # "degraded" point disagreeing isn't strong evidence
                        # of anything (batch-52's explicit fail-toward-no-
                        # lock-in mandate: don't trust a degraded reading).
                        if (
                            _index_yes is not None
                            and _index_yes != settled_yes
                            and _index_reading.get("status") == "normal"
                        ):
                            _log.warning(
                                "settlement_audit MISMATCH (Miami index) %s — "
                                "Kalshi=%s index=%.1fF implied=%s",
                                ticker,
                                "YES" if settled_yes else "NO",
                                _index_reading["temp_f"],
                                _index_yes,
                            )
                            mark_outcome_disputed(ticker)
                            try:
                                import notify as _notify_miami

                                _notify_miami.send_system_alert(
                                    "⚠ Miami hourly settlement disagrees with index",
                                    f"{ticker}: Kalshi settled "
                                    f"{'YES' if settled_yes else 'NO'}, but the "
                                    f"Kalshi Weather Index read "
                                    f"{_index_reading['temp_f']:.1f}F "
                                    f"(implied {_index_yes}) near the target "
                                    "hour. NOTE: the exact settlement "
                                    "instant/aggregation Kalshi uses isn't "
                                    "confirmed -- this could be a real "
                                    "threshold/index-parsing bug, or just "
                                    "this tolerance window sampling a "
                                    "different instant than Kalshi's real "
                                    "settlement. Re-verify before assuming "
                                    "either.",
                                    cooldown_key="miami_index_settlement_mismatch",
                                    discord_color=0xF85149,
                                )
                            except Exception as _n_exc:
                                _log.warning(
                                    "audit_settlement[%s]: Miami mismatch "
                                    "notification failed: %s",
                                    ticker,
                                    _n_exc,
                                )
                        elif (
                            _index_yes is not None
                            and _index_yes == settled_yes
                            and _index_reading.get("status") == "normal"
                        ):
                            # opus review M-3: mirror the daily branch's own
                            # mark_outcome_undisputed precedent -- without
                            # this, a ticker that mismatched once (e.g. off
                            # a stale/edge-case index point) stays
                            # permanently excluded from outcomes_valid/
                            # Brier/calibration scoring even after a later
                            # confirmed agreement, silently shrinking both
                            # the calibration pool and the hourly gate's own
                            # settled-sample count for no ongoing reason.
                            # Idempotent no-op if this ticker was never
                            # disputed in the first place.
                            mark_outcome_undisputed(ticker)
                    else:
                        _log.debug(
                            "audit_settlement[%s]: no Miami index reading "
                            "near target hour -- skipping index cross-check",
                            ticker,
                        )
                except Exception as _idx_exc:
                    _log.debug(
                        "audit_settlement[%s]: Miami index cross-check "
                        "failed (non-fatal): %s",
                        ticker,
                        _idx_exc,
                    )

            return True

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

        # Guard dropped from the old var-derivation block along with it: that
        # block's own `else: return False` for a cond_type outside
        # above/below/between wasn't just about deriving a var -- it was also
        # the only thing stopping a non-single-temperature-value market
        # (e.g. a future daily precip series) from writing a Fahrenheit
        # figure into settled_temp_f. Restored explicitly here so this
        # branch stays daily-temperature-only regardless of what future
        # ticker types reach it (opus-review-caught, 2026-08-10).
        if cond_type not in ("above", "below", "between"):
            return False

        # Read Kalshi's own settled figure directly (backlog.txt "DATA-DRIVEN
        # SIGMA FROM SETTLED HISTORY + CLI-REPORT SETTLEMENT FETCH", finding
        # F1) instead of deriving one from the ASOS raw-METAR proxy this
        # branch used before 2026-08-10 -- see this function's docstring for
        # why that proxy could legitimately disagree with Kalshi's real
        # CLI-report-based settlement by ~1 degree near a threshold.
        # expiration_value is populated identically across every strike in a
        # daily HIGH/LOW event (live-verified 2026-08-09/2026-08-10,
        # including a same-event cross-strike check on a LOW-series market),
        # so unlike the old ASOS path this needs no HIGH/LOW (var)
        # derivation at all -- the settled value applies regardless of which
        # threshold this particular ticker trades.
        try:
            client = _get_settlement_kalshi_client()
            market = client.get_market(ticker)
        except Exception as exc:
            _log.warning(
                "audit_settlement[%s]: daily market fetch failed: %s", ticker, exc
            )
            return False
        if market.get("status") != "finalized":
            return False
        exp_val = market.get("expiration_value")
        if exp_val is None:
            _log.warning(
                "audit_settlement[%s]: finalized but no expiration_value", ticker
            )
            return False
        try:
            actual = float(exp_val)
        except (TypeError, ValueError):
            _log.warning(
                "audit_settlement[%s]: non-numeric expiration_value=%r",
                ticker,
                exp_val,
            )
            return False
        source = "Kalshi:expiration_value"

        # Store the settled temperature so we can compute empirical NWS forecast
        # error distributions per city — the foundation for data-driven sigma
        # calibration that will replace the current hardcoded sigma values.
        with _conn() as con:
            cur = con.execute(
                "UPDATE outcomes SET settled_temp_f = ? WHERE ticker = ?",
                (round(actual, 1), ticker),
            )
        if cur.rowcount < 1:
            _log.warning(
                "audit_settlement[%s]: no matching outcomes row -- "
                "settled_temp_f not actually written",
                ticker,
            )
            return False
        _log.debug(
            "settlement_audit: stored settled temp %.1f°F for %s", actual, ticker
        )

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
            # actual is Kalshi's own settled figure (expiration_value), so unlike
            # the old ASOS-proxy days a mismatch here means OUR condition/threshold
            # parsing (cond_type + threshold_desc, logged below) disagrees with
            # Kalshi's real settlement -- worth investigating as a real parsing bug,
            # not proxy/CLI-report noise. See this function's docstring.
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
            # A ticker disputed under the old ASOS-proxy comparison that now
            # agrees against Kalshi's own settled figure was flagged for a
            # reason since proven unreliable (opus-review-caught, 2026-08-10)
            # -- clear it rather than leave it permanently excluded from
            # outcomes_valid. No-op if it was never disputed.
            mark_outcome_undisputed(ticker)
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

    # ZoneInfo(tz), not utc_today(): target_date is CITY-LOCAL (the same
    # value analyze_trade's days_out computation uses post-0100bffe), so
    # "today" for this arithmetic must be too, mirroring
    # _fetch_previous_run_leads's identical fix below (AUD-0044). Falls
    # back to UTC on ZoneInfo failure.
    #
    # Opus-review-noted: mos.py's _local_or_utc_today(tz) already implements
    # this identical local-today/UTC-fallback pattern -- deliberately not
    # extracted into a shared helper here since mos.py is outside this
    # batch's file scope (main.py/tracker.py/web_app.py); worth consolidating
    # in a future pass across all five sites that now duplicate it.
    try:
        from zoneinfo import ZoneInfo as _ZoneInfoPrd

        _today_prd = datetime.now(_ZoneInfoPrd(tz)).date()
    except Exception:
        _log.warning(
            "_fetch_previous_run_daily: ZoneInfo unavailable for tz=%s — "
            "falling back to UTC date",
            tz,
        )
        _today_prd = _utc_today()
    past_days = (_today_prd - target_date).days
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
    # ZoneInfo(tz), not utc_today(): target_date is CITY-LOCAL (see
    # analyze_trade's own days_out computation, which post-0100bffe compares
    # against a ZoneInfo-derived local today, not datetime.now(UTC)) -- a
    # server running ahead of the city's own offset would otherwise
    # under-count forecast_days by 1 and could miss the boundary day
    # (AUD-0044). Falls back to UTC on ZoneInfo failure.
    try:
        from zoneinfo import ZoneInfo as _ZoneInfoPrl

        _today_prl = datetime.now(_ZoneInfoPrl(tz)).date()
    except Exception:
        _log.warning(
            "_fetch_previous_run_leads: ZoneInfo unavailable for tz=%s — "
            "falling back to UTC date",
            tz,
        )
        _today_prl = _utc_today()
    forecast_days = max(1, (target_date - _today_prl).days + 1)
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
    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 (review-caught):
    # KXRAIN*M rows never write settled_temp_f (they write settled_value
    # instead) -- without this exclusion, every rain outcome permanently
    # satisfies "settled_temp_f IS NULL" and gets re-selected/re-fetched
    # from Kalshi on every non-force backfill run forever, growing with
    # rain-history size. Idempotent (not a correctness bug), just wasted
    # API calls and an inflated settled_temp_filled count that never
    # actually filled anything. Snow Step 2 (review-caught the identical
    # gap): KXDENSNOWM* rows have the exact same shape (settled_value, not
    # settled_temp_f) -- excluded the same way.
    from weather_markets import (
        _KXRAIN_MONTHLY_CITY,
        _KXSNOW_MONTHLY_CITY,
        _var_from_ticker_prefix,
    )

    with _conn() as con:
        if force:
            temp_rows = con.execute(
                "SELECT o.ticker, o.settled_yes FROM outcomes o"
            ).fetchall()
        else:
            _monthly_prefixes = tuple(_KXRAIN_MONTHLY_CITY) + tuple(
                _KXSNOW_MONTHLY_CITY
            )
            _exclude_sql = " AND ".join(
                ["o.ticker NOT LIKE ?"] * len(_monthly_prefixes)
            )
            temp_rows = con.execute(
                "SELECT o.ticker, o.settled_yes FROM outcomes o "
                f"WHERE o.settled_temp_f IS NULL AND ({_exclude_sql})",
                tuple(f"{p}%" for p in _monthly_prefixes),
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
            SELECT DISTINCT p.ticker, p.city, p.market_date, p.condition_type, p.days_out, p.var
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

        # Prefer the var stored on the prediction itself (backlog.txt
        # "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff item 2, the
        # var-derivation root-cause fix). This loop is filtered to days_out
        # >= 1 above, so it can never actually reach an hourly (always
        # days_out=0) row today -- fixed anyway so this site can't
        # independently drift from the others if that filter ever changes.
        var = row["var"]
        if var is None:
            # Determine which temperature variable from the MARKET TYPE, not the
            # condition (above/below/between).  KXHIGH markets measure the daily
            # high; KXLOWT markets measure the daily low.  Condition type only says
            # which side of the threshold the bet is on — it must not override this.
            ticker_upper = ticker.upper()
            var = (
                _var_from_ticker_prefix(ticker_upper) or "max"
            )  # between markets default to high temperature

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


# Kalshi's candlesticks endpoint accepts 1/60/1440 (minutes). Hourly, not
# 1-minute: weather markets can stay open several days (see MAX_DAYS_OUT),
# and 1-minute resolution over a multi-day window risks silently truncating
# on the candlesticks endpoint's per-request period cap (see the original
# HISTORICAL MARKET-PRICE CAPTURE backlog entry). Named once here — passed
# to both client.get_candlesticks() and log_price_candles() in both
# sync_outcomes() and backfill_price_history() — so it can't silently drift
# between the fetch call and the stored value (which would corrupt the
# (ticker, period_interval, end_period_ts) dedup index).
_CANDLE_PERIOD_MINUTES = 60


def _derive_series_ticker(market: dict, ticker: str) -> str:
    """A real client.get_market() response has no "series_ticker" field at
    all (confirmed live 2026-07-25 — the real keys are event_ticker/ticker/
    etc., never series_ticker) — so this always falls back to the ticker's
    own prefix in practice today. Kept market.get("series_ticker") as the
    first-preference source only in case a future/different response shape
    ever does carry a real value. The fallback mirrors consistency.py's
    _group_markets() own established derivation for this identical gap
    (confirmed a market's real series ticker is always
    ticker.split("-")[0] and a member of KNOWN_WEATHER_SERIES).

    DO NOT copy this same fallback into consistency.py's _parse_threshold()
    (its own separate, unrelated market.get("series_ticker") read) — that
    function uses the string "HIGH"/"LOW" substring of series_ticker as an
    above/below direction signal, and since it's currently always empty in
    practice (the same reason this function exists), adding this fallback
    there would make it start firing on the wrong branch: some real ladders
    put a LOW-condition market under a KXHIGH*-prefixed series and vice
    versa (e.g. "will the minimum temp be >N" can live in a series whose
    ticker prefix reads HIGH), confirmed live — that function's existing
    title-text fallback (used exactly because the field is always empty
    today) is correct as-is and must stay the primary path there, not this
    one, which is only safe for candlestick backfill's own use.
    """
    return market.get("series_ticker") or ticker.split("-")[0]


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
                        # See _derive_series_ticker's own docstring for why
                        # this always falls back to the ticker prefix in
                        # practice — this guard silently no-op'd (no
                        # exception, so no warning either) for every
                        # settlement since this backfill shipped 2026-07-12
                        # until that fallback was added 2026-07-25, confirmed
                        # via bot.log having zero candlestick-related lines
                        # ever and price_history being completely empty while
                        # the sibling trade-history backfill right below
                        # (which never needed series_ticker) has 20,000+
                        # real rows.
                        _candle_series = _derive_series_ticker(market, ticker)
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
                                period_interval=_CANDLE_PERIOD_MINUTES,
                            )
                            log_price_candles(
                                ticker,
                                _candle_series,
                                _CANDLE_PERIOD_MINUTES,
                                _candles,
                            )
                    except Exception as _candle_exc:
                        _log.warning(
                            "sync_outcomes: price-history backfill failed for %s: %s",
                            ticker,
                            _candle_exc,
                        )
                    # Backfill public trade-flow history (direction/taker info
                    # that OHLC candles above lack) for this now-settled market
                    # in one call -- same "fires exactly once per market, never
                    # blocks outcome recording" pattern as the candlestick
                    # backfill immediately above (backlog.txt "PUBLIC TRADES
                    # REST BACKFILL").
                    try:
                        _trade_open_str = market.get("open_time")
                        if _trade_open_str:
                            _trade_start = datetime.fromisoformat(
                                _trade_open_str.replace("Z", "+00:00")
                            )
                            _trade_end = (
                                datetime.fromisoformat(
                                    close_time_str.replace("Z", "+00:00")
                                )
                                if close_time_str
                                else now_utc
                            )
                            _trades = client.get_trades(
                                ticker,
                                int(_trade_start.timestamp()),
                                int(_trade_end.timestamp()),
                            )
                            log_trades(ticker, _trades)
                    except Exception as _trade_exc:
                        _log.warning(
                            "sync_outcomes: trade-history backfill failed for %s: %s",
                            ticker,
                            _trade_exc,
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


def backfill_price_history(client) -> tuple[int, int]:
    """One-off recovery pass for price_history rows lost to the real
    series_ticker bug (see sync_outcomes' candlestick-backfill block,
    fixed 2026-07-25): sync_outcomes only ever backfills candlesticks for a
    ticker the FIRST time it settles (once an outcomes row exists, that
    ticker is never revisited), so the code fix alone does not recover data
    for tickers that already settled under the broken guard — confirmed
    live 2026-07-25 that price_history had 0 rows total (vs 20,000+ in the
    sibling trade_history table, which never needed series_ticker and so
    was never affected).

    Finds every settled ticker with zero price_history rows and re-runs the
    exact same client.get_market()/get_candlesticks()/log_price_candles()
    sequence sync_outcomes' own (now-fixed) block uses. Safe to re-run —
    already-filled tickers are skipped by the query, no force flag needed
    (unlike backfill_emos_data, there's no "re-verify even already-filled
    rows" use case here: a market's OHLC history never changes once the
    market has closed).

    Deliberately joins the raw outcomes table, not outcomes_valid — matches
    sync_outcomes' own candlestick block, which never checked `disputed`
    either (audit_settlement, the only writer of that flag, runs before the
    candlestick block but the block itself has no disputed check). A
    disputed label means the SETTLEMENT is contested, not that the raw
    market PRICE data is untrustworthy — price_history is microstructure,
    never joined into any Brier/calibration query, so there's no scoring
    risk from including a disputed ticker's candles the way there would be
    for a settled_yes-derived signal. See tests/test_disputed_row_guard.py's
    allowlist entry for this function.

    Returns (filled, failed) — filled counts a ticker where at least one
    real candle row was actually written (not just "the API call didn't
    raise" — a ticker whose candles are genuinely unavailable, e.g. past
    the endpoint's retention window, calls cleanly and returns an empty
    list, which must NOT count as filled or it would silently stop being
    retried on a future run despite writing nothing). failed counts a
    genuine per-ticker exception (get_market/get_candlesticks erroring) —
    logged and skipped, matching sync_outcomes' own isolated-per-ticker-
    failure discipline so one bad ticker can't abort the whole pass, but
    tracked separately so a systemic failure (bad credentials, an API
    outage) is visibly distinguishable from "nothing left to do" rather
    than both reading as "0 filled".
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT o.ticker
            FROM outcomes o
            LEFT JOIN (SELECT DISTINCT ticker FROM price_history) ph
              ON ph.ticker = o.ticker
            WHERE ph.ticker IS NULL
            """
        ).fetchall()

    filled = 0
    failed = 0
    for row in rows:
        ticker = row["ticker"]
        try:
            market = client.get_market(ticker)
        except Exception as exc:
            _log.warning(
                "backfill_price_history: get_market failed for %s: %s", ticker, exc
            )
            failed += 1
            continue
        open_str = market.get("open_time")
        if not open_str:
            continue
        close_str = market.get("close_time")
        series = _derive_series_ticker(market, ticker)
        try:
            start = datetime.fromisoformat(open_str.replace("Z", "+00:00"))
            end = (
                datetime.fromisoformat(close_str.replace("Z", "+00:00"))
                if close_str
                else datetime.now(UTC)
            )
            candles = client.get_candlesticks(
                series,
                ticker,
                int(start.timestamp()),
                int(end.timestamp()),
                period_interval=_CANDLE_PERIOD_MINUTES,
            )
            written = log_price_candles(ticker, series, _CANDLE_PERIOD_MINUTES, candles)
            if written > 0:
                filled += 1
        except Exception as exc:
            _log.warning(
                "backfill_price_history: candlestick backfill failed for %s: %s",
                ticker,
                exc,
            )
            failed += 1
    return filled, failed


def backfill_daily_temp_settlement() -> tuple[int, int]:
    """One-off recovery pass for outcomes.settled_temp_f rows written by
    audit_settlement()'s now-replaced ASOS-proxy daily HIGH/LOW branch
    (backlog.txt "DATA-DRIVEN SIGMA FROM SETTLED HISTORY + CLI-REPORT
    SETTLEMENT FETCH", finding F1 in docs/feature-scan-2026-08-09.md):
    audit_settlement()'s daily branch now reads Kalshi's own
    expiration_value directly instead of deriving a proxy figure from the
    IEM ASOS raw-METAR archive (see that function's docstring), but the
    code fix alone does not correct rows that already settled under the
    old proxy value -- confirmed live 2026-07-05 that the proxy and
    Kalshi's real CLI-report settlement can legitimately disagree by ~1
    degree near a threshold.

    settled_temp_f has exactly one production writer -- audit_settlement's
    daily branch (the hourly branch writes settled_value/settled_var; the
    monthly rain/snow branches write settled_value) -- so "settled_temp_f
    IS NOT NULL" is definitionally "written by that branch." No ticker
    prefix/series filter is needed, unlike backfill_emos_data's non-force
    Part 1 (which excludes monthly rain/snow tickers only to avoid an
    unrelated always-NULL re-fetch-forever wrinkle that doesn't apply here).

    Unlike backfill_price_history (which fills rows with ZERO existing
    data), every row targeted here already has a value -- the fix is
    correcting it, not filling a gap. Re-runs audit_settlement() for each:
    safe and idempotent, since that function's write is an unconditional
    UPDATE regardless of the column's current value. No client parameter
    is needed (unlike backfill_price_history) -- audit_settlement() builds
    its own client via _get_settlement_kalshi_client().

    Returns (corrected, failed). corrected counts a ticker where
    audit_settlement() returned True (settled_temp_f actually rewritten
    from Kalshi's own settlement). failed counts one where it returned
    False (market not yet finalized, fetch error, missing/non-numeric
    expiration_value, etc.) -- left with its prior, possibly still
    proxy-derived, value untouched; safe to retry on a future run.
    Deliberately joins the raw outcomes table, not outcomes_valid, matching
    backfill_price_history's and backfill_emos_data's own reasoning -- a
    column-repair utility corrects data regardless of the row's dispute
    status; that status is a downstream calibration-query concern.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT ticker, settled_yes FROM outcomes WHERE settled_temp_f IS NOT NULL"
        ).fetchall()

    corrected = 0
    failed = 0
    for row in rows:
        ticker = row["ticker"]
        try:
            ok = audit_settlement(ticker, bool(row["settled_yes"]))
        except Exception as exc:
            _log.warning(
                "backfill_daily_temp_settlement: audit_settlement failed for %s: %s",
                ticker,
                exc,
            )
            ok = False
        if ok:
            corrected += 1
        else:
            failed += 1
    return corrected, failed


def backfill_ensemble_member_scores_var() -> tuple[int, int, int]:
    """One-off recovery pass for ensemble_member_scores rows logged before
    log_member_score() call sites started passing var= (see that function's
    docstring: "must not be pooled"). Every row with var IS NULL predates
    that change and can't be weighted or bias-corrected per max-vs-min
    without it.

    Recovers var from tracker.predictions, which already records ticker and
    city per forecast -- joined here via (city, market_date), since
    ensemble_member_scores itself has no ticker column. var is derived from
    the ticker via weather_markets._var_from_ticker_prefix() (the
    codebase-wide single source of truth for this check -- see backlog.txt
    "VAR-CONVENTION LITERAL HAND-COPIED ACROSS 7+ FILES") rather than read
    from predictions.var directly, since that column is independently NULL
    for many of the same historical rows. Validated live against every
    predictions row where var IS already populated: 0 mismatches across 67
    checked.

    A (city, market_date) pair whose predictions span more than one
    distinct KXHIGH/KXLOW prefix (both a high and a low market traded that
    city that day, the common case) is left unresolved rather than guessed
    at -- ensemble_member_scores has no ticker to disambiguate against.
    Matching actual_temp against outcomes.settled_temp_f was tried as a
    tiebreaker and never actually resolved a real ambiguous case in this
    data, so it isn't relied on here. A pair with zero matching predictions
    (no coverage that far back) is also left unresolved.

    Known limitation (review-caught, 2026-08-13, low severity): an hourly
    KXTEMPxxxH ticker has no HIGH/LOW substring, so _var_from_ticker_prefix
    returns None for it and it never contributes a candidate var here --
    meaning a (city, market_date) with an hourly ticker and a genuine
    KXLOW ticker (no KXHIGH) would resolve "unambiguously" to min, even if
    the specific row being backfilled actually came from the hourly
    market, which paper.py's own fallback treats as max by convention
    (see its _update_station_bias_from_settlement docstring). This can't
    be resolved from ensemble_member_scores alone -- it has no ticker of
    its own to say which specific market a row's forecast was for. Checked
    against live data: the one city/date combination with both an hourly
    and a daily ticker (NYC, 2026-07-24: KXHIGHNY-26JUL24-T81 +
    KXTEMPNYCH-26JUL2406-T65.99) has no KXLOW ticker that day, so it
    resolves cleanly to max with no ambiguity -- this gap isn't hit by any
    row in the current data, but a future city/date with an hourly ticker
    alongside a KXLOW (and no KXHIGH) would silently mis-resolve.

    A resolved var can also collide with idx_ems_dedup (city, model,
    target_date, var) -- pre-existing duplicate rows that share (city,
    model, target_date) survive today only because SQLite treats their NULL
    var as distinct; assigning them the SAME resolved var would violate
    that unique index. Caught per-row (not left to abort the whole
    transaction -- a naive version of this function did exactly that on
    real data: 18 such collisions existed live, and letting one
    IntegrityError propagate out of the `with _conn()` block rolled back
    every already-applied update in the same run, backfilling zero rows).
    Left NULL and counted separately from unresolved -- these rows aren't
    missing information, they're a genuine pre-existing data-duplication
    issue (both rows already double-count that city/date/model in
    get_member_accuracy()/get_member_bias() while NULL) that this backfill
    isn't the place to silently resolve by picking one to delete.

    Safe to re-run -- only ever touches rows still NULL.

    Returns (updated, unresolved, duplicate_conflict).
    """
    from weather_markets import _var_from_ticker_prefix

    init_db()
    with _conn() as con:
        null_rows = con.execute(
            "SELECT id, city, target_date FROM ensemble_member_scores WHERE var IS NULL"
        ).fetchall()

        updated = 0
        unresolved = 0
        duplicate_conflict = 0
        for row in null_rows:
            tickers = con.execute(
                "SELECT DISTINCT ticker FROM predictions WHERE city = ? AND market_date = ?",
                (row["city"], row["target_date"]),
            ).fetchall()
            candidate_vars = {
                v
                for (ticker,) in tickers
                if (v := _var_from_ticker_prefix(ticker.upper())) is not None
            }
            if len(candidate_vars) != 1:
                unresolved += 1
                continue
            try:
                con.execute(
                    "UPDATE ensemble_member_scores SET var = ? WHERE id = ?",
                    (candidate_vars.pop(), row["id"]),
                )
                updated += 1
            except sqlite3.IntegrityError:
                duplicate_conflict += 1
    return updated, unresolved, duplicate_conflict


def backfill_member_brier(trades: list[dict]) -> tuple[int, int, int]:
    """One-off recovery pass to populate implied_prob/brier on existing
    ensemble_member_scores rows, for trades settled before those columns
    existed (or before this backfill has been run once against history).
    Feeds get_member_brier(), which weather_markets.scan_member_quarantine()
    uses as its detection statistic.

    ensemble_member_scores has no ticker column (see log_member_score()'s
    docstring), so this can't iterate that table directly -- instead it
    takes paper trade records as a param (mirroring get_stop_loss_accuracy's
    paper-data-passed-in pattern, since tracker.py deliberately never
    imports paper) and joins ticker->condition_type/settled_temp_f the same
    way paper._score_ensemble_members does live.

    Not cron-wired -- meant to be run once manually (see
    main.cmd_backfill_member_brier) after implied_prob/brier logging has
    shipped, to avoid a 1-2 week cold start before the quarantine mechanism
    has enough Brier data. Safe to re-run: the UPDATE only ever touches rows
    where brier IS NULL, so already-backfilled rows are left alone.

    Scope: paper trades only. No evidence execution_log (live trades)
    carries model_forecast_means/condition_threshold in the same shape.

    Returns (updated, skipped, errored):
      - updated: number of ensemble_member_scores rows that got
        implied_prob/brier set (one per model per trade)
      - skipped: trades with no resolvable condition_type/threshold/
        settled_temp_f -- soft degradation, same eligibility bar as the
        live _score_ensemble_members path
      - errored: trades that raised while computing (malformed record
        shape) -- counted and skipped rather than aborting the whole batch
    """
    import datetime as _dt

    from weather_markets import (
        _CITY_TZ,
        _time_risk,
        _var_from_ticker_prefix,
        gaussian_probability,
        get_historical_sigma,
    )

    init_db()
    updated = 0
    skipped = 0
    errored = 0
    with _conn() as con:
        for trade in trades:
            try:
                if not trade.get("settled"):
                    skipped += 1
                    continue
                model_means = trade.get("model_forecast_means") or {}
                if not model_means:
                    skipped += 1
                    continue
                ticker = trade.get("ticker", "")
                city = trade.get("city")
                target_date = trade.get("target_date")
                raw_threshold = trade.get("condition_threshold")
                outcome = trade.get("outcome")
                if (
                    not city
                    or not target_date
                    or raw_threshold is None
                    or outcome not in ("yes", "no")
                ):
                    skipped += 1
                    continue
                var = (
                    trade.get("var") or _var_from_ticker_prefix(ticker.upper()) or "max"
                )

                row = con.execute(
                    "SELECT settled_temp_f FROM outcomes_valid WHERE ticker = ?",
                    (ticker,),
                ).fetchone()
                if row is None or row[0] is None:
                    skipped += 1
                    continue

                pred_row = con.execute(
                    "SELECT condition_type FROM predictions WHERE ticker = ? "
                    "ORDER BY predicted_at DESC LIMIT 1",
                    (ticker,),
                ).fetchone()
                condition_type = pred_row[0] if pred_row else None
                if condition_type not in ("above", "below"):
                    skipped += 1
                    continue

                # See paper._score_ensemble_members()'s matching comment:
                # must use the same continuous decision boundary (+/-0.5,
                # not the raw ticker threshold) and the same as-of-entry
                # sigma_mult horizon discount as the live engine, or this
                # backfill would silently diverge from what the live path
                # produces for the same trade.
                prob_threshold = (
                    raw_threshold + 0.5
                    if condition_type == "above"
                    else raw_threshold - 0.5
                )
                tz = _CITY_TZ.get(city, "America/New_York")
                entered_at_str = trade.get("entered_at")
                as_of = (
                    _dt.datetime.fromisoformat(entered_at_str.replace("Z", "+00:00"))
                    if entered_at_str
                    else None
                )
                _, sigma_mult = _time_risk(trade.get("close_time", ""), tz, now=as_of)
                month = _dt.date.fromisoformat(target_date).month
                sigma = get_historical_sigma(city, month, var) * sigma_mult
                outcome_yes = 1.0 if outcome == "yes" else 0.0

                for model, predicted_temp in model_means.items():
                    if predicted_temp is None:
                        continue
                    implied_prob = gaussian_probability(
                        predicted_temp, prob_threshold, sigma, condition_type
                    )
                    brier = (implied_prob - outcome_yes) ** 2
                    cur = con.execute(
                        "UPDATE ensemble_member_scores SET implied_prob = ?, brier = ? "
                        "WHERE city = ? AND model = ? AND target_date = ? AND var = ? "
                        "AND brier IS NULL",
                        (implied_prob, brier, city, model, target_date, var),
                    )
                    updated += cur.rowcount
            except Exception as exc:
                errored += 1
                _log.debug(
                    "backfill_member_brier: errored on trade %s: %s",
                    trade.get("ticker", "?"),
                    exc,
                )
    return updated, skipped, errored


def log_member_score(
    city: str,
    model: str,
    predicted_temp: float,
    actual_temp: float,
    target_date_str: str,
    var: str | None = None,
    implied_prob: float | None = None,
    brier: float | None = None,
) -> None:
    """Log an ensemble member's temperature prediction vs actuals for accuracy tracking.

    var should be "max" for daily-HIGH markets or "min" for daily-LOW markets —
    daily-high and daily-low forecast errors have different sign/magnitude and
    must not be pooled (see get_dynamic_station_bias).

    implied_prob/brier are optional: the model's own forecast converted to a
    calibrated probability against the trade's market threshold, and the
    resulting Brier score vs the real outcome. Only populated when the
    caller has a resolvable condition_type/threshold for this settlement
    (see paper._score_ensemble_members) -- feeds get_member_brier().

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
              (city, model, predicted_temp, actual_temp, target_date, var,
               implied_prob, brier, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                city,
                model,
                predicted_temp,
                actual_temp,
                target_date_str,
                var,
                implied_prob,
                brier,
            ),
        )


def get_member_accuracy(days_back: int = 60) -> dict:
    """
    Per-model MAE filtered to recent predictions, used by learn_seasonal_weights().
    Returns {model: {mae: float, n: int, std: float, city_breakdown: {city: mae},
    city_n_breakdown: {city: n}}}

    std is the sample stdev (ddof=1) of the per-observation absolute errors --
    used by weather_markets.scan_member_quarantine() to compute the standard
    error of a model's own MAE estimate (std / sqrt(n)) for its peer-relative
    drift check.
    """
    import statistics as _stats

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
        # Sample stdev (ddof=1), the conventional choice for a standard-error
        # calculation downstream (weather_markets.scan_member_quarantine's
        # std/sqrt(n)) -- population stdev would understate it slightly.
        std = _stats.stdev(errors) if len(errors) > 1 else 0.0
        city_errs: dict[str, list[float]] = {}
        for city, p, a in entries:
            city_errs.setdefault(city, []).append(abs(p - a))
        city_mae = {c: sum(v) / len(v) for c, v in city_errs.items()}
        result[model] = {
            "mae": round(mae, 4),
            "n": len(entries),
            "std": round(std, 4),
            "city_breakdown": {c: round(v, 4) for c, v in city_mae.items()},
            # R25: per-city observation counts so _weights_from_mae can gate on
            # sample size rather than number of distinct cities.
            "city_n_breakdown": {c: len(v) for c, v in city_errs.items()},
        }
    return result


def get_member_brier(days_back: int = 14) -> dict:
    """
    Per-model Brier score filtered to recent settlements, used by
    weather_markets.scan_member_quarantine() as the trade-relevant
    detection statistic (replacing get_member_accuracy's MAE).
    Returns {model: {brier: float, n: int, std: float, city_breakdown:
    {city: brier}, city_n_breakdown: {city: n}}}

    std is the sample stdev of the per-observation Brier scores -- used the
    same way get_member_accuracy's std is, for the peer-relative drift
    check's standard-error computation.
    """
    import statistics as _stats

    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model, city, brier
            FROM ensemble_member_scores
            WHERE brier IS NOT NULL
              AND model != 'blended'
              AND logged_at >= datetime('now', ? || ' days')
            """,
            (f"-{days_back}",),
        ).fetchall()

    if not rows:
        return {}

    by_model: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append((r["city"], r["brier"]))

    result: dict = {}
    for model, entries in by_model.items():
        scores = [b for _, b in entries]
        brier = sum(scores) / len(scores)
        std = _stats.stdev(scores) if len(scores) > 1 else 0.0
        city_scores: dict[str, list[float]] = {}
        for city, b in entries:
            city_scores.setdefault(city, []).append(b)
        city_brier = {c: sum(v) / len(v) for c, v in city_scores.items()}
        result[model] = {
            "brier": round(brier, 4),
            "n": len(entries),
            "std": round(std, 4),
            "city_breakdown": {c: round(v, 4) for c, v in city_brier.items()},
            "city_n_breakdown": {c: len(v) for c, v in city_scores.items()},
        }
    return result


def get_member_bias(days_back: int = 60) -> dict:
    """
    Per-model SIGNED bias (mean predicted - actual), split by var ("max"/
    "min"), used by weather_markets._model_bias() to bias-correct raw
    ensemble members before they enter the live blend.

    Unlike get_member_accuracy()'s MAE (which is pooled across var), bias
    must never be pooled across var -- a model's high-temp bias and
    low-temp bias can be similarly-sized but opposite-signed, and averaging
    them together produces a correction that's wrong for both (verified via
    leave-one-out backtest 2026-08-13: pooled bias-correction scored worse
    than no correction at all; var-split bias-correction was the only
    scheme tested that beat the uncorrected blend). Rows with var IS NULL
    (pre-backfill legacy rows -- see backfill_ensemble_member_scores_var)
    can't be attributed to either bucket and are excluded here, not folded
    into either one.

    Returns {model: {var: {bias, n, city_breakdown: {city: bias},
    city_n_breakdown: {city: n}}}}.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model, city, var, predicted_temp, actual_temp
            FROM ensemble_member_scores
            WHERE predicted_temp IS NOT NULL
              AND actual_temp IS NOT NULL
              AND var IS NOT NULL
              AND model != 'blended'
              AND logged_at >= datetime('now', ? || ' days')
            """,
            (f"-{days_back}",),
        ).fetchall()

    if not rows:
        return {}

    by_model_var: dict[tuple[str, str], list[tuple[str, float, float]]] = {}
    for r in rows:
        by_model_var.setdefault((r["model"], r["var"]), []).append(
            (r["city"], r["predicted_temp"], r["actual_temp"])
        )

    result: dict = {}
    for (model, var), entries in by_model_var.items():
        errors = [p - a for _, p, a in entries]
        bias = sum(errors) / len(errors)
        city_errs: dict[str, list[float]] = {}
        for city, p, a in entries:
            city_errs.setdefault(city, []).append(p - a)
        city_bias = {c: sum(v) / len(v) for c, v in city_errs.items()}
        result.setdefault(model, {})[var] = {
            "bias": round(bias, 4),
            "n": len(entries),
            "city_breakdown": {c: round(v, 4) for c, v in city_bias.items()},
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
    A model with fewer than 10 observations is excluded entirely (it has no
    trustworthy per-model error estimate yet) rather than flattening every
    OTHER model's already-earned differentiation to equal weight — fixed
    2026-07-23 (TRACK ECMWF FORECAST ACCURACY adjacency finding): the old
    "any thin model → equal weight for all" fallback meant onboarding a new,
    freshly-instrumented model (ecmwf_aifs025_ensemble) would have silently
    disabled icon/gfs's real learned differentiation for every city until
    ECMWF alone crossed the floor. A model that individually clears the
    floor keeps its real weight regardless of what other models are doing.

    Returns a dict summing to 1.0 over models that clear the floor, e.g.
    {'gfs': 0.42, 'ecmwf': 0.35, 'nbm': 0.23} — or {} if none do.
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

    # backlog.txt "GENERALIZED PER-MODEL ACCURACY TRACKING" Pass 2: models
    # tracked for accuracy but deliberately excluded from every live blend
    # weight computation (currently gem_global/ukmo_global_ensemble_20km)
    # must not enter the softmax below at all — including them would still
    # shift every OTHER model's normalized weight via the shared `total`
    # denominator even though their own weight is never directly consumed by
    # a blend. Also makes this function's only display consumer (main.py's
    # "Active model weights" line) honest — showing a weight for a model
    # that has zero real influence on the forecast would be misleading.
    from weather_markets import TRACKING_ONLY_MODEL_NAMES as _tracking_only

    by_model: dict[str, list[float]] = {}
    for r in rows:
        if r["model"] in _tracking_only:
            continue
        by_model.setdefault(r["model"], []).append(
            abs(r["predicted_temp"] - r["actual_temp"])
        )

    # Exclude any model below the observation floor — it has no vote, but
    # doesn't block the models that do.
    by_model = {
        m: errs for m, errs in by_model.items() if len(errs) >= MIN_OBSERVATIONS
    }
    if not by_model:
        return {}

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
    the official Kalshi settlement temperature (outcomes.settled_temp_f), not a
    live METAR read.

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
    import safe_io as _safe_io

    _safe_io.atomic_write_json(pins, _PINS_PATH)


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
    import safe_io as _safe_io

    _safe_io.atomic_write_json(retired, _RETIRED_PATH)


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
    # Bug C fix (backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2): store
    # real SQL NULL, not the literal 4-character string "None", when
    # target_date is None -- the old str(target_date) fallback wrote "None"
    # into the DB, which the ON CONFLICT(ticker, target_date) upsert key
    # would then treat as a real (colliding) value.
    target_str = (
        target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else (str(target_date) if target_date is not None else None)
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
        # Bug C fix (see log_analysis_attempt's matching comment): real NULL,
        # not the literal string "None", when td is None.
        target_str = (
            td.isoformat()
            if td is not None and hasattr(td, "isoformat")
            else (str(td) if td is not None else None)
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
    # Bug C fix (see log_analysis_attempt's matching comment): real NULL,
    # not the literal string "None", when target_date is None. SQL "= NULL"
    # never matches (even a NULL column) -- use "IS NULL" for that case.
    target_str = (
        target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else (str(target_date) if target_date is not None else None)
    )
    try:
        with _conn() as con:
            if target_str is None:
                cursor = con.execute(
                    "UPDATE analysis_attempts SET outcome=? WHERE ticker=? AND target_date IS NULL",
                    (outcome, ticker),
                )
            else:
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


def get_regional_recent_bias(
    city: str,
    var: str = "max",
    hours: int = 48,
    as_of: str | None = None,
) -> tuple[float, int]:
    """Correlation-weighted mean forecast error of CORRELATED cities' recent
    settlements (backlog.txt "CROSS-CITY RECENT-ERROR POOLING").

    Same sign convention as get_dynamic_station_bias: positive means those
    cities' models ran warm (forecast_temp_f - settled_temp_f > 0); caller
    would subtract this from the raw forecast the same way.

    Only considers cities in `city`'s paper._CORRELATED_CITY_GROUPS entry
    (paper.py holds the group/pair-correlation tables since they're also
    used for portfolio exposure caps; imported lazily here to avoid a
    module-load-order cycle, matching this file's existing lazy `from paper
    import ...` pattern). Each correlated city's rows are weighted by
    paper._CITY_PAIR_CORR (falling back to the same 0.10 default
    monte_carlo's Kelly covariance layer uses for an unlisted pair).

    var selects daily-HIGH ("max") vs daily-LOW ("min") markets via ticker
    substring, not the mostly-NULL predictions.var column (same reasoning as
    get_recent_city_correlations's own ticker-based split -- mixing HIGH and
    LOW temps in one error series would corrupt the mean by ~20-30F).

    hours: lookback window, applied to outcomes.settled_at (when the
    settlement was recorded), not the market's event date -- settlement
    lag is real (median ~1 day per live audit) and this is what "recent" as
    of scan time actually means for a caller.

    as_of: SQLite datetime()-compatible string (same 'YYYY-MM-DD HH:MM:SS'
    format predicted_at/settled_at are stored in -- NOT a Python
    isoformat(), which emits a 'T' separator that would silently break the
    string-lexicographic comparison SQLite's own datetime() performs
    internally against these columns). Defaults to 'now'. Lets a caller
    reconstruct a specific historical point in time without look-ahead
    (e.g. a backtest asking "what would this have returned right before
    city X's own prediction was logged"). Both settled_at and predicted_at
    are bounded by as_of -- the settled_at bound alone is sufficient today
    (a ticker is never re-predicted after it settles, so the latest
    predicted_at row is transitively capped by its own settlement time),
    but predicted_at is bounded explicitly too as defense-in-depth against
    a future backfill re-logging a prediction row post-settlement (opus
    review finding, 2026-07-23).

    Excludes disputed settlements via outcomes_valid, and only uses the
    latest-logged prediction row per ticker (a ticker can have one
    predictions row per day it was scanned) -- same ROW_NUMBER dedup
    pattern as get_edge_realization_by_city.

    Returns (weighted_mean_error, sample_count). (0.0, 0) when city has no
    correlated-group entry (e.g. Seattle, deliberately standalone) or no
    qualifying rows in the window.
    """
    from paper import _CITY_PAIR_CORR, _CORRELATED_CITY_GROUPS

    group = next((g for g in _CORRELATED_CITY_GROUPS if city in g), None)
    if not group:
        return 0.0, 0
    correlated_cities = sorted(group - {city})
    if not correlated_cities:
        return 0.0, 0

    init_db()
    as_of_expr = as_of if as_of else "now"
    ticker_pattern = "%HIGH%" if var == "max" else "%LOW%"
    placeholders = ",".join("?" for _ in correlated_cities)

    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT sub.city, sub.forecast_temp_f, o.settled_temp_f
            FROM (
                SELECT ticker, city, forecast_temp_f,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticker ORDER BY predicted_at DESC
                       ) as rn
                FROM predictions
                WHERE city IN ({placeholders})
                  AND forecast_temp_f IS NOT NULL
                  AND UPPER(ticker) LIKE ?
                  AND predicted_at <= datetime(?)
            ) sub
            JOIN outcomes_valid o ON o.ticker = sub.ticker
            WHERE sub.rn = 1
              AND o.settled_temp_f IS NOT NULL
              AND o.settled_at >= datetime(?, ?)
              AND o.settled_at <= datetime(?)
            """,
            (
                *correlated_cities,
                ticker_pattern,
                as_of_expr,
                as_of_expr,
                f"-{hours} hours",
                as_of_expr,
            ),
        ).fetchall()

    if not rows:
        return 0.0, 0

    # Only pool a source city's recent error if ITS OWN dynamic station-bias
    # correction has cleared the same count>=10 floor _get_combined_station_
    # bias() itself uses as the cutoff below which it stays 100% static-table
    # (dynamic_weight is 0 exactly at count==10, ramping to 100% dynamic only
    # by count>=50 -- "cleared the floor" here means "no longer purely static
    # fallback," not "already fully dynamic") (backlog.txt "CROSS-CITY
    # RECENT-ERROR POOLING" opus review,
    # 2026-08-22: a source city whose own bias correction is still thin can
    # carry a PERSISTENT residual from an unverified/miscalibrated static
    # table entry -- not the transient regime-driven anomaly this pooling is
    # meant to capture -- and that persistent residual would otherwise leak
    # into every correlated neighbour's lean every day, not just on days with
    # a genuine shared-regime signal. Concrete case this guards: Atlanta's
    # only correlated partner is Miami (paper.py _CORRELATED_CITY_GROUPS),
    # and Miami has a documented ~4.6°F persistent cold residual (utils.py
    # CITY_MIN_PROB_EDGE comment) that its own dynamic bias can't yet
    # override (too few samples) -- without this filter, Atlanta's lean would
    # equal Miami's stale residual on every call. Cached per distinct source
    # city within this call (not module-level) since it only needs to run
    # once per get_regional_recent_bias() call, not once per row.
    _maturity_cache: dict[str, bool] = {}

    def _source_city_bias_is_mature(row_city: str) -> bool:
        if row_city not in _maturity_cache:
            try:
                _, count = get_dynamic_station_bias(row_city, var, min_samples=10)
            except Exception:
                count = 0
            _maturity_cache[row_city] = count >= 10
        return _maturity_cache[row_city]

    weighted_sum = 0.0
    weight_total = 0.0
    n_used = 0
    for row_city, forecast_temp_f, settled_temp_f in rows:
        if not _source_city_bias_is_mature(row_city):
            continue
        error = float(forecast_temp_f) - float(settled_temp_f)
        weight = _CITY_PAIR_CORR.get(frozenset({city, row_city}), 0.10)
        weighted_sum += error * weight
        weight_total += weight
        n_used += 1

    if weight_total <= 0:
        return 0.0, 0

    return round(weighted_sum / weight_total, 4), n_used


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
