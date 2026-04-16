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
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

_log = logging.getLogger(__name__)

_SIGNALS_PATH = Path(__file__).parent / "data" / "settlement_signals.json"
_SIGNALS_PATH.parent.mkdir(exist_ok=True)

# Cities and their METAR stations + timezones
_MONITOR_CITIES = {
    "NYC": {"station": "KNYC", "tz": "America/New_York"},
    "MIA": {"station": "KMIA", "tz": "America/New_York"},
    "CHI": {"station": "KORD", "tz": "America/Chicago"},
    "LAX": {"station": "KLAX", "tz": "America/Los_Angeles"},
    "DAL": {"station": "KDFW", "tz": "America/Chicago"},
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
        data = json.loads(_SIGNALS_PATH.read_text())
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


def check_city_settlement(city: str, active_tickers: list[dict]) -> list[dict]:
    """
    Check METAR for a city and return any new settlement signals.

    Args:
        city: City code (e.g. "NYC")
        active_tickers: List of active market dicts with ticker, threshold, direction

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
        threshold_f = float(market.get("threshold", 0))
        direction = market.get("direction", "above")
        if not threshold_f:
            continue

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

    all_signals: list[dict] = []

    while datetime.now(UTC) < end_time:
        for city in _MONITOR_CITIES:
            try:
                active_tickers: list[dict] = []
                try:
                    markets = client.get_markets(series_ticker=f"KXHIGH{city}")
                    for m in markets or []:
                        if m.get("status") == "open":
                            ticker = m.get("ticker", "")
                            subtitle = m.get("subtitle", "")
                            import re

                            match = re.search(r"(\d+)", subtitle)
                            if match:
                                threshold = float(match.group(1))
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
                all_signals.extend(new)
            except Exception as exc:
                _log.debug("settlement_monitor: %s error: %s", city, exc)

        if all_signals:
            write_settlement_signals(all_signals)

        time.sleep(_POLL_INTERVAL_SECONDS)

    _log.info("Settlement lag monitor complete. %d signals written.", len(all_signals))
