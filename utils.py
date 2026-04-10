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
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.10"))  # minimum edge to show in analyze
STRONG_EDGE = float(
    os.getenv("STRONG_EDGE", "0.25")
)  # threshold for "STRONG BUY" label
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))
MAX_POSITION_AGE_DAYS = int(os.getenv("MAX_POSITION_AGE_DAYS", "7"))

# ── Shared math ───────────────────────────────────────────────────────────────


def normal_cdf(x: float, mu: float, sigma: float) -> float:
    """Probability that a Normal(mu, sigma) random variable is ≤ x."""
    return 0.5 * math.erfc((mu - x) / (sigma * math.sqrt(2)))


# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("kalshi")
