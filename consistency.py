"""
Cross-market consistency checker.

For a given city + date, temperature threshold markets must satisfy:
  P(high > 70°) <= P(high > 65°) <= P(high > 60°)   [above thresholds decrease]
  P(high < 60°) <= P(high < 65°) <= P(high < 70°)   [below thresholds increase]

For a given city + month, monthly rain-total markets (KXRAIN*M) must satisfy
the same single-sided shape: P(total > 7in) <= P(total > 5in) <= P(total > 1in).

If the market prices violate this monotonicity, there is a risk-free arbitrage:
buy the underpriced contract and sell the overpriced one. Rain violations are
returned with Violation.is_shadow=True -- see find_violations()'s docstring --
this is a first pass, not yet graduated to real auto-placement.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from weather_markets import (
    _KXRAIN_MONTHLY_CITY,
    _KXSNOW_MONTHLY_CITY,
    _KXTEMP_HOURLY_CITY,
    is_hurricane_count_ticker,
    is_hurricane_next_event_ticker,
    market_implied_rain_event_key,
    parse_market_price,
)

_log = logging.getLogger(__name__)


@dataclass
class Violation:
    buy_ticker: str  # the contract to BUY (underpriced)
    sell_ticker: str  # the contract to SELL (overpriced)
    buy_prob: float
    sell_prob: float
    guaranteed_edge: float  # sell_prob - buy_prob (> 0 means free money)
    description: str
    # backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE CHECK STILL
    # BLANKET-EXCLUDES KXRAIN*M": rain's ladder monotonicity has never been
    # checked against live prices before this field existed, unlike
    # temperature's (which has run this same check for months). True for
    # every rain-sourced violation -- detect and log, but callers must skip
    # the actual auto-place step, mirroring this project's established
    # shadow-then-graduate pattern for every other new-market-type signal
    # (rain forecast-blend, hurricane count guard). Not gated on a sample
    # floor/graduation trigger of its own yet -- that's a deliberate
    # follow-up decision, not part of this pass (see backlog.txt).
    is_shadow: bool = False


def _parse_threshold(market: dict) -> tuple[str, float] | None:
    """
    Extract (condition_type, threshold) from a market ticker.
    Returns ("above", 68.0), ("below", 53.0), or ("between", 59.5) etc.

    R26: condition direction is derived from the series ticker prefix first
    (KXHIGH* → above, KXLOW* → below) and only falls back to title text so
    that None/empty titles don't silently drop valid markets.

    market.get("series_ticker") is ALWAYS empty on a real Kalshi response
    (confirmed live 2026-07-25 while fixing tracker.py's candlestick-backfill
    bug — see _derive_series_ticker there) — so in practice this function
    ALWAYS falls through to the title-text fallback below, never the R26
    series-prefix branch. DO NOT "fix" that by adding a
    ticker.split("-")[0]-style fallback the way tracker.py's candlestick
    backfill does for its own, unrelated series_ticker gap: confirmed live
    that real KXHIGH*/KXLOW* series can each contain BOTH above- and
    below-condition markets (e.g. a real KXLOWTPHX ladder asking "will the
    minimum be >N", a real KXHIGHCHI ladder asking "will the high be <N") —
    a ticker-prefix-derived HIGH/LOW substring is not a reliable direction
    signal the way it is for city/series identification elsewhere in this
    codebase. Adding that fallback here would silently INVERT above/below
    for real ladders and feed a fabricated arbitrage "violation" into
    find_violations(), which drives automatic corrective trading — this was
    only caught before shipping by an independent review specifically
    warning that the tracker.py fix's own doc comment holds this function
    up as its "established precedent," which it is not safe to copy.
    """
    ticker = market.get("ticker", "")
    series = (market.get("series_ticker") or "").upper()
    title = (market.get("title") or "").lower()

    m = re.search(r"-([TB])(\d+(?:\.\d+)?)$", ticker)
    if not m:
        return None

    kind, val = m.group(1), float(m.group(2))

    if kind == "B":
        return ("between", val)

    # R26: prefer series prefix over free-text title matching
    if "HIGH" in series:
        return ("above", val)
    if "LOW" in series:
        return ("below", val)

    # Fallback: parse title/subtitle text (less reliable)
    subtitle = (market.get("subtitle") or "").lower()
    combined = title + " " + subtitle
    if ">" in combined or "above" in combined:
        return ("above", val)
    if "<" in combined or "below" in combined:
        return ("below", val)
    return None


def _group_markets(markets: list[dict]) -> dict:
    """
    Group markets by (series_ticker, date_str).
    Returns dict: key -> list of (market, condition_type, threshold, implied_prob).

    Excludes KXTEMPxxxH hourly-directional brackets: date_str is day-level
    only (no hour component), so multiple different hours' ladders for the
    same city/day would otherwise be silently pooled into one group here and
    compared for monotonicity as if they were one ladder -- a real risk,
    unlike the log-only market-implied-distribution signal, since
    find_violations()'s output feeds directly into automatic corrective
    trading (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 1 --
    no probability model exists yet for these).

    KXRAIN*M monthly rain-total ladders (backlog.txt "RAIN MARKETS --
    CONSISTENCY.PY'S ARBITRAGE CHECK STILL BLANKET-EXCLUDES KXRAIN*M")
    are handled by a dedicated branch below rather than this function's
    generic (series, date_str)-from-ticker-regex path: rain has no day
    component, so that key shape doesn't apply, and Kalshi's real per-
    bracket threshold lives in the market's own floor_strike/strike_type
    fields, not ticker/title text (live-verified across every tracked rain
    series -- see weather_markets._parse_market_condition's identical KXRAIN*M
    branch, the established precedent this mirrors). Grouped instead via
    weather_markets.market_implied_rain_event_key() -- the same (city,
    "RAIN", year, month) 4-tuple key already proven live by the sibling
    market-implied-distribution signal, reused rather than reinvented so the
    two features can never drift on what counts as "the same rain event."
    That key shape is structurally distinct (4-tuple, "RAIN"-tagged) from
    temperature's (series, date_str) 2-tuple, so the two families can never
    collide in this function's single returned `groups` dict.

    Every rain-sourced violation find_violations() produces is tagged
    is_shadow=True, set explicitly at append time below (not re-derived
    later from the group key's shape -- a future new market family sharing
    rain's 4-tuple key shape must make its own explicit is_shadow decision,
    not silently inherit False by omission) -- rain's ladder monotonicity
    has never been checked against live prices before, unlike temperature's,
    so this is a deliberate shadow-only first pass: callers must log/observe
    but not act on these until a separate, later decision graduates them.

    Also excludes KXDENSNOWM monthly snow-total ladders (backlog.txt "RAIN /
    SNOW / HURRICANE MARKETS" Step 1) -- snow's own arbitrage-check grouping
    is a separate, not-yet-picked-up piece of that same backlog family, out
    of scope for the rain fix above. Redundant with the final grouping
    outcome -- these tickers' date_match regex already fails (no day digits
    after the month), so they'd be dropped via the "not series or not
    date_str" skip below regardless -- but NOT redundant for the L-8
    warning just below that skip: series resolves truthy (derived from the
    ticker prefix, e.g. "KXDENSNOWM") while date_match stays None, which
    without this exclusion would log a real WARNING for every snow market on
    every single scan. Kept explicit for that reason, plus the same
    single-source-of-truth reasoning as the hourly exclusion, since this
    feeds find_violations() too.

    Also excludes the 5 hurricane-season-count series (backlog.txt
    "HURRICANE MARKETS" -- season-count model, 2026-08-03), added here
    because -- unlike rain/snow -- this exclusion is NOT redundant:
    KXHURCTOT/KXHURCTOTMAJ/KXTROPSTORM tickers embed a real day-level date
    ("KXHURCTOT-26DEC01-T9") that the date_match regex below DOES match, and
    their "-T<N>" suffix DOES match _parse_threshold's own regex too --
    they were only failing to reach find_violations() by an accident of
    title text (real titles like "more than 9 Atlantic hurricanes" don't
    contain the literal "above"/">" _parse_threshold's title fallback
    requires) -- the exact "safe by coincidence" shape this project has
    already been burned by once for this same ticker family (see
    is_hurricane_ticker()'s own history). find_violations() feeds
    automatic corrective trading (_arb_ppo -> paper.place_paper_order)
    directly, with NO shadow-gate check of its own for THIS ticker family
    (rain is the one exception -- see the is_shadow field on Violation and
    the rain branch below) -- opus-review-caught (2026-08-03): without this
    exclusion, adding these 5 series to
    KNOWN_WEATHER_SERIES (so get_weather_markets() now returns them) would
    let the arb auto-placer place REAL (non-shadow) paper orders on a
    ticker family this bot has explicitly decided is unvalidated,
    completely bypassing _hurricane_count_gates_active().
    """
    groups: dict = {}

    for m in markets:
        ticker = m.get("ticker", "")
        if ticker.upper().startswith(tuple(_KXTEMP_HOURLY_CITY)):
            continue
        if ticker.upper().startswith(tuple(_KXSNOW_MONTHLY_CITY)):
            continue
        if is_hurricane_count_ticker(ticker):
            continue
        # Same reasoning as the hurricane-count exclusion just above, for the
        # 2 time-to-next-event series (backlog.txt "HURRICANE MARKETS" --
        # time-to-next-event model, 2026-08-07): KNOWN_WEATHER_SERIES now
        # returns them too, so find_violations() would otherwise see them
        # with no shadow-gate check of its own, completely bypassing
        # _hurricane_next_event_gates_active().
        if is_hurricane_next_event_ticker(ticker):
            continue

        if ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY)):
            # Rain branch: (city, "RAIN", year, month) key via the shared
            # sibling helper, condition read from Kalshi's own
            # floor_strike/strike_type fields -- mirrors
            # weather_markets._parse_market_condition's identical KXRAIN*M
            # branch rather than _parse_threshold's ticker-suffix regex
            # below, which can't match a "-<N>" rain bracket suffix at all
            # (no T/B letter). Fails closed (skip, don't guess, and WARN so
            # an unexpected listing-format change surfaces immediately
            # instead of silently turning this check into a permanent
            # no-op) on any unexpected shape, mirroring that sibling
            # branch's own logging.
            rain_key = market_implied_rain_event_key(ticker)
            if rain_key is None:
                _log.warning(
                    "consistency: could not derive rain event key from ticker %r"
                    " — excluded from grouping",
                    ticker,
                )
                continue
            floor_strike = m.get("floor_strike")
            strike_type = m.get("strike_type")
            if floor_strike is None or strike_type != "greater":
                _log.warning(
                    "consistency[%s]: missing floor_strike or unexpected"
                    " strike_type=%r (expected 'greater') — excluded from grouping",
                    ticker,
                    strike_type,
                )
                continue
            try:
                threshold = float(floor_strike)
            except (TypeError, ValueError):
                _log.warning(
                    "consistency[%s]: non-numeric floor_strike=%r — excluded"
                    " from grouping",
                    ticker,
                    floor_strike,
                )
                continue
            # coalesce_market_price (utils.py, called via parse_market_price)
            # documents itself as raising ValueError on a non-numeric price
            # string and expects EVERY caller to wrap it per-market -- this
            # branch didn't reach parse_market_price at all before rain was
            # supported, so it's new exposure here specifically. Unguarded,
            # one malformed rain price would raise out of find_violations()
            # entirely, which (via each caller's own except Exception) can
            # halt ALL auto-trading for the cycle -- exactly what the
            # shadow-only design exists to prevent. See the identical guard
            # added to the temperature branch below (pre-existing gap,
            # fixed in the same pass since it's the same call, same file).
            try:
                prices = parse_market_price(m)
            except (ValueError, TypeError) as exc:
                _log.warning(
                    "consistency[%s]: malformed price fields (%s) — excluded"
                    " from grouping",
                    ticker,
                    exc,
                )
                continue
            if not prices.get("has_quote", False):
                continue
            # precip_month_total is always single-sided "total > threshold"
            # (Kalshi's strike_type="greater", live-verified across every
            # tracked rain series) -- the same shape as a temperature
            # "above" bracket, so it reuses that monotonicity loop unchanged
            # rather than adding a parallel rain-specific check below.
            # is_shadow/unit are set explicitly here (not re-derived later
            # from the group key's shape) so a FUTURE new market family
            # sharing this same 4-tuple-key pattern (e.g. snow's own
            # arbitrage check, already flagged as a follow-up above) can't
            # silently default to is_shadow=False just by omission --
            # opus-review-caught: the same "shared resource, one caller
            # forgets to opt in" bug class this project has hit before for
            # hurricane/rain shadow gates.
            groups.setdefault(rain_key, []).append(
                (
                    m,
                    "above",
                    threshold,
                    prices["implied_prob"],
                    prices["yes_bid"],
                    prices["yes_ask"],
                    True,  # is_shadow
                    "in",  # unit
                )
            )
            continue

        # Extract series and date from ticker
        series = m.get("series_ticker", "")
        if not series:
            # Derive from ticker prefix
            parts = ticker.split("-")
            series = parts[0] if parts else ""

        date_match = re.search(r"(\d{2}[A-Z]{3}\d{2})", ticker)
        # L-8: warn when ticker format doesn't match — silent drop masks API format changes
        if date_match is None and series:
            _log.warning(
                "consistency: could not extract date from ticker %r — excluded from grouping",
                ticker,
            )
        date_str = date_match.group(1) if date_match else ""

        if not series or not date_str:
            continue

        parsed = _parse_threshold(m)
        if not parsed:
            continue

        cond_type, threshold = parsed
        # See the identical guard/comment on the rain branch above -- this
        # call was already unguarded before rain existed; fixed here too
        # since it's the same exposure, same file, same fix.
        try:
            prices = parse_market_price(m)
        except (ValueError, TypeError) as exc:
            _log.warning(
                "consistency[%s]: malformed price fields (%s) — excluded from grouping",
                ticker,
                exc,
            )
            continue
        # F5: skip markets with no real quote — implied_prob=0 from a stale/empty book
        # would generate spurious violations
        if not prices.get("has_quote", False):
            continue
        implied = prices["implied_prob"]
        yes_bid = prices["yes_bid"]
        yes_ask = prices["yes_ask"]

        key = (series, date_str)
        # Store bid/ask alongside implied prob so find_violations can compute
        # R27: real arb edge = sell_bid − buy_ask (not mid − mid). is_shadow/
        # unit set explicitly (False/"°") -- see the rain branch's identical
        # per-entry tagging above for why this isn't re-derived from the
        # group key's shape.
        groups.setdefault(key, []).append(
            (m, cond_type, threshold, implied, yes_bid, yes_ask, False, "°")
        )

    return groups


def find_violations(markets: list[dict]) -> list[Violation]:
    """
    Scan a list of markets and return all monotonicity violations.
    Only checks markets that have real quotes (implied_prob > 0).

    Every violation whose group key is a rain event key (a 4-tuple tagged
    "RAIN", from market_implied_rain_event_key() -- see _group_markets) is
    returned with is_shadow=True. Callers that auto-place corrective trades
    MUST check this flag and skip placement for shadow violations -- this
    is a deliberate first pass (rain's ladder monotonicity has never been
    checked against live prices before), not yet graduated to live
    placement. See backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE
    CHECK STILL BLANKET-EXCLUDES KXRAIN*M".
    """
    groups = _group_markets(markets)
    violations: list[Violation] = []

    for entries in groups.values():
        # is_shadow/unit are set per-entry at append time in _group_markets
        # (not re-derived here from the group key's shape) -- every entry in
        # one group shares the same value by construction (grouping itself
        # already partitions rain from temperature), so taking it from any
        # single entry is safe.
        # Split into above and below groups; carry bid/ask for R27 edge calc.
        above = [
            (m, t, p, bid, ask, shadow, unit)
            for m, ct, t, p, bid, ask, shadow, unit in entries
            if ct == "above" and p > 0
        ]
        below = [
            (m, t, p, bid, ask, shadow, unit)
            for m, ct, t, p, bid, ask, shadow, unit in entries
            if ct == "below" and p > 0
        ]

        # Above: P(high > X) should DECREASE as X increases
        # Sort by threshold ascending
        above.sort(key=lambda x: x[1])
        for i in range(len(above) - 1):
            m_lo, t_lo, p_lo, bid_lo, ask_lo, shadow, unit = above[i]
            m_hi, t_hi, p_hi, bid_hi, ask_hi, _shadow_hi, _unit_hi = above[i + 1]
            if p_hi > p_lo + 0.01:  # P(> higher threshold) > P(> lower) — violation
                # Opus-review-caught: a market with NO real ask (or NO real
                # bid) on the leg this arb needs still has has_quote=True
                # (parse_market_price treats a one-sided book as a quote --
                # mid falls back to yes_bid) and yes_ask/yes_bid=0.0, which
                # made `edge = bid_hi - 0` compute a fabricated "guaranteed"
                # profit against a leg with no real liquidity to trade
                # into/out of. Both legs need a REAL two-sided quote to be
                # tradeable at all -- reproduced live against a realistic
                # thin rain ladder before this guard existed. Applies to
                # both market families; disproportionately matters for rain,
                # whose monthly ladders are typically much thinner than
                # temperature's daily ones, and this shadow pass exists
                # specifically to give a clean signal for that graduation
                # decision.
                if ask_lo <= 0 or bid_hi <= 0:
                    continue
                # R27: arb = BUY low-threshold (pay ask_lo), SELL high-threshold
                # (receive bid_hi).  Use actual bid/ask, not midpoints.
                edge = bid_hi - ask_lo
                violations.append(
                    Violation(
                        buy_ticker=m_lo["ticker"],
                        sell_ticker=m_hi["ticker"],
                        buy_prob=p_lo,
                        sell_prob=p_hi,
                        guaranteed_edge=edge,
                        description=(
                            f"P(>{t_hi:g}{unit}) = {p_hi:.0%} > P(>{t_lo:g}{unit}) = {p_lo:.0%} — "
                            f"IMPOSSIBLE: higher threshold can't have higher probability"
                        ),
                        is_shadow=shadow,
                    )
                )

        # Below: P(high < X) should INCREASE as X increases
        below.sort(key=lambda x: x[1])
        for i in range(len(below) - 1):
            m_lo, t_lo, p_lo, bid_lo, ask_lo, shadow, unit = below[i]
            m_hi, t_hi, p_hi, bid_hi, ask_hi, _shadow_hi, _unit_hi = below[i + 1]
            if p_lo > p_hi + 0.01:  # P(< lower threshold) > P(< higher) — violation
                # Same zero-quote-leg guard as the "above" loop above.
                if ask_hi <= 0 or bid_lo <= 0:
                    continue
                # R27: arb = BUY high-threshold (pay ask_hi), SELL low-threshold
                # (receive bid_lo).
                edge = bid_lo - ask_hi
                violations.append(
                    Violation(
                        buy_ticker=m_hi["ticker"],
                        sell_ticker=m_lo["ticker"],
                        buy_prob=p_hi,
                        sell_prob=p_lo,
                        guaranteed_edge=edge,
                        description=(
                            f"P(<{t_lo:g}{unit}) = {p_lo:.0%} > P(<{t_hi:g}{unit}) = {p_hi:.0%} — "
                            f"IMPOSSIBLE: lower threshold can't have higher 'below' probability"
                        ),
                        is_shadow=shadow,
                    )
                )

    violations.sort(key=lambda v: v.guaranteed_edge, reverse=True)
    # M-16: remove violations with non-positive edge — wide spreads produce negative
    # guaranteed_edge (bid_hi - ask_lo < 0) which is not a real arb opportunity.
    real_violations = [v for v in violations if v.guaranteed_edge > 0]
    return real_violations
