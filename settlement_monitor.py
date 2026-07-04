"""
METAR Settlement Lag Monitor — Phase D: Settlement & Monitoring.

Runs from 5 PM to 7 PM local time for each city, checking METAR every 5 minutes.
When METAR confirms the day's high temp outcome, writes a settlement signal.
The main cron loop picks up these signals on next cycle.

Run: python main.py settlement-monitor
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import metar as _metar
from safe_io import project_root as _project_root
from weather_markets import _CITY_TZ

_log = logging.getLogger(__name__)

_SIGNALS_PATH = _project_root() / "data" / "settlement_signals.json"
_SIGNALS_PATH.parent.mkdir(exist_ok=True)

# Short code (this module's convention) → full city name (metar.py's and
# weather_markets.py's convention) — the only hand-maintained mapping needed
# now; station/tz are derived below instead of duplicated a third time. A
# stale/mismatched entry here raises KeyError at import time rather than
# silently drifting (the exact failure mode that let a stale Kalshi ticker
# and a short-code/full-name key mismatch both go unnoticed elsewhere this
# same week — see mos.py and KNOWN_WEATHER_SERIES's KXLOWTLAX fix).
_SHORT_CODE_TO_CITY: dict[str, str] = {
    "NYC": "NYC",
    "MIA": "Miami",
    "CHI": "Chicago",
    "LAX": "LA",
    "DAL": "Dallas",
    "BOS": "Boston",
    "PHX": "Phoenix",
    "SEA": "Seattle",
    "DEN": "Denver",
    "ATL": "Atlanta",
    "AUS": "Austin",
    "DC": "Washington",
    "PHI": "Philadelphia",
    "OKC": "OklahomaCity",
    "SFO": "SanFrancisco",
    "MSP": "Minneapolis",
    "HOU": "Houston",
    "SAT": "SanAntonio",
    "LV": "LasVegas",
    "NOLA": "NewOrleans",
}

# Cities and their METAR stations + timezones — derived from metar.py's and
# weather_markets.py's canonical maps (single source of truth) instead of a
# third hand-typed copy.
# P3-8: expanded to all 18 traded cities (was 5); LV/NOLA added when the bot
# started tracking those markets, bringing the total to 20.
_MONITOR_CITIES = {
    code: {"station": _metar.MARKET_STATION_MAP[city], "tz": _CITY_TZ[city]}
    for code, city in _SHORT_CODE_TO_CITY.items()
}

# Kalshi series ticker prefix per city — NOT simply "KXHIGH" + city code
_CITY_SERIES_TICKER = {
    "NYC": "KXHIGHNY",
    "MIA": "KXHIGHMIA",
    "CHI": "KXHIGHCHI",
    "LAX": "KXHIGHLAX",  # was KXHIGHLA — Kalshi retired that ticker
    "DAL": "KXHIGHTDAL",
    "BOS": "KXHIGHTBOS",  # was KXHIGHBOS — retired
    "PHX": "KXHIGHTPHX",
    "SEA": "KXHIGHTSEA",
    "DEN": "KXHIGHDEN",
    "ATL": "KXHIGHTATL",
    "AUS": "KXHIGHAUS",
    "DC": "KXHIGHTDC",
    "PHI": "KXHIGHPHIL",  # was KXHIGHTPHIL — retired
    "OKC": "KXHIGHTOKC",
    "SFO": "KXHIGHTSFO",
    "MSP": "KXHIGHTMIN",
    "HOU": "KXHIGHTHOU",
    "SAT": "KXHIGHTSATX",
    "LV": "KXHIGHTLV",
    "NOLA": "KXHIGHTNOLA",
}

# Settlement lag monitoring window: 5 PM – 7 PM local
_MONITOR_START_HOUR = 17
_MONITOR_END_HOUR = 19
# Tighter margin for settlement lag (1°F vs 3°F for day-trade METAR)
_SETTLEMENT_MARGIN_F = 1.0
_POLL_INTERVAL_SECONDS = 300  # 5 minutes


def build_settlement_signal(
    ticker: str,
    city: str,
    outcome: str,
    confidence: float,
    current_temp_f: float,
    threshold_f: float,
) -> dict:
    """Build a settlement lag signal dict."""
    return {
        "ticker": ticker,
        "city": city,
        "outcome": outcome,
        "confidence": confidence,
        "current_temp_f": current_temp_f,
        "threshold_f": threshold_f,
        "created_at": datetime.now(UTC).isoformat(),
        "source": "metar_settlement_lag",
    }


def write_settlement_signals(signals: list[dict]) -> None:
    """Write signals list to the signals file (atomic write)."""
    import safe_io

    safe_io.atomic_write_json(
        {"signals": signals, "updated_at": datetime.now(UTC).isoformat()},
        _SIGNALS_PATH,
    )


def read_settlement_signals(max_age_minutes: int = 120) -> list[dict]:
    """
    Read active settlement signals, filtering out expired ones.

    Args:
        max_age_minutes: Discard signals older than this many minutes

    Returns:
        List of active signal dicts
    """
    if not _SIGNALS_PATH.exists():
        return []
    try:
        data = json.loads(_SIGNALS_PATH.read_text(encoding="utf-8"))
        signals = data.get("signals", [])
    except Exception:
        return []

    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=max_age_minutes)
    active = []
    for s in signals:
        try:
            created = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if created >= cutoff:
                active.append(s)
        except Exception:
            pass
    return active


def _check_between_settlement(
    current_temp_f: float,
    lower_f: float,
    upper_f: float,
) -> dict:
    """
    Determine settlement outcome for a between-bucket market.

    Returns a dict with keys: locked (bool), outcome (str|None),
    confidence (float).

    Lock logic (mirrors _metar_lock_in in weather_markets.py):
    • YES — temp is anywhere inside [lower, upper].  By 5-7 PM the daily
      high is almost certainly established; confidence scales with clearance
      from the nearest edge.
    • NO  — temp is outside by > (_SETTLEMENT_MARGIN_F + 1.0)°F from the
      nearest edge.  The extra 1°F guard prevents a premature NO when the
      reading is just below or above the bucket boundary.
    • Neither — temp is near the edge; outcome is still uncertain.

    Args:
        current_temp_f: Latest METAR temperature
        lower_f: Bucket lower bound (e.g. 66.5)
        upper_f: Bucket upper bound (e.g. 68.5)
    """
    if lower_f <= current_temp_f <= upper_f:
        # Inside the band → lock YES.  Clearance only affects confidence,
        # not the lock condition (consistent with _metar_lock_in).
        clearance = min(current_temp_f - lower_f, upper_f - current_temp_f)
        confidence = min(0.95, 0.70 + clearance * 0.05)
        return {"locked": True, "outcome": "yes", "confidence": confidence}

    # Outside the band.  Use (_SETTLEMENT_MARGIN_F + 1.0)°F guard to avoid
    # locking NO when the reading is just outside the bucket boundary.
    clearance = (
        current_temp_f - upper_f
        if current_temp_f > upper_f
        else lower_f - current_temp_f
    )
    if clearance >= _SETTLEMENT_MARGIN_F + 1.0:
        confidence = min(0.95, 0.60 + clearance * 0.03)
        return {"locked": True, "outcome": "no", "confidence": confidence}

    return {"locked": False, "outcome": None, "confidence": 0.0}


def check_city_settlement(city: str, active_tickers: list[dict]) -> list[dict]:
    """
    Check METAR for a city and return any new settlement signals.

    Args:
        city: City code (e.g. "NYC")
        active_tickers: List of active market dicts.  Each dict must contain
            either:
              • direction="above"|"below" + threshold (T-ticker markets), or
              • direction="between" + lower + upper   (B-ticker markets)

    Returns:
        List of new settlement signal dicts
    """
    from metar import check_metar_lockout, fetch_metar

    config = _MONITOR_CITIES.get(city)
    if not config:
        return []

    obs = fetch_metar(config["station"])
    if not obs:
        return []

    new_signals = []
    for market in active_tickers:
        direction = market.get("direction", "above")

        if direction == "between":
            lower_f = float(market.get("lower", 0))
            upper_f = float(market.get("upper", 0))
            lockout = _check_between_settlement(obs["current_temp_f"], lower_f, upper_f)
            if lockout["locked"]:
                center_f = (lower_f + upper_f) / 2
                signal = build_settlement_signal(
                    ticker=market["ticker"],
                    city=city,
                    outcome=lockout["outcome"],
                    confidence=lockout["confidence"],
                    current_temp_f=obs["current_temp_f"],
                    threshold_f=center_f,
                )
                new_signals.append(signal)
                _log.info(
                    "SETTLEMENT LAG signal: %s → %s (conf=%.0f%%) — temp %.1f°F vs bucket [%.1f, %.1f]°F",
                    market["ticker"],
                    lockout["outcome"],
                    lockout["confidence"] * 100,
                    obs["current_temp_f"],
                    lower_f,
                    upper_f,
                )
            continue

        # T-ticker (above / below) — original path
        if market.get("threshold") is None:
            continue
        threshold_f = float(market["threshold"])

        lockout = check_metar_lockout(
            current_temp_f=obs["current_temp_f"],
            threshold_f=threshold_f,
            direction=direction,
            obs_time=obs["obs_time"],
            city_tz=config["tz"],
            margin_f=_SETTLEMENT_MARGIN_F,
        )
        if lockout["locked"]:
            signal = build_settlement_signal(
                ticker=market["ticker"],
                city=city,
                outcome=lockout["outcome"],
                confidence=lockout["confidence"],
                current_temp_f=obs["current_temp_f"],
                threshold_f=threshold_f,
            )
            new_signals.append(signal)
            _log.info(
                "SETTLEMENT LAG signal: %s → %s (conf=%.0f%%) — temp %.1f°F vs threshold %.1f°F",
                market["ticker"],
                lockout["outcome"],
                lockout["confidence"] * 100,
                obs["current_temp_f"],
                threshold_f,
            )

    return new_signals


def run_settlement_monitor(client, duration_minutes: int = 120) -> None:
    """
    Run the settlement lag monitoring loop.

    Polls METAR every _POLL_INTERVAL_SECONDS seconds, writing signals for any
    markets where the outcome has been confirmed.

    Args:
        client: Kalshi API client (for fetching active markets)
        duration_minutes: How long to run (default 2 hours)
    """
    _log.info("Settlement lag monitor starting (duration=%dmin)", duration_minutes)
    end_time = datetime.now(UTC) + timedelta(minutes=duration_minutes)

    # P3-2: seed in-memory state from the signals file so a restart during the
    # settlement window doesn't re-fire signals that were already written.
    existing_signals = read_settlement_signals(max_age_minutes=120)
    all_signals: list[dict] = list(existing_signals)
    signalled_tickers: set[str] = {s["ticker"] for s in existing_signals}
    if signalled_tickers:
        _log.info(
            "Settlement lag monitor: restored %d signal(s) from disk",
            len(signalled_tickers),
        )

    while datetime.now(UTC) < end_time:
        for city in _MONITOR_CITIES:
            try:
                city_tz = _MONITOR_CITIES[city]["tz"]
                local_now = datetime.now(ZoneInfo(city_tz))
                if not (_MONITOR_START_HOUR <= local_now.hour < _MONITOR_END_HOUR):
                    continue

                active_tickers: list[dict] = []
                try:
                    markets = client.get_markets(
                        series_ticker=_CITY_SERIES_TICKER[city]
                    )
                    for m in markets or []:
                        if m.get("status") == "open":
                            ticker = m.get("ticker", "")
                            subtitle = m.get("subtitle", "")

                            # ── B-ticker (between-bucket) ─────────────────
                            # Detect from the ticker suffix, not the subtitle.
                            # Subtitle keywords ("above"/"below") are absent
                            # for between markets, so subtitle-based parsing
                            # would silently mis-classify these as "below".
                            b_match = re.search(r"-B(\d+(?:\.\d+)?)$", ticker.upper())
                            if b_match:
                                center = float(b_match.group(1))
                                if not (-60.0 <= center <= 130.0):
                                    _log.debug(
                                        "settlement_monitor: implausible B-ticker "
                                        "center %.1f from %r — skipping",
                                        center,
                                        ticker,
                                    )
                                    continue
                                # Kalshi between-buckets are 2°F wide, centered
                                # on the ticker value (see _parse_market_condition).
                                active_tickers.append(
                                    {
                                        "ticker": ticker,
                                        "direction": "between",
                                        "lower": center - 1.0,
                                        "upper": center + 1.0,
                                        "threshold": None,
                                    }
                                )
                                continue

                            # ── T-ticker (above / below) ──────────────────
                            # R36: capture optional decimal component so
                            # subtitles like "above 80.5°F" parse correctly.
                            match = re.search(r"(\d+(?:\.\d+)?)", subtitle)
                            if match:
                                threshold = float(match.group(1))
                                # Plausibility guard: reject obviously wrong
                                # parses (e.g. year digits from the ticker).
                                if not (-60.0 <= threshold <= 130.0):
                                    _log.debug(
                                        "settlement_monitor: implausible threshold "
                                        "%.1f from subtitle %r — skipping",
                                        threshold,
                                        subtitle,
                                    )
                                    continue
                                direction = (
                                    "above" if "above" in subtitle.lower() else "below"
                                )
                                active_tickers.append(
                                    {
                                        "ticker": ticker,
                                        "threshold": threshold,
                                        "direction": direction,
                                    }
                                )
                except Exception as exc:
                    _log.debug("settlement_monitor: market fetch for %s: %s", city, exc)

                new = check_city_settlement(city, active_tickers)
                for sig in new:
                    if sig["ticker"] not in signalled_tickers:
                        all_signals.append(sig)
                        signalled_tickers.add(sig["ticker"])
            except Exception as exc:
                _log.debug("settlement_monitor: %s error: %s", city, exc)

        if all_signals:
            write_settlement_signals(all_signals)

        remaining = (end_time - datetime.now(UTC)).total_seconds()
        time.sleep(min(_POLL_INTERVAL_SECONDS, max(0, remaining)))

    _log.info("Settlement lag monitor complete. %d signals written.", len(all_signals))
