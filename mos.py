"""
NOAA MOS (Model Output Statistics) via Iowa Environmental Mesonet API.
Station-specific post-processed forecasts — same ASOS stations Kalshi settles on.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import requests
from requests.adapters import HTTPAdapter, Retry

from utils import utc_today as _utc_today

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
    "DEN": "KDEN",  # B3: Denver added — mountain terrain makes MOS post-processing especially valuable
}

# MOS verified RMSE by days_out (°F). Used as sigma in probability calculations
# instead of the generic _forecast_uncertainty() table. Source: NOAA MOS verification.
MOS_SIGMA: dict[str, dict[int, float]] = {
    "GFS": {0: 2.0, 1: 2.5, 2: 3.2, 3: 4.0, 4: 5.0, 5: 5.5},
    "NAM": {0: 1.8, 1: 2.3, 2: 3.0},  # NAM only reliable out to ~60h
}

# Shared session with retry
_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=1,  # was 3 — Retry(total=3) + timeout=10 → 43 s/call; total=1 caps at ~21 s
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
    ),
)


# In-process cache: (station, date_iso, model) → (result, monotonic_time).
# MOS updates every ~6 h; 1-hour TTL prevents redundant HTTP calls when
# cmd_cron / analyze_trade loop over many markets for the same cities.
_MOS_CACHE: dict[tuple, tuple[dict | None, float]] = {}
_MOS_CACHE_TTL = 3600  # 1 hour


def get_mos_station(city: str) -> str | None:
    """Return the ASOS station code for a city, or None if unknown."""
    return _CITY_STATION.get(city.upper())


def is_mos_cached(station: str, target_date: date | None) -> bool:
    """Return True if a fresh MOS cache entry exists for this station/date (no network call).

    Used by analyze_trade to skip the MOS fetch entirely when the pre-warm didn't
    cover this city/date, avoiding slow per-market network calls during the analysis
    phase.  Returns False if the cache entry is missing or has expired.
    """
    if not station or not target_date:
        return False
    date_str = (
        target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date)
    )
    now = time.monotonic()
    for model in ("NAM", "GFS"):
        key = (station.upper(), date_str, model)
        cached = _MOS_CACHE.get(key)
        if cached is not None and (now - cached[1]) < _MOS_CACHE_TTL:
            return True
    return False


_MOS_SPECIAL_CODES = frozenset(("M", "m", "T", "t", "", "N/A"))


def _parse_temp(value) -> float | None:
    """Parse MOS temperature field, handling ASOS special codes."""
    if value is None:
        return None
    s = str(value).strip()
    if s in _MOS_SPECIAL_CODES:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        _log.debug("Unparseable MOS temp value: %r", value)
        return None


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
          - min_temp_f: float | None, lowest temperature for the target date
          - n_hours: int, number of hourly rows found for that date
          - station: str
          - model: str
          - sigma: float, MOS-specific RMSE for this days_out (B1)
        or None on any failure.
    """
    if target_date is None:
        from datetime import UTC, datetime

        target_date = datetime.now(UTC).date() + timedelta(days=1)

    date_str = target_date.isoformat()

    # Check cache before hitting the network.
    _cache_key = (station.upper(), date_str, model.upper())
    _cached = _MOS_CACHE.get(_cache_key)
    if _cached is not None:
        _result, _ts = _cached
        if time.monotonic() - _ts < _MOS_CACHE_TTL:
            return _result

    try:
        resp = _session.get(
            _MOS_URL,
            params={"station": station.upper(), "model": model},
            timeout=(5, 10),  # (connect, read) — 5s cap on SSL handshake
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        _log.debug("fetch_mos(%s): %s", station, exc)
        _MOS_CACHE[_cache_key] = (None, time.monotonic())
        return None

    rows = payload.get("data", [])
    if not rows:
        _MOS_CACHE[_cache_key] = (None, time.monotonic())
        return None

    # Filter to rows on the target date (ftime starts with date_str)
    day_rows = [r for r in rows if str(r.get("ftime", "")).startswith(date_str)]
    if not day_rows:
        _MOS_CACHE[_cache_key] = (None, time.monotonic())
        return None

    temps: list[float] = [
        t for r in day_rows if (t := _parse_temp(r.get("tmp"))) is not None
    ]
    if not temps:
        _MOS_CACHE[_cache_key] = (None, time.monotonic())
        return None

    # B1: compute days_out and look up MOS-specific RMSE as sigma
    days_out = max(0, (target_date - _utc_today()).days)
    sigma_table = MOS_SIGMA.get(model.upper(), MOS_SIGMA["GFS"])
    max_key = max(sigma_table.keys())
    sigma = sigma_table.get(days_out, sigma_table[max_key])

    result = {
        "max_temp_f": float(max(temps)),
        "min_temp_f": float(min(temps)),
        "n_hours": len(day_rows),
        "station": station.upper(),
        "model": model,
        "sigma": sigma,
    }
    _MOS_CACHE[_cache_key] = (result, time.monotonic())
    return result


def fetch_mos_best(
    station: str,
    target_date: date | None = None,
) -> dict | None:
    """
    B2: Fetch MOS using the best available model for the given days_out.
    For days_out <= 1: try NAM first (higher resolution), fall back to GFS.
    For days_out >= 2: use GFS only (NAM is unreliable beyond ~60h).

    Returns the result dict from fetch_mos(), or None if all models fail.
    """
    if target_date is None:
        from datetime import UTC, datetime

        target_date = datetime.now(UTC).date() + timedelta(days=1)

    days_out = max(0, (target_date - _utc_today()).days)

    if days_out <= 1:
        # Try NAM first — tighter RMSE for same-day and next-day markets
        result = fetch_mos(station, target_date, model="NAM")
        if result is not None:
            return result

    # GFS fallback (or primary for days_out >= 2)
    return fetch_mos(station, target_date, model="GFS")
