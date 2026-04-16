"""
NOAA MOS (Model Output Statistics) via Iowa Environmental Mesonet API.
Station-specific post-processed forecasts — same ASOS stations Kalshi settles on.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import requests
from requests.adapters import HTTPAdapter, Retry

_log = logging.getLogger(__name__)

# IEM MOS API endpoint
_MOS_URL = "https://mesonet.agron.iastate.edu/api/1/mos.json"

# ASOS station codes for each city (matches Kalshi settlement stations)
_CITY_STATION: dict[str, str] = {
    "NYC": "KNYC",
    "MIA": "KMIA",
    "CHI": "KORD",
    "LAX": "KLAX",
    "DAL": "KDFW",
}

# Shared session with retry
_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]
        )
    ),
)


def get_mos_station(city: str) -> str | None:
    """Return the ASOS station code for a city, or None if unknown."""
    return _CITY_STATION.get(city.upper())


def fetch_mos(
    station: str,
    target_date: date | None = None,
    model: str = "GFS",
) -> dict | None:
    """
    Fetch MOS forecast for a station from the IEM API.

    Args:
        station: ASOS station code (e.g. "KNYC")
        target_date: Date to get forecast for (default: tomorrow)
        model: MOS model ("GFS" or "NAM")

    Returns:
        dict with keys:
          - max_temp_f: float, highest temperature for the target date
          - n_hours: int, number of hourly rows found for that date
          - station: str
          - model: str
        or None on any failure.
    """
    if target_date is None:
        from datetime import UTC, datetime

        target_date = datetime.now(UTC).date() + timedelta(days=1)

    date_str = target_date.isoformat()

    try:
        resp = _session.get(
            _MOS_URL,
            params={"station": station.upper(), "model": model},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        _log.debug("fetch_mos(%s): %s", station, exc)
        return None

    rows = payload.get("data", [])
    if not rows:
        return None

    # Filter to rows on the target date (ftime starts with date_str)
    day_rows = [r for r in rows if str(r.get("ftime", "")).startswith(date_str)]
    if not day_rows:
        return None

    temps = [r["tmp"] for r in day_rows if r.get("tmp") is not None]
    if not temps:
        return None

    return {
        "max_temp_f": float(max(temps)),
        "n_hours": len(day_rows),
        "station": station.upper(),
        "model": model,
    }
