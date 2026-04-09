"""
Historical climatology from Open-Meteo archive API.
Fetches 30 years of daily high/low for each city and caches to disk.
Used as a baseline probability before forecast skill is considered.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"
HISTORY_YEARS = 30
WINDOW_DAYS = 21  # ±21 calendar days across all years
CACHE_MAX_AGE = 365 * 24 * 3600  # refresh cache if older than 1 year


def _cache_path(city: str) -> Path:
    return DATA_DIR / f"climate_{city}.json"


def _cache_is_stale(cache: Path) -> bool:
    """Return True if the cache file is missing or older than CACHE_MAX_AGE seconds."""
    if not cache.exists():
        return True
    return (time.time() - cache.stat().st_mtime) > CACHE_MAX_AGE


def fetch_historical(city: str, coords: tuple, force: bool = False) -> dict | None:
    """
    Download 30 years of daily high/low for a city and cache to disk.
    Auto-refreshes if the cache is older than 1 year.
    Returns dict with keys: dates, highs, lows.
    """
    cache = _cache_path(city)
    if cache.exists() and not force and not _cache_is_stale(cache):
        with open(cache) as f:
            return json.load(f)

    lat, lon, tz = coords
    end_year = date.today().year - 1
    start_year = end_year - HISTORY_YEARS

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "timezone": tz,
    }
    try:
        resp = requests.get(ARCHIVE_BASE, params=params, timeout=60)
        resp.raise_for_status()
        daily = resp.json().get("daily", {})
        data = {
            "dates": daily.get("time", []),
            "highs": daily.get("temperature_2m_max", []),
            "lows": daily.get("temperature_2m_min", []),
        }
        with open(cache, "w") as f:
            json.dump(data, f)
        return data
    except Exception:
        # If download fails, return stale cache if available
        if cache.exists():
            with open(cache) as f:
                return json.load(f)
        return None


def climatological_prob(
    city: str, coords: tuple, target_date: date, condition: dict
) -> float | None:
    """
    Probability of the market condition based purely on historical observations.
    Uses a ±WINDOW_DAYS calendar window across 30 years (~1,260 data points).

    condition must include:
      type: "above" | "below" | "between"
      threshold: float  (for above/below)
      lower, upper: float  (for between)
      var: "max" | "min"  (which temperature to use)
    """
    data = fetch_historical(city, coords)
    if not data:
        return None

    target_doy = target_date.timetuple().tm_yday
    temps = []

    for date_str, high, low in zip(data["dates"], data["highs"], data["lows"]):
        if high is None or low is None:
            continue
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            continue
        d_doy = d.timetuple().tm_yday
        diff = abs(target_doy - d_doy)
        diff = min(diff, 365 - diff)  # handle year-boundary wrap
        if diff <= WINDOW_DAYS:
            temps.append(low if condition.get("var") == "min" else high)

    if len(temps) < 30:  # need enough data points to be meaningful
        return None

    if condition["type"] == "above":
        return sum(1 for t in temps if t > condition["threshold"]) / len(temps)
    elif condition["type"] == "below":
        return sum(1 for t in temps if t < condition["threshold"]) / len(temps)
    elif condition["type"] == "between":
        lo, hi = condition["lower"], condition["upper"]
        return sum(1 for t in temps if lo <= t <= hi) / len(temps)
    return None


def preload_all(city_coords: dict) -> None:
    """Fetch and cache historical data for all cities. Refreshes stale caches."""
    for city, coords in city_coords.items():
        cache = _cache_path(city)
        if not cache.exists():
            print(f"  Downloading 30yr climate history for {city}...", flush=True)
            fetch_historical(city, coords)
        elif _cache_is_stale(cache):
            print(f"  Refreshing climate history for {city} (>1yr old)...", flush=True)
            fetch_historical(city, coords, force=True)
