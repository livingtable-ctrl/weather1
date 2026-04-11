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
STRONG_EDGE = float(
    os.getenv("STRONG_EDGE", "0.25")
)  # threshold for "STRONG BUY" label
MED_EDGE = float(
    os.getenv("MED_EDGE", "0.15")
)  # threshold for medium-confidence auto-trade tier
MAX_DAILY_SPEND = float(
    os.getenv("MAX_DAILY_SPEND", "100.0")
)  # max total paper dollars auto-traded per day
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))
MAX_DAYS_OUT = int(os.getenv("MAX_DAYS_OUT", "4"))  # scan markets up to N days out
MAX_POSITION_AGE_DAYS = int(os.getenv("MAX_POSITION_AGE_DAYS", "7"))

# #120: Betting strategy — kelly | fixed_pct | fixed_dollars
# kelly:         standard half-Kelly sizing (default)
# fixed_pct:     always bet FIXED_BET_PCT of balance (set FIXED_BET_PCT env var)
# fixed_dollars: always bet FIXED_BET_DOLLARS (set FIXED_BET_DOLLARS env var)
STRATEGY = os.getenv("STRATEGY", "kelly").lower()
FIXED_BET_PCT = float(os.getenv("FIXED_BET_PCT", "0.01"))  # 1% of balance
FIXED_BET_DOLLARS = float(os.getenv("FIXED_BET_DOLLARS", "10.0"))  # $10 per trade

# #121: Drawdown recovery tiers — configurable via env
DRAWDOWN_HALT_PCT = float(os.getenv("DRAWDOWN_HALT_PCT", "0.50"))  # halt below this

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
