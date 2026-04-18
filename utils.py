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
