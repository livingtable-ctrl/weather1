"""
Shared utilities used across the Kalshi weather trading modules.
"""

from __future__ import annotations

import logging
import math
import os

# ── Kalshi platform constant ──────────────────────────────────────────────────

# Fee Kalshi charges on winning trades. 7% is the default taker rate.
# Maker (limit) orders pay 0%. Override via KALSHI_FEE_RATE in .env.
KALSHI_FEE_RATE = float(os.getenv("KALSHI_FEE_RATE", "0.07"))

# Edge thresholds — override via .env
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.07"))  # minimum edge to show in analyze
# Paper trading uses a lower threshold to capture more signals for observation.
# Must be <= 5% per system requirements (P1.3). Override via PAPER_MIN_EDGE env var.
PAPER_MIN_EDGE = float(os.getenv("PAPER_MIN_EDGE", "0.05"))
# Minimum probability-delta edge (forecast_prob − market_prob) to place a trade.
# Filters out signals where ROI edge exists but probability conviction is low.
# 8pp = ~2× the 4pp ask/bid half-spread on a typical 50¢ Kalshi contract.
MIN_PROB_EDGE = float(os.getenv("MIN_PROB_EDGE", "0.08"))

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
)  # max total paper dollars auto-traded per day
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))
MAX_DAYS_OUT = int(os.getenv("MAX_DAYS_OUT", "5"))  # scan markets up to N days out
MAX_POSITION_AGE_DAYS = int(os.getenv("MAX_POSITION_AGE_DAYS", "7"))

# #120: Betting strategy — kelly | fixed_pct | fixed_dollars
# kelly:         standard half-Kelly sizing (default)
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
    #30: Uses scipy.stats.norm.logcdf if available to avoid underflow at tails.
    """
    if sigma <= 0:
        return 1.0 if x >= mu else 0.0
    try:
        from scipy.stats import norm as _norm  # type: ignore[import-untyped]

        return float(_norm.cdf(x, loc=mu, scale=sigma))
    except ImportError:
        return 0.5 * math.erfc((mu - x) / (sigma * math.sqrt(2)))


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
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
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
    """
    return {
        "KALSHI_FEE_RATE": KALSHI_FEE_RATE,
        "MIN_EDGE": MIN_EDGE,
        "PAPER_MIN_EDGE": PAPER_MIN_EDGE,
        "STRONG_EDGE": STRONG_EDGE,
        "MED_EDGE": MED_EDGE,
        "MAX_DAILY_SPEND": MAX_DAILY_SPEND,
        "MAX_DAILY_LOSS_PCT": MAX_DAILY_LOSS_PCT,
        "MAX_DAYS_OUT": MAX_DAYS_OUT,
        "MAX_POSITION_AGE_DAYS": MAX_POSITION_AGE_DAYS,
        "STRATEGY": STRATEGY,
        "FIXED_BET_PCT": FIXED_BET_PCT,
        "FIXED_BET_DOLLARS": FIXED_BET_DOLLARS,
        "DRAWDOWN_HALT_PCT": DRAWDOWN_HALT_PCT,
        "MAX_VAR_DOLLARS": MAX_VAR_DOLLARS,
        "STOP_LOSS_MULT": STOP_LOSS_MULT,
        "ENABLE_MICRO_LIVE": ENABLE_MICRO_LIVE,
        "MICRO_LIVE_FRACTION": MICRO_LIVE_FRACTION,
        "BRIER_ALERT_THRESHOLD": BRIER_ALERT_THRESHOLD,
        "SLIPPAGE_ALERT_CENTS": SLIPPAGE_ALERT_CENTS,
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
        except Exception:
            pass

    changed = previous_hash is not None and current_hash != previous_hash
    changed_keys = [k for k in fp if fp.get(k) != previous_fp.get(k)] if changed else []

    if previous_hash is None or changed:
        try:
            _CONFIG_HASH_PATH.write_text(
                json.dumps({"hash": current_hash, "fingerprint": fp}, indent=2)
            )
        except Exception:
            pass

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
