"""
Shared utilities used across the Kalshi weather trading modules.
"""

from __future__ import annotations

import logging
import math

# ── Kalshi platform constant ──────────────────────────────────────────────────

KALSHI_FEE_RATE = 0.07  # 7% of winnings charged by Kalshi

# ── Shared math ───────────────────────────────────────────────────────────────


def normal_cdf(x: float, mu: float, sigma: float) -> float:
    """Probability that a Normal(mu, sigma) random variable is ≤ x."""
    return 0.5 * math.erfc((mu - x) / (sigma * math.sqrt(2)))


# ── Logging ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("kalshi")
