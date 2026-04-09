"""
NOAA National Weather Service API integration.
Provides:
  - Official calibrated daily forecasts (up to 7 days)
  - Real-time hourly observations for same-day markets
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime

import requests

NWS_BASE = "https://api.weather.gov"
UA_HEADER = {"User-Agent": "kalshi-weather-predictor/1.0 (contact@example.com)"}
OBS_TTL = 600  # seconds — re-fetch observation if older than this

# In-memory caches
_gridpoint_cache: dict = {}
_station_cache: dict = {}
_forecast_cache: dict = {}
_obs_cache: dict = {}  # city -> (timestamp, observation_dict)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get(url: str, params: dict | None = None) -> dict:
    resp = requests.get(url, headers=UA_HEADER, params=params, timeout=15)
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
        data = _get(f"{NWS_BASE}/points/{lat},{lon}/observationStations")
        features = data.get("features", [])
        if not features:
            return None
        station_id = features[0]["properties"]["stationIdentifier"]
        _station_cache[key] = station_id
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

    lat, lon, _ = coords
    try:
        grid_id, gx, gy = _get_gridpoint(lat, lon)
        data = _get(f"{NWS_BASE}/gridpoints/{grid_id}/{gx},{gy}/forecast")
    except Exception:
        return {}

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
    forecast = get_nws_daily_forecast(city, coords)
    date_str = target_date.isoformat()
    day = forecast.get(date_str, {})

    var = condition.get("var", "max")
    temp = day.get("low") if var == "min" else day.get("high")
    if temp is None:
        return None

    # NWS is calibrated — use tighter sigma than raw ensemble
    days_out = (target_date - date.today()).days
    sigma = 2.0 if days_out <= 2 else 3.0 if days_out <= 5 else 4.0

    def ncdf(x, mu, s):
        return 0.5 * math.erfc((mu - x) / (s * math.sqrt(2)))

    if condition["type"] == "above":
        return 1.0 - ncdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "below":
        return ncdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "between":
        return ncdf(condition["upper"], temp, sigma) - ncdf(
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
    now = time.time()
    if city in _obs_cache:
        cached_at, obs = _obs_cache[city]
        if now - cached_at < OBS_TTL:
            return obs

    lat, lon, _ = coords
    station_id = _get_obs_station(lat, lon)
    if not station_id:
        return None

    try:
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
        _obs_cache[city] = (now, obs)
        return obs
    except Exception:
        return None


def obs_prob(obs: dict, condition: dict) -> float:
    """
    Convert a live observation to a probability.
    For same-day markets the temp is essentially known — use a very tight sigma.
    """
    temp = obs["temp_f"]
    sigma = 1.0  # near-certain once observed

    def ncdf(x, mu, s):
        return 0.5 * math.erfc((mu - x) / (s * math.sqrt(2)))

    if condition["type"] == "above":
        return 1.0 - ncdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "below":
        return ncdf(condition["threshold"], temp, sigma)
    elif condition["type"] == "between":
        return ncdf(condition["upper"], temp, sigma) - ncdf(
            condition["lower"], temp, sigma
        )
    return 0.0
