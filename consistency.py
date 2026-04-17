"""
Cross-market consistency checker.

For a given city + date, temperature threshold markets must satisfy:
  P(high > 70°) <= P(high > 65°) <= P(high > 60°)   [above thresholds decrease]
  P(high < 60°) <= P(high < 65°) <= P(high < 70°)   [below thresholds increase]

If the market prices violate this monotonicity, there is a risk-free arbitrage:
buy the underpriced contract and sell the overpriced one.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from weather_markets import parse_market_price

_STALENESS_THRESHOLD = 300  # seconds; skip markets older than this


@dataclass
class Violation:
    buy_ticker: str  # the contract to BUY (underpriced)
    sell_ticker: str  # the contract to SELL (overpriced)
    buy_prob: float
    sell_prob: float
    guaranteed_edge: float  # sell_prob - buy_prob (> 0 means free money)
    description: str


def _parse_threshold(market: dict) -> tuple[str, float] | None:
    """
    Extract (condition_type, threshold) from a market ticker.
    Returns ("above", 68.0), ("below", 53.0), or ("between", 59.5) etc.
    """
    ticker = market.get("ticker", "")
    title = (market.get("title") or "").lower()

    m = re.search(r"-([TB])(\d+(?:\.\d+)?)$", ticker)
    if not m:
        return None

    kind, val = m.group(1), float(m.group(2))

    if kind == "B":
        return ("between", val)
    elif ">" in title or "above" in title:
        return ("above", val)
    elif "<" in title or "below" in title:
        return ("below", val)
    return None


def _group_markets(markets: list[dict]) -> dict:
    """
    Group markets by (series_ticker, date_str).
    Returns dict: key -> list of (market, condition_type, threshold, implied_prob).
    """
    groups: dict = {}

    for m in markets:
        ticker = m.get("ticker", "")

        # Extract series and date from ticker
        series = m.get("series_ticker", "")
        if not series:
            # Derive from ticker prefix
            parts = ticker.split("-")
            series = parts[0] if parts else ""

        date_match = re.search(r"(\d{2}[A-Z]{3}\d{2})", ticker)
        date_str = date_match.group(1) if date_match else ""

        if not series or not date_str:
            continue

        parsed = _parse_threshold(m)
        if not parsed:
            continue

        cond_type, threshold = parsed
        prices = parse_market_price(m)
        implied = prices["implied_prob"]

        key = (series, date_str)
        groups.setdefault(key, []).append((m, cond_type, threshold, implied))

    return groups


def find_violations(
    markets: list[dict], *, staleness_threshold: float = _STALENESS_THRESHOLD
) -> list[Violation]:
    """
    Scan a list of markets and return all monotonicity violations.
    Only checks markets that have real quotes (implied_prob > 0).
    Markets with _fetched_at older than staleness_threshold seconds are skipped.
    """
    now = time.time()
    fresh = [
        m for m in markets if now - m.get("_fetched_at", now) <= staleness_threshold
    ]
    groups = _group_markets(fresh)
    violations: list[Violation] = []

    for (series, date_str), entries in groups.items():
        # Split into above and below groups
        above = [(m, t, p) for m, ct, t, p in entries if ct == "above" and p > 0]
        below = [(m, t, p) for m, ct, t, p in entries if ct == "below" and p > 0]

        # Above: P(high > X) should DECREASE as X increases
        # Sort by threshold ascending
        above.sort(key=lambda x: x[1])
        for i in range(len(above) - 1):
            m_lo, t_lo, p_lo = above[i]
            m_hi, t_hi, p_hi = above[i + 1]
            if p_hi > p_lo + 0.01:  # P(> higher threshold) > P(> lower) — violation
                violations.append(
                    Violation(
                        buy_ticker=m_lo["ticker"],
                        sell_ticker=m_hi["ticker"],
                        buy_prob=p_lo,
                        sell_prob=p_hi,
                        guaranteed_edge=p_hi - p_lo,
                        description=(
                            f"P(>{t_hi:.0f}°) = {p_hi:.0%} > P(>{t_lo:.0f}°) = {p_lo:.0%} — "
                            f"IMPOSSIBLE: higher threshold can't have higher probability"
                        ),
                    )
                )

        # Below: P(high < X) should INCREASE as X increases
        below.sort(key=lambda x: x[1])
        for i in range(len(below) - 1):
            m_lo, t_lo, p_lo = below[i]
            m_hi, t_hi, p_hi = below[i + 1]
            if p_lo > p_hi + 0.01:  # P(< lower threshold) > P(< higher) — violation
                violations.append(
                    Violation(
                        buy_ticker=m_hi["ticker"],
                        sell_ticker=m_lo["ticker"],
                        buy_prob=p_hi,
                        sell_prob=p_lo,
                        guaranteed_edge=p_lo - p_hi,
                        description=(
                            f"P(<{t_lo:.0f}°) = {p_lo:.0%} > P(<{t_hi:.0f}°) = {p_hi:.0%} — "
                            f"IMPOSSIBLE: lower threshold can't have higher 'below' probability"
                        ),
                    )
                )

    violations.sort(key=lambda v: v.guaranteed_edge, reverse=True)
    return violations
