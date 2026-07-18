"""
Shared utilities used across the Kalshi weather trading modules.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC, date, datetime

from config import _paper_min_edge_default as _cfg_paper_min_edge_default


def utc_today() -> date:
    """Return the current UTC date. Use everywhere instead of date.today()."""
    return datetime.now(UTC).date()


def sql_normalize_iso_column(column: str) -> str:
    """Return a SQL expression normalizing a mixed-format timestamp column for comparison.

    Some rows in this codebase were written with Python's `datetime.now(UTC).isoformat()`
    ('T' separator, e.g. "2026-07-05T12:00:00+00:00"); others were written with SQLite's
    `datetime('now')` (space separator, e.g. "2026-07-05 12:00:00"). Python's ISO-T format
    sorts lexicographically *higher* than SQLite's at the position where they diverge, so
    comparing a raw mixed-format column against `datetime('now', ...)` silently corrupts
    date-range queries (H-20/H-21/H-22: this exact bug recurred independently in
    execution_log.py and tracker.py). Wrap the column in this expression before comparing
    it to a `datetime('now', ...)`-style cutoff, e.g.:
        f"{sql_normalize_iso_column('placed_at')} >= datetime('now', ?)"
    """
    return (
        f"strftime('%Y-%m-%d %H:%M:%S', replace(replace({column}, 'T', ' '), 'Z', ''))"
    )


def is_trading_paused() -> bool:
    """Single source of truth for the TRADING_PAUSED kill-switch.

    Was previously re-derived independently in cron.py, order_executor.py,
    main.py (x2), and web_app.py — each parsing the same env var with its own
    copy of the truthy-string tuple, which could silently drift out of sync.
    """
    return os.getenv("TRADING_PAUSED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def get_paper_min_edge() -> float:
    """Live-refreshed PAPER_MIN_EDGE — call this, not a frozen import, from any
    long-running process (main.py's `loop`, `watch`/`watch --auto`/`watch --auto
    --live`). Those hold this module in memory for their whole run (no re-import
    between cron cycles), so a plain module constant computed once at process
    start would never see a fresh walk-forward/param-sweep result the weekly
    cron-triggered jobs write mid-run — this function re-checks on every call
    (config._paper_min_edge_default's own cache is keyed on file mtime, not
    process lifetime, so this stays cheap when nothing on disk has changed).

    Must be <= 5% per system requirements (P1.3) — test_edge_threshold.py
    enforces this on the return value. config.py's BotConfig.paper_min_edge
    (dashboard display only) shows the raw, unclamped auto-tuned suggestion;
    this is the safety-clamped value that actually gates trade placement (see
    cron.py, order_executor.py), so the two can legitimately differ when tuning
    suggests something above 5%. Override via PAPER_MIN_EDGE env var (also
    honored inside _cfg_paper_min_edge_default, unclamped there).
    """
    return min(_cfg_paper_min_edge_default(), 0.05)


# ── Kalshi platform constant ──────────────────────────────────────────────────

# Fee Kalshi charges on a taker fill (an order that immediately crosses the
# book): fee = round_up(0.07 * C * P * (1-P)) per contract. 7% is the
# coefficient in that formula, not a flat 7% of winnings -- KALSHI_FEE_RATE is
# used here as a flat-fraction-of-winnings approximation, which is exact only
# when a real per-fill formula isn't being modeled directly. Override via
# KALSHI_FEE_RATE in .env.
KALSHI_FEE_RATE = float(os.getenv("KALSHI_FEE_RATE", "0.07"))

# Fee Kalshi charges on a maker fill (a resting limit order that isn't
# immediately matched): fee = round_up(M * 0.0175 * C * P * (1-P)) per
# contract, where M (the maker multiplier) DEFAULTS TO 0 for the general
# event-contract fee schedule -- verified 2026-07-12 directly against Kalshi's
# own fee schedule PDF (kalshi.com/docs/kalshi-fee-schedule.pdf, effective
# July 7, 2026). M is only nonzero (giving a real 25%-of-taker maker fee) for
# a specific list of ~50 non-standard series (sports/politics/entertainment,
# e.g. KXNFL*, KXNBA*, KXCPI, KXFED) -- this bot's weather markets
# (KXHIGH*/KXLOW*/KXRAIN*) are not on that list, so maker fee is genuinely
# $0 here, not an approximation. This bot's live/paper order placement is
# always a resting midpoint GTC limit order (maker) -- see
# order_executor.py's _place_live_order -- never a taker fill, so every
# Kelly/EV/P&L computation modeling this bot's own trades should use this
# rate, not KALSHI_FEE_RATE. Override via KALSHI_MAKER_FEE_RATE in .env.
KALSHI_MAKER_FEE_RATE = float(os.getenv("KALSHI_MAKER_FEE_RATE", "0.0"))

# Hard cap on Kelly fraction — applied in both weather_markets.py and paper.py.
# Operative production cap is 0.25 (quarter-Kelly ceiling). Override via
# KELLY_CAP env var — config.py's BotConfig.kelly_cap reads the same env var
# (for validate()/dashboard display) but previously had no effect on real
# sizing since this constant ignored the env var entirely.
KELLY_CAP: float = float(os.getenv("KELLY_CAP", "0.25"))

# Multiplier applied to KELLY_CAP for the higher ci_adjusted_kelly ceiling
# granted to consensus trades (weather_markets.py's temperature path: 0.33 at
# the current KELLY_CAP=0.25 default). Previously a bare 0.33 literal
# independent of KELLY_CAP, so tuning KELLY_CAP via .env silently left the
# consensus ceiling behind at the old value. Override via
# KELLY_CAP_CONSENSUS_MULT env var.
KELLY_CAP_CONSENSUS_MULT: float = float(os.getenv("KELLY_CAP_CONSENSUS_MULT", "1.32"))

# Max fraction of starting balance allowed on one city/date combo — paper.py's
# real city/date exposure gate. Override via MAX_CITY_DATE_EXPOSURE env var —
# config.py's BotConfig.max_city_date_exposure reads the same env var (for
# validate()/dashboard display) but previously had no effect on real sizing
# since paper.py hardcoded its own copy of this value, ignoring the env var
# entirely.
MAX_CITY_DATE_EXPOSURE: float = float(os.getenv("MAX_CITY_DATE_EXPOSURE", "0.25"))

# Settled-trade count gate before per-method Kelly multiplier activates
# (paper.py._method_kelly_multiplier) — separate from MIN_BRIER_SAMPLES (30)
# intentionally, since per-method Brier on small samples is noisier. Override
# via METHOD_KELLY_GATE env var — config.py's BotConfig.method_kelly_gate
# reads the same env var (for validate()/dashboard display) but previously
# had no effect on real gating since paper.py hardcoded its own copy of this
# value, ignoring the env var entirely.
METHOD_KELLY_GATE: float = float(os.getenv("METHOD_KELLY_GATE", "50.0"))

# Minimum guaranteed edge required before main.py auto-places an arbitrage
# violation. Override via MIN_ARB_EDGE env var — config.py's BotConfig.min_arb_edge
# reads the same env var (for validate()/dashboard display) but previously had
# no effect on real gating since main.py hardcoded its own copy of this value
# (0.05), ignoring both the env var and this field entirely.
MIN_ARB_EDGE: float = float(os.getenv("MIN_ARB_EDGE", "0.05"))

# Edge thresholds — override via .env
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.07"))  # minimum edge to show in analyze
# Paper trading uses a lower threshold to capture more signals for observation.
# See get_paper_min_edge() above — call that, not a module constant, so
# long-running processes (loop, watch --auto) see fresh tuning data mid-run.
# Minimum probability-delta edge (forecast_prob − market_prob) to place a trade.
# Filters out signals where ROI edge exists but probability conviction is low.
# 8pp = ~2× the 4pp ask/bid half-spread on a typical 50¢ Kalshi contract.
MIN_PROB_EDGE = float(os.getenv("MIN_PROB_EDGE", "0.08"))

# Per-city probability-edge overrides for high-variance markets.
# Dallas Brier (0.33) is worse than the naive baseline — requires stronger conviction.
CITY_MIN_PROB_EDGE: dict[str, float] = {"Dallas": 0.15}


def min_prob_edge_for_days_out(days_out: int) -> float:
    """Minimum probability-edge required based on market horizon.

    Further-out markets need higher conviction: the crowd has more time to
    reprice against us before settlement, and ensemble accuracy degrades
    with horizon. Thresholds derived from calibrated competitor benchmarks.

      days_out == 0 → 12pp  (same-day/METAR-locked: shares the day-1 floor —
                             not because the same rationale applies (METAR
                             probs don't degrade with repricing time), but
                             because live Brier data shows same-day and 1-2d
                             accuracy are statistically indistinguishable
                             (0.270 n=138 vs 0.269 n=93, checked 2026-07-12).
                             Revisit if get_brier_by_days_out()'s same_day
                             and 1-2d buckets diverge.)
      days_out == 1 → 12pp  (next-day: model is reasonably accurate)
      days_out == 2 → 15pp  (2-day: meaningful ensemble spread)
      days_out >= 3 → 18pp  (3-5 day: high uncertainty, demand strong edge)
    """
    if days_out <= 1:
        return 0.12
    if days_out == 2:
        return 0.15
    return 0.18


# Market divergence cap: don't bet heavily against the market.
# When our model disagrees with the market by >2.5× the market says, the market
# is right nearly every time — we're fighting better real-time information.
MAX_MARKET_DIVERGENCE_RATIO = (
    2.0  # tightened from 2.5 — don't bet when we see 2x market odds
)
# Don't bet when the market is highly confident against our position.
# Raised from 0.12 → 0.25: data shows 0/5 wins when market gave our bet <25% odds.
# When market prices an event at <25% (or >75%), it has been correct every time.
MIN_MARKET_PROB_TO_BET_WITH = 0.25

# Confidence-tiered edge thresholds
# HIGH: spread < 0.05 (models agree) → lower bar
# MODERATE: 0.05 ≤ spread < 0.15 → standard bar
# LOW: spread ≥ 0.15 (models disagree) → higher bar
_EDGE_TIERS: dict[str, dict[str, float]] = {
    "HIGH": {"paper": 0.05, "live": 0.08},
    "MODERATE": {"paper": 0.07, "live": 0.10},
    "LOW": {"paper": 0.10, "live": 0.15},
}


def classify_confidence_tier(spread: float) -> str:
    """Classify ensemble spread into HIGH, MODERATE, or LOW confidence tier."""
    if spread < 0.05:
        return "HIGH"
    if spread < 0.15:
        return "MODERATE"
    return "LOW"


def get_min_edge_for_confidence(spread: float, is_live: bool = False) -> float:
    """Return minimum edge required given ensemble spread and trading mode."""
    tier = classify_confidence_tier(spread)
    return _EDGE_TIERS[tier]["live" if is_live else "paper"]


STRONG_EDGE = float(
    os.getenv("STRONG_EDGE", "0.30")
)  # threshold for "STRONG BUY" label
DRIFT_TIGHTEN_EDGE = float(
    os.getenv("DRIFT_TIGHTEN_EDGE", "0.05")
)  # added to STRONG_EDGE when Brier drift is detected
MED_EDGE = float(
    os.getenv("MED_EDGE", "0.15")
)  # threshold for medium-confidence auto-trade tier
MAX_DAILY_SPEND = float(
    os.getenv("MAX_DAILY_SPEND", "500.0")
)  # max multi-day paper dollars auto-traded per day (days_out >= 1)
MAX_SAME_DAY_SPEND = float(
    os.getenv("MAX_SAME_DAY_SPEND", "500.0")
)  # max same-day paper dollars auto-traded per day (days_out == 0)
SAME_DAY_RESERVE_SLOTS = int(os.getenv("SAME_DAY_RESERVE_SLOTS", "0"))
# How many same-day slots to hold back before SAME_DAY_RESERVE_AFTER_HOUR_UTC. 0 = disabled.
SAME_DAY_RESERVE_AFTER_HOUR_UTC = int(
    os.getenv("SAME_DAY_RESERVE_AFTER_HOUR_UTC", "12")
)
# UTC hour at which reserved slots are released (0-23). Default 12 = noon UTC.
SAME_DAY_RESERVE_MIN_SAMPLES = int(os.getenv("SAME_DAY_RESERVE_MIN_SAMPLES", "150"))
# Minimum settled same-day trades required before reservation logic activates.
SAME_DAY_DYNAMIC_SLOTS = os.getenv("SAME_DAY_DYNAMIC_SLOTS", "0") in (
    "1",
    "true",
    "True",
)
# Enable dynamic per-band cap scaling based on historical above/below win rates.
SAME_DAY_DYNAMIC_K = int(os.getenv("SAME_DAY_DYNAMIC_K", "5"))
# Bayesian shrinkage constant (pseudo-observation count). Lower = more responsive to data.
SAME_DAY_DYNAMIC_BAND_HOURS = int(os.getenv("SAME_DAY_DYNAMIC_BAND_HOURS", "6"))
# Hours per time band (6 → 4 bands). Tighten to 3 or 2 once 200+ above/below trades settled.
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))
MAX_DAYS_OUT = int(os.getenv("MAX_DAYS_OUT", "5"))  # scan markets up to N days out
MAX_POSITION_AGE_DAYS = int(os.getenv("MAX_POSITION_AGE_DAYS", "7"))

# #120: Betting strategy — kelly | fixed_pct | fixed_dollars
# kelly:         quarter-Kelly sizing (default)
# fixed_pct:     always bet FIXED_BET_PCT of balance (set FIXED_BET_PCT env var)
# fixed_dollars: always bet FIXED_BET_DOLLARS (set FIXED_BET_DOLLARS env var)
STRATEGY = os.getenv("STRATEGY", "kelly").lower()
FIXED_BET_PCT = float(os.getenv("FIXED_BET_PCT", "0.01"))  # 1% of balance
FIXED_BET_DOLLARS = float(os.getenv("FIXED_BET_DOLLARS", "10.0"))  # $10 per trade

# #121: Drawdown recovery tiers — configurable via env
DRAWDOWN_HALT_PCT = float(os.getenv("DRAWDOWN_HALT_PCT", "0.20"))  # halt below this

# #P6: Pre-trade VaR gate. New position is skipped if it would push portfolio 5th-percentile
# loss beyond this amount. Default = 20% of STARTING_BALANCE ($200 on a $1000 start).
# Set to 0 to disable. Override via MAX_VAR_DOLLARS env var.
MAX_VAR_DOLLARS = float(os.getenv("MAX_VAR_DOLLARS", "200.0"))

# Starting paper bankroll in dollars. Set STARTING_BALANCE in .env to match your actual
# funded amount — all drawdown tiers, daily loss limits, and Kelly sizing reference this.
# paper.py reads this directly from os.getenv so it stays in sync.
STARTING_BALANCE: float = float(os.getenv("STARTING_BALANCE", "1000.0"))

# #P7: Stop-loss multiplier. A position is closed early when its unrealized loss
# exceeds cost / STOP_LOSS_MULT. Default 2.0 → exit when price halves (lost 50% of cost).
# Set to 0 to disable stop-losses entirely.
STOP_LOSS_MULT = float(os.getenv("STOP_LOSS_MULT", "2.0"))

# Break-even stop trigger: once a position's unrealized profit reaches this fraction
# of its cost (default 30%), move the stop to entry price. Any subsequent fall back
# to entry or below triggers a scratch exit — the position can no longer lose money.
BREAKEVEN_TRIGGER_PCT: float = float(os.getenv("BREAKEVEN_TRIGGER_PCT", "0.30"))

# Between-market low-confidence YES guard: block a "between" trade when our blended
# probability is below this and would still lead to a YES bet (see the between_floor
# gate in weather_markets.analyze_trade). Lower to block more, raise to loosen.
BETWEEN_FLOOR_MODEL_MAX: float = float(os.getenv("BETWEEN_FLOOR_MODEL_MAX", "0.15"))

# Micro live trades — hard-disabled until re-implemented with pre_live_trade_check(),
# execution_log writes, idempotency key, and add_live_loss() accounting (see P0-3/P0-4).
ENABLE_MICRO_LIVE: bool = False
MICRO_LIVE_FRACTION: float = float(os.getenv("MICRO_LIVE_FRACTION", "0.01"))
MICRO_LIVE_MIN_DOLLARS: float = float(os.getenv("MICRO_LIVE_MIN_DOLLARS", "1.0"))

# #P10.3: Weekly Brier alert — notify + pause if score exceeds this threshold
# for two consecutive ISO weeks.
BRIER_ALERT_THRESHOLD: float = float(os.getenv("BRIER_ALERT_THRESHOLD", "0.22"))

# Rolling accuracy circuit breaker
ACCURACY_WINDOW_TRADES: int = int(os.getenv("ACCURACY_WINDOW_TRADES", "20"))
ACCURACY_MIN_WIN_RATE: float = float(os.getenv("ACCURACY_MIN_WIN_RATE", "0.40"))
ACCURACY_MIN_SAMPLE: int = int(os.getenv("ACCURACY_MIN_SAMPLE", "20"))

# Minimum settled predictions required before Brier score is used to scale bet size.
# Below this count the Brier is statistically unreliable (small-sample luck).
MIN_BRIER_SAMPLES: int = int(os.getenv("MIN_BRIER_SAMPLES", "30"))

# SPRT model degradation detection constants (Task 22)
SPRT_P0: float = float(os.getenv("SPRT_P0", "0.55"))  # null hypothesis win rate
SPRT_P1: float = float(os.getenv("SPRT_P1", "0.45"))  # alternative (degraded) win rate
SPRT_ALPHA: float = float(os.getenv("SPRT_ALPHA", "0.05"))  # false positive rate
SPRT_BETA: float = float(os.getenv("SPRT_BETA", "0.20"))  # false negative rate
SPRT_MIN_TRADES: int = int(
    os.getenv("SPRT_MIN_TRADES", "20")
)  # min trades before SPRT activates

# #P10.4: Live slippage alert threshold in cents.
SLIPPAGE_ALERT_CENTS: float = float(os.getenv("SLIPPAGE_ALERT_CENTS", "0.5"))

# Optional HTTP Basic Auth password for the web dashboard.
# If empty (default), the dashboard is open. Set to protect the port.
DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "")

# Orderbook cache TTL — entries older than this are treated as stale and ignored.
# Default: 15 minutes. If the WS is silent for 15+ minutes the cache is worthless.
WS_CACHE_TTL_SECS: float = float(os.getenv("WS_CACHE_TTL_SECS", "900"))

# ── Shared math ───────────────────────────────────────────────────────────────


def normal_cdf(x: float, mu: float, sigma: float) -> float:
    """
    Probability that a Normal(mu, sigma) random variable is ≤ x.
    #30: Uses scipy.stats.norm.cdf if available (falls back to a plain
    math.erfc computation, mathematically equivalent, if scipy is absent).
    """
    if sigma <= 0:
        return 1.0 if x >= mu else 0.0
    try:
        from scipy.stats import norm as _norm  # type: ignore[import-untyped]

        return float(_norm.cdf(x, loc=mu, scale=sigma))
    except ImportError:
        return 0.5 * math.erfc((mu - x) / (sigma * math.sqrt(2)))


def prob_threshold(condition: dict, default: float = 0.0) -> float:
    """Continuous-space decision boundary for probability math (Gaussian CDF,
    ensemble exceedance fraction, etc.) on an above/below temperature condition.

    NOT the same as condition["threshold"] (the literal ticker/rule value,
    e.g. T86 -> 86.0) -- that raw value is kept as-is for audit_settlement,
    METAR lockout, and DB bookkeeping, which compare against Kalshi's literal
    rule text ("greater than 86"). Live-verified 2026-07-17 against real
    rules_primary text across 4 cities: a "T{val} above" ticker's actual rule
    is "greater than {val}", i.e. integer settlement must be val+1 or higher,
    so the continuous boundary that tiles with the adjacent between-bucket
    (which ends at val+0.5) is val+0.5, not val. Symmetric for below: val-0.5.
    _parse_market_condition sets "prob_threshold" accordingly; this getter
    falls back to raw "threshold" for "between"/precip conditions (which
    don't have "prob_threshold") and hand-built dicts in tests. Returns
    `default` (matching this codebase's existing convention for "not
    applicable in this branch", e.g. condition.get("threshold", 0.0)
    elsewhere) rather than None when neither key is present -- real
    above/below callers always have one of the two keys set, so this only
    fires for conditions where the caller's own type check would already
    make the result unused (e.g. an unconditionally-computed but
    type-gated-before-use raw fraction).
    """
    value = condition.get("prob_threshold", condition.get("threshold"))
    return float(value) if value is not None else default


# ── Logging ───────────────────────────────────────────────────────────────────


def _setup_logging() -> logging.Logger:
    """
    #106/#107: Configure structured logging. Each module should use
    logging.getLogger(__name__) for per-module log level control.
    Root 'kalshi' logger level set by LOG_LEVEL env var (default: WARNING).
    """
    root = logging.getLogger("kalshi")
    if root.handlers:
        return root  # already configured
    level = os.getenv("LOG_LEVEL", "WARNING").upper()
    root.setLevel(getattr(logging, level, logging.WARNING))
    handler = logging.StreamHandler()
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(_fmt)
    root.addHandler(handler)

    # Opt-in file logging: set LOG_FILE env var to persist logs to disk.
    # Uses RotatingFileHandler (10 MB max, 3 backups) so the file never grows unbounded.
    # When LOG_FILE is absent this block is skipped entirely — no behavior change.
    _log_file = os.getenv("LOG_FILE", "")
    if _log_file:
        from logging.handlers import RotatingFileHandler

        _fh = RotatingFileHandler(_log_file, maxBytes=10 * 1024 * 1024, backupCount=3)
        _fh.setFormatter(_fmt)
        root.addHandler(_fh)

    return root


logger = _setup_logging()


# ── P10.3: Config integrity ───────────────────────────────────────────────────

_CONFIG_HASH_PATH = (
    __import__("pathlib").Path(__file__).parent / "data" / ".config_hash"
)


def get_config_fingerprint() -> dict:
    """P10.3: Return a snapshot of all env-configurable parameters.

    This is the single source of truth for what config is currently active.
    Changes between runs can be detected by comparing fingerprints.

    DASHBOARD_PASSWORD is deliberately excluded -- check_config_integrity()
    writes this fingerprint to data/.config_hash in plaintext, and a secret
    has no business living in a drift-detection file on disk.
    """
    return {
        "KALSHI_FEE_RATE": KALSHI_FEE_RATE,
        "KALSHI_MAKER_FEE_RATE": KALSHI_MAKER_FEE_RATE,
        "KELLY_CAP": KELLY_CAP,
        "MIN_EDGE": MIN_EDGE,
        "PAPER_MIN_EDGE": get_paper_min_edge(),
        "MIN_PROB_EDGE": MIN_PROB_EDGE,
        "CITY_MIN_PROB_EDGE": CITY_MIN_PROB_EDGE,
        "MAX_MARKET_DIVERGENCE_RATIO": MAX_MARKET_DIVERGENCE_RATIO,
        "MIN_MARKET_PROB_TO_BET_WITH": MIN_MARKET_PROB_TO_BET_WITH,
        "STRONG_EDGE": STRONG_EDGE,
        "DRIFT_TIGHTEN_EDGE": DRIFT_TIGHTEN_EDGE,
        "MED_EDGE": MED_EDGE,
        "MAX_DAILY_SPEND": MAX_DAILY_SPEND,
        "MAX_SAME_DAY_SPEND": MAX_SAME_DAY_SPEND,
        "SAME_DAY_RESERVE_SLOTS": SAME_DAY_RESERVE_SLOTS,
        "SAME_DAY_RESERVE_AFTER_HOUR_UTC": SAME_DAY_RESERVE_AFTER_HOUR_UTC,
        "SAME_DAY_RESERVE_MIN_SAMPLES": SAME_DAY_RESERVE_MIN_SAMPLES,
        "SAME_DAY_DYNAMIC_SLOTS": SAME_DAY_DYNAMIC_SLOTS,
        "SAME_DAY_DYNAMIC_K": SAME_DAY_DYNAMIC_K,
        "SAME_DAY_DYNAMIC_BAND_HOURS": SAME_DAY_DYNAMIC_BAND_HOURS,
        "BREAKEVEN_TRIGGER_PCT": BREAKEVEN_TRIGGER_PCT,
        "BETWEEN_FLOOR_MODEL_MAX": BETWEEN_FLOOR_MODEL_MAX,
        "MAX_DAILY_LOSS_PCT": MAX_DAILY_LOSS_PCT,
        "MAX_DAYS_OUT": MAX_DAYS_OUT,
        "MAX_POSITION_AGE_DAYS": MAX_POSITION_AGE_DAYS,
        "STRATEGY": STRATEGY,
        "FIXED_BET_PCT": FIXED_BET_PCT,
        "FIXED_BET_DOLLARS": FIXED_BET_DOLLARS,
        "DRAWDOWN_HALT_PCT": DRAWDOWN_HALT_PCT,
        "MAX_VAR_DOLLARS": MAX_VAR_DOLLARS,
        "STARTING_BALANCE": STARTING_BALANCE,
        "STOP_LOSS_MULT": STOP_LOSS_MULT,
        "ENABLE_MICRO_LIVE": ENABLE_MICRO_LIVE,
        "MICRO_LIVE_FRACTION": MICRO_LIVE_FRACTION,
        "MICRO_LIVE_MIN_DOLLARS": MICRO_LIVE_MIN_DOLLARS,
        "BRIER_ALERT_THRESHOLD": BRIER_ALERT_THRESHOLD,
        "ACCURACY_WINDOW_TRADES": ACCURACY_WINDOW_TRADES,
        "ACCURACY_MIN_WIN_RATE": ACCURACY_MIN_WIN_RATE,
        "ACCURACY_MIN_SAMPLE": ACCURACY_MIN_SAMPLE,
        "MIN_BRIER_SAMPLES": MIN_BRIER_SAMPLES,
        "SPRT_P0": SPRT_P0,
        "SPRT_P1": SPRT_P1,
        "SPRT_ALPHA": SPRT_ALPHA,
        "SPRT_BETA": SPRT_BETA,
        "SPRT_MIN_TRADES": SPRT_MIN_TRADES,
        "SLIPPAGE_ALERT_CENTS": SLIPPAGE_ALERT_CENTS,
        "WS_CACHE_TTL_SECS": WS_CACHE_TTL_SECS,
    }


def _hash_fingerprint(fp: dict) -> str:
    import hashlib
    import json

    canonical = json.dumps(fp, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def check_config_integrity() -> dict:
    """P10.3: Compare current config against the last-seen fingerprint.

    Writes the current hash to data/.config_hash on first run or if config changed.

    Returns:
        {
            "changed": bool,
            "current_hash": str,
            "previous_hash": str | None,
            "changed_keys": list[str],   # keys whose values changed
        }
    """
    import json

    fp = get_config_fingerprint()
    current_hash = _hash_fingerprint(fp)
    _CONFIG_HASH_PATH.parent.mkdir(exist_ok=True)

    previous_hash: str | None = None
    previous_fp: dict = {}
    if _CONFIG_HASH_PATH.exists():
        try:
            stored = json.loads(_CONFIG_HASH_PATH.read_text())
            previous_hash = stored.get("hash")
            previous_fp = stored.get("fingerprint", {})
        except Exception as _exc:
            logging.getLogger(__name__).warning(
                "check_config_integrity: could not read %s (%s) — treating as "
                "first run; drift for this cycle will be missed",
                _CONFIG_HASH_PATH,
                _exc,
            )

    changed = previous_hash is not None and current_hash != previous_hash
    changed_keys = [k for k in fp if fp.get(k) != previous_fp.get(k)] if changed else []

    if previous_hash is None or changed:
        try:
            _CONFIG_HASH_PATH.write_text(
                json.dumps({"hash": current_hash, "fingerprint": fp}, indent=2)
            )
        except Exception as _exc:
            logging.getLogger(__name__).warning(
                "check_config_integrity: could not write %s (%s) — drift "
                "detection will silently stop working until this is fixed",
                _CONFIG_HASH_PATH,
                _exc,
            )

    if changed:
        logging.getLogger(__name__).warning(
            "config_integrity: config changed since last run — changed keys: %s",
            changed_keys,
        )

    return {
        "changed": changed,
        "current_hash": current_hash,
        "previous_hash": previous_hash,
        "changed_keys": changed_keys,
    }
