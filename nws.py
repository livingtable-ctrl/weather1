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
from concurrent.futures import ThreadPoolExecutor as _TPE
from concurrent.futures import TimeoutError as _FutureTimeout
from datetime import date, datetime
from pathlib import Path

import requests

from circuit_breaker import CircuitBreaker
from schema_validator import validate_nws_response
from utils import normal_cdf
from utils import utc_today as _utc_today

socket.setdefaulttimeout(
    10
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
_precip_cache: dict = {}  # city -> (timestamp, precip_inches | None)

# Per-city lock prevents concurrent threads from fetching the same city observation
# simultaneously (thread-race fix: 4 workers × 5 cities = 20 fetches → 5 fetches)
_obs_locks: dict[str, threading.Lock] = {}
_obs_locks_mu = threading.Lock()

# Hard wall-clock timeout for obs HTTP calls — Windows SSL can hang past
# socket-level timeouts; a thread pool future gives a reliable deadline.
_OBS_WALL_SECS = 7.0
_obs_fetch_pool = _TPE(max_workers=4, thread_name_prefix="nws-obs")

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
        url, params=params, timeout=(5, 8)
    )  # (connect, read) — 5s cap on SSL handshake; #125: session reuses connections
    _elapsed = time.perf_counter() - _t0
    # #108: warn on slow NWS responses
    if _elapsed > 5:
        _log.warning("NWS API slow: %.1fs for %s", _elapsed, url)
    resp.raise_for_status()
    return resp.json()


def _get_obs(url: str) -> dict:
    """_get with a hard wall-clock deadline for observation endpoints.

    Windows SSL can hang indefinitely past socket-level timeouts. Submitting
    to a thread pool and calling .result(timeout=N) gives a reliable deadline
    regardless of OS-level SSL stalls.
    """
    try:
        return _obs_fetch_pool.submit(_get, url).result(timeout=_OBS_WALL_SECS)
    except _FutureTimeout:
        _log.warning("NWS obs wall-clock timeout (%.0fs) for %s", _OBS_WALL_SECS, url)
        raise TimeoutError(f"wall-clock timeout on {url}")


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


def fetch_nbm_forecast(city: str, coords: tuple, target_date: date) -> dict | None:
    """
    Return NBM high/low for a specific date via the NWS gridpoints API.

    NBM (National Blend of Models) is NOAA's official multi-model consensus —
    more accurate than raw GFS/ICON for days 1–7 and has no rate limits for
    reasonable use. This is the same data source as get_nws_daily_forecast()
    but returns a flat {"high_f", "low_f"} dict for easy use as a fallback.

    Returns {"high_f": float | None, "low_f": float | None} or None if
    the NWS circuit is open or the date is not in the forecast window.
    """
    daily = get_nws_daily_forecast(city, coords)
    if not daily:
        return None
    target_str = target_date.isoformat()
    day = daily.get(target_str)
    if not day:
        return None
    high = day.get("high")
    low = day.get("low")
    if high is None and low is None:
        return None
    return {
        "high_f": float(high) if high is not None else None,
        "low_f": float(low) if low is not None else None,
    }


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
    # E4: reject implausible NWS forecast temperatures before feeding CDF
    if not (-60.0 <= float(temp) <= 130.0):
        _log.warning("NWS forecast temp out of range for %s: %s°F", city, temp)
        return None

    # NWS is calibrated — use tighter sigma than raw ensemble.
    # Same-day: NWS high/low is near-certain (1°F); tighten significantly.
    days_out = (target_date - _utc_today()).days
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

            data = _get_obs(f"{NWS_BASE}/stations/{station_id}/observations/latest")
            props = data.get("properties", {})
            temp_c = (props.get("temperature") or {}).get("value")
            if temp_c is None:
                return None
            temp_f = temp_c * 9 / 5 + 32
            # E4: reject implausible observation temperatures before use
            if not (-60.0 <= temp_f <= 130.0):
                _log.warning(
                    "NWS observation temp out of range for %s: %.1f°F", city, temp_f
                )
                return None
            obs = {
                "temp_f": temp_f,
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
    Cached for OBS_TTL seconds. Thread-safe via per-city lock. Circuit-broken.
    """
    if _nws_cb.is_open():
        _log.warning("NWS circuit open — skipping precip obs for %s", city)
        return None

    now = time.time()
    if city in _precip_cache:
        cached_at, val = _precip_cache[city]
        if now - cached_at < OBS_TTL:
            return val

    with _get_obs_lock(city):
        try:
            now = time.time()
            if city in _precip_cache:
                cached_at, val = _precip_cache[city]
                if now - cached_at < OBS_TTL:
                    return val

            lat, lon, _ = coords
            station_id = _get_obs_station(lat, lon)
            if not station_id:
                return None

            data = _get_obs(f"{NWS_BASE}/stations/{station_id}/observations/latest")
            props = data.get("properties", {})
            p1h = (props.get("precipitationLastHour") or {}).get("value")
            if p1h is not None:
                result = round(float(p1h) / 25.4, 4)
                _precip_cache[city] = (time.time(), result)
                _nws_cb.record_success()
                return result
            p6h = (props.get("precipitationLast6Hours") or {}).get("value")
            if p6h is not None:
                result = round(float(p6h) / 6 / 25.4, 4)
                _precip_cache[city] = (time.time(), result)
                _nws_cb.record_success()
                return result
            _nws_cb.record_success()
            return None
        except Exception as exc:
            _nws_cb.record_failure()
            _log.warning("NWS precip obs failed for %s: %s", city, exc)
            return None


def obs_prob(obs: dict, condition: dict) -> float:
    """
    Convert a live observation to a probability.
    Uses sigma=3.5 — a midday temperature reading is not the final daily
    high/low; intraday spread is 3-5°F and sigma=1.0 produced near-binary
    probabilities (2%/98%) that devastated Brier scores when outcome differed.
    """
    temp = obs["temp_f"]
    # Realistic intraday uncertainty: matches historical daily-high/low spread.
    sigma = 3.5

    if condition["type"] == "above":
        return 1.0 - normal_cdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "below":
        return normal_cdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "between":
        lower = condition["lower"]
        upper = condition["upper"]
        # Use realistic sigma for "between" markets.  The prior sigma=0.25 when
        # the temp is inside the bucket assumed the obs confirmed the daily high,
        # but the daily high often moves 3-5°F after a midday reading.  Use
        # sigma=3.5 (matching historical forecast uncertainty) so the obs gives
        # a calibrated ~11% probability when centered, not a misleading 95%.
        return normal_cdf(upper, temp, 3.5) - normal_cdf(lower, temp, 3.5)
    return 0.0
