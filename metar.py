"""
METAR same-day lock-in strategy.
After ~2 PM local time, if the daily high has clearly already peaked above/below
the Kalshi threshold, the outcome is near-certain.
Reported win rate: 85-90%.
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter, Retry

_log = logging.getLogger(__name__)

_METAR_URL = "https://aviationweather.gov/api/data/metar"
_LOCK_IN_HOUR = 14  # 2 PM local — earliest lock-in time
_LOCK_IN_CONFIDENCE = 0.90  # probability to assign to locked outcome

_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]
        )
    ),
)


def fetch_metar(station: str) -> dict | None:
    """
    Fetch the most recent METAR observation for a station.

    Returns:
        dict with keys: current_temp_f, station, obs_time (datetime UTC)
        or None on failure
    """
    try:
        resp = _session.get(
            _METAR_URL,
            params={"ids": station.upper(), "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log.debug("fetch_metar(%s): %s", station, exc)
        return None

    if not data:
        return None

    obs = data[0]
    # Prefer tmpf (°F) if present, otherwise convert temp (°C)
    temp_f = obs.get("tmpf")
    if temp_f is None:
        temp_c = obs.get("temp")
        if temp_c is None:
            return None
        temp_f = float(temp_c) * 9 / 5 + 32
    else:
        temp_f = float(temp_f)

    obs_time_str = obs.get("obsTime", "")
    try:
        obs_time = datetime.fromisoformat(obs_time_str.replace("Z", "+00:00"))
    except Exception:
        _log.warning("fetch_metar: missing/unparseable obsTime for %s", station)
        return None

    return {
        "current_temp_f": temp_f,
        "station": obs.get("icaoId", station),
        "obs_time": obs_time,
    }


def check_metar_lockout(
    current_temp_f: float,
    threshold_f: float,
    direction: str,
    obs_time: datetime,
    city_tz: str = "America/New_York",
    margin_f: float = 3.0,
) -> dict:
    """
    Determine if a METAR reading locks in the trade outcome.

    Lock-in conditions (ALL must be true):
    1. Local time >= 2 PM (temperature has had time to peak)
    2. Temperature is more than margin_f beyond the threshold

    Returns:
        dict: {locked: bool, outcome: "yes"|"no"|None, confidence: float, reason: str}
    """
    NOT_LOCKED = {"locked": False, "outcome": None, "confidence": 0.0, "reason": ""}

    # 1. Check local time
    try:
        from zoneinfo import ZoneInfo

        local_time = obs_time.astimezone(ZoneInfo(city_tz))
    except Exception:
        local_time = obs_time  # fallback to UTC
    if local_time.hour < _LOCK_IN_HOUR:
        return {
            **NOT_LOCKED,
            "reason": f"too early ({local_time.hour}h < {_LOCK_IN_HOUR}h local)",
        }

    # 2. Check temperature clearance
    if direction == "above":
        if current_temp_f >= threshold_f + margin_f:
            return {
                "locked": True,
                "outcome": "yes",
                "confidence": _LOCK_IN_CONFIDENCE,
                "reason": f"METAR {current_temp_f:.1f}°F >= threshold {threshold_f}°F + margin {margin_f}°F",
            }
        elif current_temp_f <= threshold_f - margin_f:
            return {
                "locked": True,
                "outcome": "no",
                "confidence": _LOCK_IN_CONFIDENCE,
                "reason": f"METAR {current_temp_f:.1f}°F <= threshold {threshold_f}°F - margin {margin_f}°F",
            }
    elif direction == "below":
        if current_temp_f <= threshold_f - margin_f:
            return {
                "locked": True,
                "outcome": "yes",
                "confidence": _LOCK_IN_CONFIDENCE,
                "reason": f"METAR {current_temp_f:.1f}°F <= threshold {threshold_f}°F - margin {margin_f}°F",
            }
        elif current_temp_f >= threshold_f + margin_f:
            return {
                "locked": True,
                "outcome": "no",
                "confidence": _LOCK_IN_CONFIDENCE,
                "reason": f"METAR {current_temp_f:.1f}°F >= threshold {threshold_f}°F + margin {margin_f}°F",
            }

    return {
        **NOT_LOCKED,
        "reason": f"temperature {current_temp_f:.1f}°F within margin of {threshold_f}°F",
    }
