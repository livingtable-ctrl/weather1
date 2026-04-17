"""
NOAA National Weather Service API integration.
Provides:
  - Official calibrated daily forecasts (up to 7 days)
  - Real-time hourly observations for same-day markets
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import date, datetime
from pathlib import Path

import requests

from circuit_breaker import CircuitBreaker
from schema_validator import validate_nws_response
from utils import normal_cdf

socket.setdefaulttimeout(
    25
)  # hard backstop — requests timeout unreliable on Windows SSL

_log = logging.getLogger(__name__)

_nws_cb = CircuitBreaker(name="nws", failure_threshold=3, recovery_timeout=180)

NWS_BASE = "https://api.weather.gov"
# #68: load User-Agent from env so it can be updated without a code change
_nws_ua = os.getenv("NWS_USER_AGENT", "kalshi-weather-predictor/1.0 (user@localhost)")
UA_HEADER = {"User-Agent": _nws_ua}
OBS_TTL = 600  # seconds — re-fetch observation if older than this

# #125: shared session for connection pooling
_session = requests.Session()
_session.headers.update(UA_HEADER)

# In-memory caches
_gridpoint_cache: dict = {}
_station_cache: dict = {}
_forecast_cache: dict = {}
_obs_cache: dict = {}  # city -> (timestamp, observation_dict)

# Per-city lock prevents concurrent threads from fetching the same city observation
# simultaneously (thread-race fix: 4 workers × 5 cities = 20 fetches → 5 fetches)
_obs_locks: dict[str, threading.Lock] = {}
_obs_locks_mu = threading.Lock()

# Persistent station-ID cache: station→coord mappings never change, so we can
# avoid the NWS /observationStations round-trip on subsequent process starts.
_STATION_CACHE_PATH = (
    Path(__file__).resolve().parent / "data" / ".nws_station_cache.json"
)


def _load_station_cache() -> None:
    """Load persisted station cache from disk into _station_cache."""
    try:
        if _STATION_CACHE_PATH.exists():
            raw = json.loads(_STATION_CACHE_PATH.read_text())
            # Keys are stored as "lat,lon" strings; convert back to tuples
            for k, v in raw.items():
                parts = k.split(",")
                _station_cache[(float(parts[0]), float(parts[1]))] = v
    except Exception as exc:
        _log.debug("nws: could not load station cache: %s", exc)


def _save_station_cache() -> None:
    """Persist station cache to disk (best-effort, never raises)."""
    try:
        _STATION_CACHE_PATH.parent.mkdir(exist_ok=True)
        serializable = {f"{k[0]},{k[1]}": v for k, v in _station_cache.items()}
        _STATION_CACHE_PATH.write_text(json.dumps(serializable))
    except Exception as exc:
        _log.debug("nws: could not save station cache: %s", exc)


def _get_obs_lock(city: str) -> threading.Lock:
    """Return (creating if needed) the per-city observation lock."""
    with _obs_locks_mu:
        if city not in _obs_locks:
            _obs_locks[city] = threading.Lock()
        return _obs_locks[city]


# Load persisted station cache at module import time
_load_station_cache()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get(url: str, params: dict | None = None) -> dict:
    _t0 = time.perf_counter()
    resp = _session.get(
        url, params=params, timeout=15
    )  # #125: session reuses connections
    _elapsed = time.perf_counter() - _t0
    # #108: warn on slow NWS responses
    if _elapsed > 5:
        _log.warning("NWS API slow: %.1fs for %s", _elapsed, url)
    resp.raise_for_status()
    return resp.json()


def _get_gridpoint(lat: float, lon: float) -> tuple[str, int, int]:
    key = (round(lat, 4), round(lon, 4))
    if key in _gridpoint_cache:
        return _gridpoint_cache[key]
    data = _get(f"{NWS_BASE}/points/{lat},{lon}")
    props = data["properties"]
    result = (props["gridId"], props["gridX"], props["gridY"])
    _gridpoint_cache[key] = result
    return result


def _get_obs_station(lat: float, lon: float) -> str | None:
    key = (round(lat, 4), round(lon, 4))
    if key in _station_cache:
        return _station_cache[key]
    try:
        # NWS API: get observationStations URL from /points response (direct sub-resource
        # path was removed in a later API version)
        points_data = _get(f"{NWS_BASE}/points/{lat},{lon}")
        obs_url = points_data.get("properties", {}).get("observationStations")
        if not obs_url:
            return None
        data = _get(obs_url)
        features = data.get("features", [])
        if not features:
            return None
        station_id = features[0]["properties"]["stationIdentifier"]
        _station_cache[key] = station_id
        _save_station_cache()  # persist so subsequent process starts skip this fetch
        return station_id
    except Exception:
        return None


# ── Official NWS daily forecast ───────────────────────────────────────────────


def get_nws_daily_forecast(city: str, coords: tuple) -> dict[str, dict]:
    """
    Fetch NWS official daily high/low forecast for a city.
    Returns dict keyed by ISO date string:
      {"2026-04-10": {"high": 65.0, "low": 48.0}, ...}

    NWS forecasts are professionally made and bias-corrected — they often
    outperform raw model output especially at 1-5 day range.
    """
    if city in _forecast_cache:
        return _forecast_cache[city]

    if _nws_cb.is_open():
        _log.warning("NWS circuit open — skipping daily forecast for %s", city)
        return {}

    lat, lon, _ = coords
    try:
        grid_id, gx, gy = _get_gridpoint(lat, lon)
        data = _get(f"{NWS_BASE}/gridpoints/{grid_id}/{gx},{gy}/forecast")
        _nws_cb.record_success()
    except Exception as exc:
        _nws_cb.record_failure()
        _log.warning("NWS daily forecast failed for %s: %s", city, exc)
        return {}

    validate_nws_response(data)
    periods = data.get("properties", {}).get("periods", [])
    result: dict[str, dict] = {}

    for period in periods:
        try:
            start = datetime.fromisoformat(period["startTime"])
            date_str = start.date().isoformat()
            temp = period.get("temperature")
            if temp is None:
                continue
            if date_str not in result:
                result[date_str] = {"high": None, "low": None}
            if period.get("isDaytime", True):
                result[date_str]["high"] = float(temp)
            else:
                result[date_str]["low"] = float(temp)
        except Exception:
            continue

    _forecast_cache[city] = result
    return result


def nws_prob(
    city: str, coords: tuple, target_date: date, condition: dict
) -> float | None:
    """
    Convert NWS forecast temperature to a probability using a narrow normal
    distribution (NWS forecasts are calibrated, so use tighter σ than raw models).
    """
    if _nws_cb.is_open():
        _log.warning("NWS circuit open — skipping forecast prob for %s", city)
        return None
    forecast = get_nws_daily_forecast(city, coords)
    date_str = target_date.isoformat()
    day = forecast.get(date_str, {})

    var = condition.get("var", "max")
    temp = day.get("low") if var == "min" else day.get("high")
    if temp is None:
        return None

    # NWS is calibrated — use tighter sigma than raw ensemble.
    # Same-day: NWS high/low is near-certain (1°F); tighten significantly.
    days_out = (target_date - date.today()).days
    if days_out <= 0:
        sigma = 1.0
    elif days_out <= 2:
        sigma = 2.0
    elif days_out <= 5:
        sigma = 3.0
    else:
        sigma = 4.0

    if condition["type"] == "above":
        return 1.0 - normal_cdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "below":
        return normal_cdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "between":
        return normal_cdf(condition["upper"], temp, sigma) - normal_cdf(
            condition["lower"], temp, sigma
        )
    return None


# ── Real-time observations ────────────────────────────────────────────────────


def get_live_observation(city: str, coords: tuple) -> dict | None:
    """
    Fetch the latest hourly observation for a city.
    Returns dict with temp_f, timestamp, description.
    Cached for OBS_TTL seconds to avoid hammering the API.
    """
    if _nws_cb.is_open():
        _log.warning("NWS circuit open — skipping observation for %s", city)
        return None

    # Fast path: check cache before acquiring lock
    now = time.time()
    if city in _obs_cache:
        cached_at, obs = _obs_cache[city]
        if now - cached_at < OBS_TTL:
            return obs

    # Per-city lock: only one thread fetches NWS for a given city at a time.
    # Other threads for the same city wait here, then return from cache.
    with _get_obs_lock(city):
        try:
            # Double-check inside lock — another thread may have just populated cache
            now = time.time()
            if city in _obs_cache:
                cached_at, obs = _obs_cache[city]
                if now - cached_at < OBS_TTL:
                    return obs

            lat, lon = coords[0], coords[1]
            station_id = _get_obs_station(lat, lon)
            if not station_id:
                return None

            data = _get(f"{NWS_BASE}/stations/{station_id}/observations/latest")
            props = data.get("properties", {})
            temp_c = (props.get("temperature") or {}).get("value")
            if temp_c is None:
                return None
            obs = {
                "temp_f": temp_c * 9 / 5 + 32,
                "timestamp": props.get("timestamp", ""),
                "description": props.get("textDescription", ""),
            }
            _obs_cache[city] = (time.time(), obs)
            _nws_cb.record_success()
            return obs
        except Exception as exc:
            _nws_cb.record_failure()
            _log.warning("NWS observation failed for %s: %s", city, exc)
            return None


def get_live_precip_obs(city: str, coords: tuple) -> float | None:
    """
    Fetch the latest observed precipitation (inches) from NWS for same-day markets.
    Uses precipitationLastHour, falling back to precipitationLast6Hours / 6.
    Returns None if unavailable or the station doesn't report precip.
    """
    lat, lon, _ = coords
    station_id = _get_obs_station(lat, lon)
    if not station_id:
        return None
    try:
        data = _get(f"{NWS_BASE}/stations/{station_id}/observations/latest")
        props = data.get("properties", {})
        # Try 1-hour precip first
        p1h = (props.get("precipitationLastHour") or {}).get("value")
        if p1h is not None:
            # NWS reports in mm; convert to inches
            return round(float(p1h) / 25.4, 4)
        # Fallback to 6-hour average
        p6h = (props.get("precipitationLast6Hours") or {}).get("value")
        if p6h is not None:
            return round(float(p6h) / 6 / 25.4, 4)
    except Exception:
        pass
    return None


def obs_prob(obs: dict, condition: dict) -> float:
    """
    Convert a live observation to a probability.
    For same-day markets the temp is essentially known — use a very tight sigma.
    """
    temp = obs["temp_f"]
    sigma = 1.0  # near-certain once observed

    if condition["type"] == "above":
        return 1.0 - normal_cdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "below":
        return normal_cdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "between":
        return normal_cdf(condition["upper"], temp, sigma) - normal_cdf(
            condition["lower"], temp, sigma
        )
    return 0.0
