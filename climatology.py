"""
Historical climatology from Open-Meteo archive API.
Fetches 30 years of daily high/low for each city and caches to disk.
Used as a baseline probability before forecast skill is considered.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import date
from pathlib import Path

import requests

import safe_io
from circuit_breaker import CircuitBreaker as _CircuitBreaker
from utils import prob_threshold as _prob_threshold

_log = logging.getLogger(__name__)
_clim_cb = _CircuitBreaker("climatology", failure_threshold=5, recovery_timeout=300)

DATA_DIR = Path(__file__).parent / "data"

# #125: shared session for connection pooling
_session = requests.Session()
DATA_DIR.mkdir(exist_ok=True)

ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"
HISTORY_YEARS = 30
WINDOW_DAYS = 21  # default ±21 calendar days across all years
# Shoulder months: tighten window to avoid smearing seasonal transitions
SHOULDER_MONTHS = {3, 4, 5, 9, 10}  # Mar/Apr/May/Sep/Oct
SHOULDER_WINDOW_DAYS = 14
CACHE_MAX_AGE = 365 * 24 * 3600  # refresh cache if older than 1 year


def _cache_path(city: str) -> Path:
    return DATA_DIR / f"climate_{city}.json"


def _cache_is_stale(cache: Path) -> bool:
    """Return True if the cache file is missing or older than CACHE_MAX_AGE seconds."""
    if not cache.exists():
        return True
    return (time.time() - cache.stat().st_mtime) > CACHE_MAX_AGE


# In-memory cache so repeated calls within one process (e.g. 5 markets for NYC
# all calling climatological_prob) only hit disk once per city per run.
_MEM_CACHE: dict[str, dict] = {}


def fetch_historical(city: str, coords: tuple, force: bool = False) -> dict | None:
    """
    Download 30 years of daily high/low for a city and cache to disk.
    Auto-refreshes if the cache is older than 1 year.
    Returns dict with keys: dates, highs, lows.
    """
    if not force and city in _MEM_CACHE:
        return _MEM_CACHE[city]

    cache = _cache_path(city)
    if cache.exists() and not force and not _cache_is_stale(cache):
        with open(cache) as f:
            data = json.load(f)
        _MEM_CACHE[city] = data
        return data

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
        resp = _session.get(ARCHIVE_BASE, params=params, timeout=60)  # #125
        resp.raise_for_status()
        daily = resp.json().get("daily", {})
        data = {
            "dates": daily.get("time", []),
            "highs": daily.get("temperature_2m_max", []),
            "lows": daily.get("temperature_2m_min", []),
        }
        safe_io.atomic_write_json(data, cache)
        _MEM_CACHE[city] = data
        return data
    except Exception as exc:
        _log.warning("fetch_historical: API failed for %s: %s", city, exc)
        # #4: If download fails, return stale cache but warn if it's very old
        if cache.exists():
            cache_age_days = (time.time() - cache.stat().st_mtime) / 86400
            if cache_age_days > 365:
                _log.warning(
                    "fetch_historical: cache for %s is %.0f days old "
                    "(API unavailable); forecast accuracy may be reduced.",
                    city,
                    cache_age_days,
                )
            with open(cache) as f:
                data = json.load(f)
            _MEM_CACHE[city] = data
            return data
        _log.warning(
            "fetch_historical: API failed for %s and no cache exists — returning None",
            city,
        )
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
    if _clim_cb.is_open():
        _log.warning("Climatology circuit open — skipping for %s", city)
        return None
    try:
        result = _climatological_prob_inner(city, coords, target_date, condition)
        _clim_cb.record_success()
        return result
    except Exception as exc:
        _clim_cb.record_failure()
        _log.warning("Climatology prob failed for %s: %s", city, exc)
        return None


def _climatological_prob_inner(
    city: str, coords: tuple, target_date: date, condition: dict
) -> float | None:
    data = fetch_historical(city, coords)
    if not data:
        return None

    # Use a tighter window during shoulder months to avoid smearing transitions
    window = (
        SHOULDER_WINDOW_DAYS if target_date.month in SHOULDER_MONTHS else WINDOW_DAYS
    )

    target_doy = target_date.timetuple().tm_yday
    temps = []

    _n_dates = len(data["dates"])
    _n_highs = len(data["highs"])
    _n_lows = len(data["lows"])
    if _n_dates != _n_highs or _n_dates != _n_lows:
        _log.warning(
            "climatology: mismatched list lengths dates=%d highs=%d lows=%d for %s"
            " — truncating to shortest",
            _n_dates,
            _n_highs,
            _n_lows,
            city,
        )

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
        if diff <= window:
            temps.append(low if condition.get("var") == "min" else high)

    if len(temps) < 30:  # need enough data points to be meaningful
        return None

    if condition["type"] == "above":
        return sum(1 for t in temps if t > _prob_threshold(condition)) / len(temps)
    elif condition["type"] == "below":
        return sum(1 for t in temps if t < _prob_threshold(condition)) / len(temps)
    elif condition["type"] == "between":
        lo, hi = condition["lower"], condition["upper"]
        return sum(1 for t in temps if lo <= t <= hi) / len(temps)
    return None


def persistence_prob(
    condition_type: str,
    threshold_lo: float,
    threshold_hi: float | None,
    current_value: float,
    std_dev: float = 5.0,
) -> float | None:
    """
    #26: Persistence baseline — models tomorrow's temperature as
    N(current_value, std_dev) and returns P(value meets condition).

    condition_type: 'above', 'below', 'between'
    threshold_lo: lower (or sole) threshold
    threshold_hi: upper threshold (only used for 'between')
    current_value: today's observed temperature (°F)
    std_dev: assumed day-to-day persistence error (default 5°F)

    Returns probability in [0, 1], or None if inputs are invalid.
    """
    if current_value is None or threshold_lo is None:
        return None
    if std_dev <= 0:
        return None

    from utils import normal_cdf as _normal_cdf

    if condition_type == "above":
        return 1.0 - _normal_cdf(threshold_lo, current_value, std_dev)
    elif condition_type == "below":
        return _normal_cdf(threshold_lo, current_value, std_dev)
    elif condition_type == "between":
        if threshold_hi is None:
            return None
        p_hi = _normal_cdf(threshold_hi, current_value, std_dev)
        p_lo = _normal_cdf(threshold_lo, current_value, std_dev)
        return max(0.0, p_hi - p_lo)
    return None


# Restored 2026-07-12 -- silently lost in the 24559a7 mystery-revert (see
# backlog.txt); ported forward against current climatology.py (safe_io's
# atomic_write_json replaces the original's raw json.dump, matching this
# file's current write convention). NWS Day-3 temperature RMSE is empirically
# ~60% of climatological std. Applying this fraction converts raw variability
# into a calibrated forecast sigma -- independent of this bot's own settled-
# trade history, so it covers every city (including LasVegas/NewOrleans,
# which have too few settled trades for a learned-from-history sigma) from
# the moment the cache is built.
FORECAST_RMSE_FRACTION = 0.60
_SIGMA_FLOOR = 1.5  # never allow sigma < 1.5°F regardless of climate data

_SIGMA_CACHE_PATH = DATA_DIR / "forecast_sigma.json"
_SIGMA_CACHE_AGE = 30 * 24 * 3600  # refresh monthly
_sigma_mem_cache: dict = {}


def compute_sigma_from_climate(
    city: str, coords: tuple, var: str = "max"
) -> dict[int, float]:
    """
    Compute per-month forecast sigma (°F) from 30yr climate archive for one city.
    Returns {month: sigma} for months 1-12 that have enough data (>= 30 points).
    Empty dict on data error.
    """
    data = fetch_historical(city, coords)
    if not data:
        return {}

    key = "highs" if var == "max" else "lows"
    by_month: dict[int, list[float]] = {m: [] for m in range(1, 13)}

    for date_str, val in zip(data["dates"], data[key]):
        if val is None:
            continue
        try:
            m = date.fromisoformat(date_str).month
            by_month[m].append(val)
        except ValueError:
            continue

    result: dict[int, float] = {}
    for m, vals in by_month.items():
        if len(vals) >= 30:
            std = statistics.stdev(vals)
            result[m] = round(max(_SIGMA_FLOOR, std * FORECAST_RMSE_FRACTION), 2)
    return result


def load_all_sigmas(city_coords: dict, force: bool = False) -> dict:
    """
    Return per-city, per-month forecast sigmas computed from 30yr climate archive.
    Structure: {city: {"max": {month_str: sigma}, "min": {month_str: sigma}}}
    Cached to data/forecast_sigma.json, refreshed monthly.
    """
    global _sigma_mem_cache
    if _sigma_mem_cache and not force:
        return _sigma_mem_cache

    if not force and _SIGMA_CACHE_PATH.exists():
        age = time.time() - _SIGMA_CACHE_PATH.stat().st_mtime
        if age < _SIGMA_CACHE_AGE:
            with open(_SIGMA_CACHE_PATH) as f:
                _sigma_mem_cache = json.load(f)
            return _sigma_mem_cache

    result: dict = {}
    for city, coords in city_coords.items():
        result[city] = {
            "max": {
                str(k): v
                for k, v in compute_sigma_from_climate(city, coords, var="max").items()
            },
            "min": {
                str(k): v
                for k, v in compute_sigma_from_climate(city, coords, var="min").items()
            },
        }

    try:
        safe_io.atomic_write_json(result, _SIGMA_CACHE_PATH)
    except Exception as e:
        _log.warning("Could not write forecast_sigma.json: %s", e)

    _sigma_mem_cache = result
    return result


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

    # Recompute sigma cache if stale or missing (runs after climate data is fresh)
    if not _SIGMA_CACHE_PATH.exists() or (
        time.time() - _SIGMA_CACHE_PATH.stat().st_mtime > _SIGMA_CACHE_AGE
    ):
        print("  Computing per-city forecast sigma from climate archive...", flush=True)
        load_all_sigmas(city_coords, force=True)
