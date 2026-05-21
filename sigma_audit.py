"""
Sigma calibration audit — diagnostic script, no behavior changes.

Reads settled predictions from the DB and infers what sigma value would be
needed to reproduce both our_prob and market_prob, given the stored
forecast_temp_f and thresholds.  The ratio our_sigma / market_sigma tells us
whether our temperature uncertainty is miscalibrated vs the market.

Usage:
    python sigma_audit.py

Expected output if sigma is the root cause:
    "between" contracts show ratio >= 2.0 (our sigma much wider than market).
    "below"/"above" contracts may show smaller ratios.

If ratio < 1.5 for all condition types, sigma is NOT the root cause and
Change 2 (sigma cap) should be reconsidered.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

try:
    from scipy.optimize import brentq
    from scipy.stats import norm as _norm

    def _cdf(x: float, mu: float, sigma: float) -> float:
        return float(_norm.cdf(x, loc=mu, scale=sigma))

except ImportError:

    def _cdf(x: float, mu: float, sigma: float) -> float:  # type: ignore[misc]
        return 0.5 * math.erfc((mu - x) / (sigma * math.sqrt(2)))

    def brentq(f, a, b, **_kw):  # type: ignore[misc]
        # Fallback bisection if scipy not available
        for _i in range(60):
            mid = (a + b) / 2
            if f(mid) * f(a) <= 0:
                b = mid
            else:
                a = mid
        return (a + b) / 2


_DB = Path(__file__).parent / "data" / "predictions.db"
# Also try parent project directory (when running from a git worktree)
if not _DB.exists():
    _DB = Path(__file__).parent.parent.parent / "data" / "predictions.db"
if not _DB.exists():
    _DB = Path("C:/Users/thesa/claude kalshi/data/predictions.db")


def _forecast_prob(
    condition_type: str,
    lo: float | None,
    hi: float | None,
    forecast_temp: float,
    sigma: float,
) -> float:
    """Replicate _forecast_probability() using stored threshold columns."""
    if sigma <= 0:
        return float("nan")
    if condition_type == "above":
        threshold = hi if hi is not None else lo
        if threshold is None:
            return float("nan")
        return 1.0 - _cdf(threshold, forecast_temp, sigma)
    elif condition_type == "below":
        threshold = hi if hi is not None else lo
        if threshold is None:
            return float("nan")
        return _cdf(threshold, forecast_temp, sigma)
    elif condition_type == "between":
        if lo is None or hi is None:
            return float("nan")
        return _cdf(hi, forecast_temp, sigma) - _cdf(lo, forecast_temp, sigma)
    return float("nan")


def _implied_sigma(
    condition_type: str,
    lo: float | None,
    hi: float | None,
    forecast_temp: float,
    target_prob: float,
) -> float | None:
    """Find sigma such that _forecast_prob(..., sigma) == target_prob."""
    if not (0.001 < target_prob < 0.999):
        return None
    try:

        def f(s: float) -> float:
            return (
                _forecast_prob(condition_type, lo, hi, forecast_temp, s) - target_prob
            )

        # Search in [0.1, 30] — all plausible temperature sigmas
        if f(0.1) * f(30.0) > 0:
            return None
        return brentq(f, 0.1, 30.0, xtol=1e-4)
    except Exception:
        return None


def run_audit() -> None:
    if not _DB.exists():
        print(f"Database not found: {_DB}")
        return

    con = sqlite3.connect(str(_DB))
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT city, condition_type, threshold_lo, threshold_hi,
               forecast_temp_f, our_prob, market_prob
        FROM predictions
        WHERE forecast_temp_f IS NOT NULL
          AND our_prob IS NOT NULL
          AND market_prob IS NOT NULL
          AND condition_type IS NOT NULL
    """).fetchall()
    con.close()

    if not rows:
        print("No predictions with forecast_temp_f found. Run the bot first.")
        return

    print(
        f"\n{'City':12s} {'Type':8s} {'our_p':6s} {'mkt_p':6s} "
        f"{'our_sig':7s} {'mkt_sig':7s} {'ratio':6s}"
    )
    print("-" * 62)

    by_type: dict[str, list[float]] = {}

    for r in rows:
        city = r["city"] or "?"
        ctype = r["condition_type"]
        temp = r["forecast_temp_f"]
        lo, hi = r["threshold_lo"], r["threshold_hi"]
        our_p, mkt_p = r["our_prob"], r["market_prob"]

        our_sig = _implied_sigma(ctype, lo, hi, temp, our_p)
        mkt_sig = _implied_sigma(ctype, lo, hi, temp, mkt_p)

        if our_sig is None or mkt_sig is None or mkt_sig < 0.05:
            ratio_str = "  N/A"
        else:
            ratio = our_sig / mkt_sig
            ratio_str = f"{ratio:5.2f}x"
            by_type.setdefault(ctype, []).append(ratio)

        our_s = f"{our_sig:.2f}" if our_sig is not None else "  N/A"
        mkt_s = f"{mkt_sig:.2f}" if mkt_sig is not None else "  N/A"
        print(
            f"{str(city)[:12]:12s} {ctype:8s} {our_p:.3f}  {mkt_p:.3f}  "
            f"{our_s:>7s}  {mkt_s:>7s}  {ratio_str}"
        )

    print("\n=== Mean ratio by condition type ===")
    for ctype, ratios in sorted(by_type.items()):
        mean = sum(ratios) / len(ratios)
        flag = " <- SIGMA TOO LARGE" if mean >= 2.0 else ""
        print(f"  {ctype:8s}  n={len(ratios):2d}  mean ratio={mean:.2f}x{flag}")

    print()
    if any(sum(v) / len(v) >= 2.0 for v in by_type.values() if v):
        print(
            "DIAGNOSIS: Sigma is likely too large. Proceed with Change 2 (sigma cap)."
        )
    else:
        print("NOTE: Sigma ratio < 2.0. Sigma may not be the primary root cause.")
        print("      Reconsider before implementing the sigma cap.")


if __name__ == "__main__":
    run_audit()
