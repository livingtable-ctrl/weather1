"""
Fetch and analyze Kalshi weather prediction markets.
Compares market-implied probabilities with Open-Meteo forecast data.
"""

from __future__ import annotations

import logging
import os
import random
import re
import socket
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path

import requests

from calibration import load_city_weights as _load_city_weights
from calibration import load_seasonal_weights as _load_seasonal_weights
from circuit_breaker import CircuitBreaker
from climate_indices import get_enso_index, temperature_adjustment
from climatology import climatological_prob
from kalshi_client import KalshiClient, _request_with_retry
from nws import get_live_observation, nws_prob, obs_prob
from schema_validator import validate_forecast
from utils import KALSHI_FEE_RATE, MAX_DAYS_OUT, normal_cdf

socket.setdefaulttimeout(
    25
)  # hard backstop — requests timeout unreliable on Windows SSL

_log = logging.getLogger(__name__)

# Primary circuit breaker: 3-model daily forecast (FORECAST_BASE).
# Higher threshold + longer recovery because these are cached and precious.
_forecast_cb = CircuitBreaker(
    name="open_meteo_forecast", failure_threshold=6, recovery_timeout=6 * 3600
)
# Supplementary circuit breaker: ensemble spread, NBM, ECMWF high-res (ENSEMBLE_BASE).
# Failures here degrade quality but don't block primary signals.
_ensemble_cb = CircuitBreaker(
    name="open_meteo_ensemble", failure_threshold=4, recovery_timeout=6 * 3600
)

# ── Trading filters ───────────────────────────────────────────────────────────
# Only analyse markets expiring within this many days. Days 3-4 carry higher
# uncertainty but the horizon discount in edge_confidence() and Kelly sizing
# handle that automatically. Override via MAX_DAYS_OUT env var.

# Minimum combined volume + open_interest required to trade a market.
# Below this the market is effectively illiquid — fills are unreliable.
MIN_LIQUIDITY: int = 50

# Single source of truth for edge calculation logic version.
# Increment whenever kelly_fraction, bayesian_kelly_fraction, edge_confidence,
# or time_decay_edge logic changes, so outputs can be traced.
EDGE_CALC_VERSION = "v1.0"

# ── Open-Meteo (free, no API key) ────────────────────────────────────────────


def _load_city_coords() -> dict:
    """
    #119: Load city coordinates from data/cities.json so new cities can be added
    without modifying code. Falls back to hardcoded defaults if file is missing.
    """
    import json

    cities_path = Path(__file__).parent / "data" / "cities.json"
    if cities_path.exists():
        try:
            raw = json.loads(cities_path.read_text())
            return {
                city: tuple(coords)
                for city, coords in raw.items()
                if not city.startswith("_")  # skip _comment keys
            }
        except Exception:
            pass
    # Hardcoded fallback (exact settlement station coordinates)
    return {
        "NYC": (40.7789, -73.9692, "America/New_York"),
        "Chicago": (41.9803, -87.9090, "America/Chicago"),
        "LA": (34.0190, -118.2910, "America/Los_Angeles"),
        "Miami": (25.8175, -80.3164, "America/New_York"),
        "Boston": (42.3606, -71.0106, "America/New_York"),
        "Dallas": (32.8998, -97.0403, "America/Chicago"),
        "Phoenix": (33.4373, -112.0078, "America/Phoenix"),
        "Seattle": (47.4502, -122.3088, "America/Los_Angeles"),
        "Denver": (39.8561, -104.6737, "America/Denver"),
        "Atlanta": (33.6407, -84.4277, "America/New_York"),
    }


CITY_COORDS = _load_city_coords()

# Per-city static bias corrections (°F) — subtract from model forecast before
# computing probability. Positive = model runs warm; negative = model runs cold.
# Sources: Weather Edge MCP field data, NWS station comparison reports.
_STATION_BIAS: dict[str, float] = {
    "NYC": 1.0,  # KNYC: NWS gridpoint overshoots Central Park by ~1°F (warm)
    "MIA": 3.0,  # KMIA: GFS southern warm bias, confirmed via field research
    "DEN": 2.0,  # KDEN: Mountain terrain uncertainty, conservative correction
    "CHI": 0.5,  # KORD: Minor warm bias
    "DAL": 0.5,  # KDFW: GFS southern warm bias (minor)
    "LAX": 0.0,  # KLAX: No known systematic bias
}


def apply_station_bias(city: str, forecast_temp: float) -> float:
    """
    Apply per-city static bias correction to a model forecast temperature.
    Subtracts the known warm bias so probability calculations are centered
    on the station's actual expected temperature.

    Args:
        city: City code (e.g. "NYC", "MIA")
        forecast_temp: Raw model forecast in °F

    Returns:
        Bias-corrected temperature in °F (unchanged if city unknown)
    """
    bias = _STATION_BIAS.get(city.upper(), 0.0)
    return forecast_temp - bias


# City → timezone and METAR station (same as Kalshi settlement stations)
_CITY_TZ: dict[str, str] = {
    "NYC": "America/New_York",
    "MIA": "America/New_York",
    "CHI": "America/Chicago",
    "LAX": "America/Los_Angeles",
    "DAL": "America/Chicago",
    "DEN": "America/Denver",
}


def _metar_station_for_city(city: str) -> str | None:
    """Return the METAR/ASOS station for a city (matches Kalshi settlement)."""
    _MAP: dict[str, str] = {
        "NYC": "KNYC",
        "MIA": "KMIA",
        "CHI": "KORD",
        "LAX": "KLAX",
        "DAL": "KDFW",
        "DEN": "KDEN",
    }
    return _MAP.get(city.upper())


FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_BASE = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = [
    "icon_seamless",
    "gfs_seamless",
]  # existing (keep for backward compat)
ENSEMBLE_MODELS_EXTENDED = [
    *ENSEMBLE_MODELS,
    "nbm",
    "ecmwf_aifs025",
]  # Phase C: adds NBM + ECMWF AIFS

# Dedicated session for NBM / Open-Meteo forecast calls (mockable in tests)
_om_session: requests.Session = requests.Session()

# Ensemble cache: key -> (list[float], timestamp)
_ENSEMBLE_CACHE: dict = {}
_ENSEMBLE_CACHE_TTL = 4 * 60 * 60  # 4 hours — matches loop interval

# Rate limiter: enforce minimum gap between Open-Meteo requests to avoid 429 bursts.
_OM_RATE_LOCK = threading.Lock()
_OM_LAST_REQUEST_TS: float = 0.0
_OM_MIN_INTERVAL: float = 3.0  # seconds between requests (~0.33 req/s) — conservative to avoid university throttling


def _om_rate_limit() -> None:
    """Block until the minimum inter-request interval has elapsed."""
    global _OM_LAST_REQUEST_TS
    with _OM_RATE_LOCK:
        now = time.monotonic()
        wait = _OM_MIN_INTERVAL - (now - _OM_LAST_REQUEST_TS)
        if wait > 0:
            time.sleep(wait)
        _OM_LAST_REQUEST_TS = time.monotonic()


def _om_request(method: str, url: str, **kwargs) -> requests.Response:
    """Rate-limited wrapper for all Open-Meteo API calls."""
    _om_rate_limit()
    return _request_with_retry(method, url, **kwargs)


# Forecast cache: (city, date_iso) -> (dict, timestamp)
_FORECAST_CACHE: dict = {}
_FORECAST_CACHE_TTL = 4 * 60 * 60  # 4 hours — matches loop interval

# Disk-backed forecast cache — survives process restarts so `analyze` is fast
# on the 2nd+ run within the same 90-minute window.
_FORECAST_DISK_CACHE_PATH = Path("data/forecast_cache.json")
_FORECAST_DISK_LOCK = threading.Lock()


def _load_forecast_disk_cache() -> None:
    """Load non-expired entries from disk into the in-memory cache on startup."""
    if not _FORECAST_DISK_CACHE_PATH.exists():
        return
    try:
        import json as _json

        with _FORECAST_DISK_LOCK:
            raw = _json.loads(_FORECAST_DISK_CACHE_PATH.read_text(encoding="utf-8"))
        now = time.time()
        loaded = 0
        for key_str, entry in raw.items():
            age = now - entry.get("ts_posix", 0)
            if age < _FORECAST_CACHE_TTL:
                # Reconstruct in-memory key as tuple; stored ts converted to monotonic approx
                city, date_iso = key_str.split("|", 1)
                mem_key = (city, date_iso)
                # Approximate monotonic timestamp from wall-clock age
                _FORECAST_CACHE[mem_key] = (entry["data"], time.monotonic() - age)
                loaded += 1
        if loaded:
            _log.debug("forecast disk cache: loaded %d entries", loaded)
    except Exception as exc:
        _log.debug("forecast disk cache load failed (non-fatal): %s", exc)


def _save_forecast_disk_entry(cache_key: tuple, data: dict) -> None:
    """Persist a single forecast cache entry to disk asynchronously."""

    def _write() -> None:
        try:
            import json as _json

            key_str = f"{cache_key[0]}|{cache_key[1]}"
            now = time.time()
            with _FORECAST_DISK_LOCK:
                if _FORECAST_DISK_CACHE_PATH.exists():
                    raw: dict = _json.loads(
                        _FORECAST_DISK_CACHE_PATH.read_text(encoding="utf-8")
                    )
                else:
                    raw = {}
                raw[key_str] = {"data": data, "ts_posix": now}
                # Prune expired entries so the file doesn't grow indefinitely
                raw = {
                    k: v
                    for k, v in raw.items()
                    if now - v.get("ts_posix", 0) < _FORECAST_CACHE_TTL
                }
                _FORECAST_DISK_CACHE_PATH.write_text(
                    _json.dumps(raw, default=str), encoding="utf-8"
                )
        except Exception as exc:
            _log.debug("forecast disk cache write failed (non-fatal): %s", exc)

    threading.Thread(target=_write, daemon=True).start()


# Populate in-memory cache from disk on import
_load_forecast_disk_cache()

# Maximum age of forecast data before analyze_trade rejects it.
# Set higher than _FORECAST_CACHE_TTL so cache expiry happens first.
# Override via FORECAST_MAX_AGE_SECS env var.
FORECAST_MAX_AGE_SECS = int(
    os.getenv("FORECAST_MAX_AGE_SECS", str(5 * 3600))
)  # 5 hours — slightly above 4h cache TTL so disk cache is always accepted

# #66: Market listing cache to avoid hammering the API on every analyze call
_MARKETS_CACHE: tuple[list, float] | None = None
_MARKETS_CACHE_TTL = 60  # 60 seconds

# ── Calibration data (loaded once at import; empty dicts = use hardcoded weights) ──
_CITY_WEIGHTS: dict[str, dict[str, float]] = _load_city_weights()
_SEASONAL_WEIGHTS: dict[str, dict[str, float]] = _load_seasonal_weights()


def _current_forecast_cycle() -> str:
    """
    #37: Return the current NWP forecast cycle label based on UTC hour.
    Cycles: 00z (00-05 UTC), 06z (06-11 UTC), 12z (12-17 UTC), 18z (18-23 UTC).
    """
    hour = datetime.now(UTC).hour
    if hour < 6:
        return "00z"
    elif hour < 12:
        return "06z"
    elif hour < 18:
        return "12z"
    else:
        return "18z"


def _ttl_until_next_cycle(now: datetime | None = None) -> int:
    """
    #126: Return seconds until the next NWP model cycle data becomes available.

    NWP model runs are initialized at 00/06/12/18 UTC, but data becomes
    available roughly 2 hours after initialization:
      00z run → available ~02 UTC
      06z run → available ~08 UTC
      12z run → available ~14 UTC
      18z run → available ~20 UTC

    Returns at least 1800 seconds (30 min) to avoid thrashing.
    """
    if now is None:
        now = datetime.now(UTC)

    # Availability hours in UTC (after which the cycle data is usable)
    cycle_hours = [2, 8, 14, 20]

    current_hour = now.hour + now.minute / 60.0

    # Find next cycle availability time today
    for ch in cycle_hours:
        if current_hour < ch:
            seconds_to_next = (ch - current_hour) * 3600
            return max(1800, int(seconds_to_next))

    # All cycles for today have passed — next is 02 UTC tomorrow
    seconds_to_midnight = (24.0 - current_hour) * 3600
    seconds_to_02_tomorrow = seconds_to_midnight + 2 * 3600
    return max(1800, int(seconds_to_02_tomorrow))


# ── Multi-model regular forecast ─────────────────────────────────────────────


def _get_enso_phase() -> str:
    """
    #28: Return the current ENSO phase: 'el_nino', 'la_nina', or 'neutral'.
    Uses ONI threshold of ±0.5 (standard NOAA definition).
    """
    try:
        oni = get_enso_index()
        if oni is None:
            return "neutral"
        if oni >= 0.5:
            return "el_nino"
        elif oni <= -0.5:
            return "la_nina"
        return "neutral"
    except Exception:
        return "neutral"


def _forecast_model_weights(month: int, city: str | None = None) -> dict[str, float]:
    """
    Seasonal model weights for the daily forecast blend.
    ECMWF is the most accurate global model in winter (Oct–Mar) for mid-latitudes.
    GFS is competitive in summer for the US. ICON adds value year-round.

    Priority order (#122, #28):
      1. Dynamic from tracker MAE (city + season specific)
      2. Per-city learned weights from data/learned_weights.json
      3. Static seasonal weights + ENSO adjustment (original behaviour)
    """
    # 1. Dynamic from tracker MAE
    if city is not None:
        dyn = _dynamic_model_weights(city=city, month=month)
        if dyn:
            return dyn

    # 2. Per-city learned weights from last backtest
    if city is not None:
        lw = load_learned_weights()
        if city in lw:
            return dict(lw[city])

    # 3. Static seasonal + ENSO fallback
    is_winter = month in (10, 11, 12, 1, 2, 3)
    ecmwf_w = 2.5 if is_winter else 1.5

    if is_winter:
        enso_phase = _get_enso_phase()
        if enso_phase == "el_nino":
            ecmwf_w += 0.5  # El Niño winters: ECMWF skill advantage grows
        elif enso_phase == "la_nina":
            ecmwf_w += 0.3  # La Niña winters: moderate ECMWF boost

    return {"gfs_seamless": 1.0, "ecmwf_ifs04": ecmwf_w, "icon_seamless": 1.0}


def get_weather_forecast(city: str, target_date: date) -> dict | None:
    """
    Fetch daily high/low/precip from three forecast models (GFS, ECMWF, ICON)
    and return the averaged values. Results are cached for 90 minutes.
    """
    cache_key = (city, target_date.isoformat())
    cached = _FORECAST_CACHE.get(cache_key)
    if cached is not None:
        data, ts = cached
        if time.monotonic() - ts < _ttl_until_next_cycle():
            return data

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, tz = coords

    # Seasonal model weights — ECMWF more accurate in winter, GFS competitive in summer
    model_weights = _forecast_model_weights(target_date.month, city=city)
    highs: list[tuple[float, float]] = []  # (value, weight)
    lows: list[tuple[float, float]] = []
    precips: list[tuple[float, float]] = []

    def _fetch_one(model: str, weight: float) -> tuple | None:
        """Fetch one model's forecast; returns (high, low, precip, weight) or None."""
        if _forecast_cb.is_open():
            _log.warning(
                "[CircuitBreaker] open_meteo_forecast circuit open — skipping forecast fetch"
            )
            return None
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": tz,
            "forecast_days": 16,
            "models": model,
        }
        try:
            resp = _om_request("GET", FORECAST_BASE, params=params, timeout=10)
            resp.raise_for_status()
            _forecast_cb.record_success()
        except Exception as _exc:
            _forecast_cb.record_failure()
            _log.warning("open_meteo forecast fetch failed: %s", _exc)
            return None
        data = resp.json()
        validate_forecast(data.get("daily", {}), source="open_meteo")
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in dates:
            return None
        idx = dates.index(target_str)
        h = daily.get("temperature_2m_max", [None])[idx]
        lo = daily.get("temperature_2m_min", [None])[idx]
        p = daily.get("precipitation_sum", [None])[idx]
        return (h, lo, p, weight)

    with ThreadPoolExecutor(max_workers=len(model_weights)) as pool:  # #124: dynamic
        futures = {
            pool.submit(_fetch_one, model, weight): model
            for model, weight in model_weights.items()
        }
        for fut in as_completed(futures):
            try:
                model_data = fut.result()
                if model_data is None:
                    continue
                h, lo, p, weight = model_data
                if h is not None:
                    highs.append((h, weight))
                if lo is not None:
                    lows.append((lo, weight))
                if p is not None:
                    precips.append((p, weight))
            except Exception:
                continue

    if not highs:
        # Open-Meteo unavailable — try Pirate Weather (HRRR-based) as fallback
        pw_high = fetch_temperature_pirate_weather(city, target_date)
        if pw_high is not None:
            _log.info(
                "get_weather_forecast: using Pirate Weather fallback for %s", city
            )
            result = {
                "date": target_date.isoformat(),
                "city": city,
                "high_f": pw_high,
                "low_f": None,
                "precip_in": 0.0,
                "models_used": 1,
                "high_range": (pw_high, pw_high),
                "_source": "pirate_weather",
            }
            _FORECAST_CACHE[cache_key] = (result, time.monotonic())
            _save_forecast_disk_entry(cache_key, result)
            return result
        return None

    def _wavg(pairs: list[tuple[float, float]]) -> float:
        total_w = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total_w

    high_vals = [v for v, _ in highs]
    result = {
        "date": target_date.isoformat(),
        "city": city,
        "high_f": _wavg(highs),
        "low_f": _wavg(lows) if lows else None,
        "precip_in": _wavg(precips) if precips else 0.0,
        "models_used": len(highs),
        "high_range": (min(high_vals), max(high_vals)),
    }
    _FORECAST_CACHE[cache_key] = (result, time.monotonic())
    _save_forecast_disk_entry(cache_key, result)
    return result


# ── NBM (National Blend of Models) ──────────────────────────────────────────


def fetch_temperature_nbm(city: str, target_date: date) -> float | None:
    """
    Fetch NBM (National Blend of Models) max daily temperature for a city.
    Uses Open-Meteo with model="nbm" — NWS-calibrated blend of GFS/HRRR/ECMWF.

    Returns max temperature for target_date in °F, or None on failure.
    """
    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _ensemble_cb.is_open():
        _log.warning("[CircuitBreaker] open_meteo circuit open — skipping NBM fetch")
        return None

    try:
        resp = _om_request(
            "GET",
            FORECAST_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "models": "nbm",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "timezone": "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        _ensemble_cb.record_success()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        return float(max(valid)) if valid else None
    except Exception as exc:
        _ensemble_cb.record_failure()
        _log.debug("fetch_temperature_nbm(%s): %s", city, exc)
        return None


_PIRATE_FORECAST_BASE = "https://api.pirateweather.net/forecast"
_PIRATE_TIMEMACHINE_BASE = "https://timemachine.pirateweather.net/forecast"

# Separate circuit breaker for Pirate Weather so Open-Meteo failures don't bleed over.
_pirate_cb = CircuitBreaker(
    name="pirate_weather", failure_threshold=3, recovery_timeout=3 * 3600
)


def fetch_temperature_pirate_weather(city: str, target_date: date) -> float | None:
    """
    Fetch daily high temperature from Pirate Weather (HRRR/GFS/GEFS blend).
    Used as fallback when Open-Meteo circuit breakers are open.

    Future/today dates use the forecast endpoint; past dates use the time machine.
    Requires PIRATE_WEATHER_API_KEY in environment.
    Returns temperatureMax for target_date in °F, or None on failure.
    """
    api_key = os.getenv("PIRATE_WEATHER_API_KEY", "")
    if not api_key:
        return None

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _pirate_cb.is_open():
        _log.warning("[CircuitBreaker] pirate_weather circuit open — skipping fetch")
        return None

    today = date.today()
    is_historical = target_date < today

    try:
        if is_historical:
            # Time machine: embed timestamp in path, returns single-day daily block

            ts = int(
                datetime(
                    target_date.year, target_date.month, target_date.day, 12, tzinfo=UTC
                ).timestamp()
            )
            url = f"{_PIRATE_TIMEMACHINE_BASE}/{api_key}/{lat},{lon},{ts}"
            params = {
                "exclude": "currently,minutely,hourly,alerts,flags",
                "units": "us",
            }
        else:
            # Forecast endpoint — 7-day daily block, find matching day by timestamp
            url = f"{_PIRATE_FORECAST_BASE}/{api_key}/{lat},{lon}"
            params = {
                "exclude": "currently,minutely,hourly,alerts,flags",
                "units": "us",
            }

        resp = _request_with_retry("GET", url, params=params, timeout=15)
        resp.raise_for_status()
        _pirate_cb.record_success()
        data = resp.json()
        daily_data = data.get("daily", {}).get("data", [])
        if not daily_data:
            return None

        if is_historical:
            entry = daily_data[0]
        else:
            # Match by calendar date — each entry's `time` is midnight local Unix timestamp

            target_ts_start = int(
                datetime(
                    target_date.year, target_date.month, target_date.day, tzinfo=UTC
                ).timestamp()
            )
            target_ts_end = target_ts_start + 86400
            entry = next(
                (
                    d
                    for d in daily_data
                    if target_ts_start <= d.get("time", 0) < target_ts_end
                ),
                daily_data[0],  # fallback to first day if date match fails
            )

        # temperatureMax is the absolute daily extreme; prefer over temperatureHigh (daytime only)
        high = entry.get("temperatureMax") or entry.get("temperatureHigh")
        return float(high) if high is not None else None
    except Exception as exc:
        _pirate_cb.record_failure()
        _log.debug("fetch_temperature_pirate_weather(%s): %s", city, exc)
        return None


def _compute_ensemble_mean(temps: dict[str, float | None]) -> float | None:
    """Compute mean of non-None values in a {model: temp} dict."""
    values = [v for v in temps.values() if v is not None]
    return sum(values) / len(values) if values else None


def _compute_ensemble_spread(temps: dict[str, float | None]) -> float:
    """Compute std dev of non-None values. Returns 0.0 if fewer than 2 valid."""
    values = [v for v in temps.values() if v is not None]
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


# Historical forecast RMSE per city/season (Phase C Gaussian probability)
# Season: 1=Winter(DJF), 2=Spring(MAM), 3=Summer(JJA), 4=Fall(SON)
_HISTORICAL_SIGMA: dict[str, dict[int, float]] = {
    "NYC": {1: 5.5, 2: 6.0, 3: 5.0, 4: 5.8},
    "MIA": {1: 3.5, 2: 4.0, 3: 3.0, 4: 3.5},
    "CHI": {1: 7.0, 2: 6.5, 3: 5.5, 4: 6.5},
    "LAX": {1: 4.0, 2: 4.5, 3: 4.0, 4: 4.5},
    "DAL": {1: 5.0, 2: 5.5, 3: 4.5, 4: 5.5},
}
_DEFAULT_SIGMA = 5.0


def _month_to_season(month: int) -> int:
    """Convert month (1-12) to season index (1=Winter, 2=Spring, 3=Summer, 4=Fall)."""
    return {12: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3, 9: 4, 10: 4, 11: 4}[
        month
    ]


def get_historical_sigma(city: str, month: int) -> float:
    """Return historical forecast RMSE (sigma) for a city in °F."""
    season = _month_to_season(month)
    return _HISTORICAL_SIGMA.get(city.upper(), {}).get(season, _DEFAULT_SIGMA)


def gaussian_probability(
    forecast_mean: float,
    threshold: float,
    sigma: float,
    direction: str = "above",
) -> float:
    """
    Compute P(T > threshold) or P(T < threshold) using a Gaussian distribution.

    More principled than raw ensemble member counting for small ensembles.

    Args:
        forecast_mean: Bias-corrected ensemble mean temperature in °F
        threshold: Kalshi market threshold in °F
        sigma: Forecast uncertainty (RMSE) in °F
        direction: "above" or "below"

    Returns:
        Probability as a float in [0, 1]
    """
    if direction not in ("above", "below"):
        raise ValueError(f"gaussian_probability: unknown direction {direction!r}")
    # P(T < threshold) where T ~ Normal(forecast_mean, sigma)
    cdf = normal_cdf(threshold, forecast_mean, sigma)

    if direction == "above":
        return max(0.0, min(1.0, 1.0 - cdf))
    else:
        return max(0.0, min(1.0, cdf))


def fetch_temperature_ecmwf(city: str, target_date: date) -> float | None:
    """
    Fetch ECMWF AIFS ensemble max daily temperature for a city.
    Uses Open-Meteo with models="ecmwf_aifs025".
    Outperforms GFS by ~20% for days 1–3 (operational since July 2025).

    Returns max temperature for target_date in °F, or None on failure.
    """
    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _ensemble_cb.is_open():
        _log.warning("[CircuitBreaker] open_meteo circuit open — skipping ECMWF fetch")
        return None

    try:
        resp = _om_request(
            "GET",
            FORECAST_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "models": "ecmwf_aifs025",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "timezone": "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        _ensemble_cb.record_success()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        return float(max(valid)) if valid else None
    except Exception as exc:
        _ensemble_cb.record_failure()
        _log.debug("fetch_temperature_ecmwf(%s): %s", city, exc)
        return None


# ── Ensemble forecast ────────────────────────────────────────────────────────


def _fetch_model_ensemble(
    lat: float,
    lon: float,
    tz: str,
    target_date: date,
    model: str,
    hour: int | None,
    var: str,
) -> list[float]:
    """
    Fetch all ensemble member temps from one model for a given location/date.
    var: "max" (daily high), "min" (daily low)
    hour: if set, fetch hourly data at that local hour instead of daily.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": model,
        "temperature_unit": "fahrenheit",
        "timezone": tz,
        "forecast_days": 16,
    }

    if _ensemble_cb.is_open():
        _log.warning(
            "[CircuitBreaker] open_meteo circuit open — skipping ensemble fetch"
        )
        return []

    if hour is not None:
        params["hourly"] = "temperature_2m"
        try:
            resp = _om_request("GET", ENSEMBLE_BASE, params=params, timeout=20)
            resp.raise_for_status()
            _ensemble_cb.record_success()
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.warning("open_meteo ensemble fetch failed: %s", _exc)
            return []
        data = resp.json()
        # #71: validate expected response structure
        if not isinstance(data, dict):
            return []
        hourly = data.get("hourly")
        if not isinstance(hourly, dict):
            return []
        times = hourly.get("time", [])
        target_dt = f"{target_date.isoformat()}T{hour:02d}:00"
        if target_dt not in times:
            return []
        idx = times.index(target_dt)
        return [
            hourly[k][idx]
            for k in hourly
            if k.startswith("temperature_2m_member") and hourly[k][idx] is not None
        ]
    else:
        daily_var = "temperature_2m_max" if var == "max" else "temperature_2m_min"
        params["daily"] = daily_var
        try:
            resp = _om_request("GET", ENSEMBLE_BASE, params=params, timeout=20)
            resp.raise_for_status()
            _ensemble_cb.record_success()
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.warning("open_meteo ensemble fetch failed: %s", _exc)
            return []
        data = resp.json()
        # #71: validate expected response structure
        if not isinstance(data, dict):
            return []
        daily = data.get("daily")
        if not isinstance(daily, dict):
            return []
        times = daily.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in times:
            return []
        idx = times.index(target_str)
        prefix = f"{daily_var}_member"
        return [
            daily[k][idx]
            for k in daily
            if k.startswith(prefix) and daily[k][idx] is not None
        ]


_LEARNED_WEIGHTS: dict = {}  # cached after first load


def load_learned_weights() -> dict:
    """
    Load per-city model weights previously saved by save_learned_weights().
    Format: {city: {model: weight, ...}, ...}
    Returns empty dict if file missing or malformed. Cached for the session.
    """
    global _LEARNED_WEIGHTS
    if _LEARNED_WEIGHTS:
        return _LEARNED_WEIGHTS
    path = Path(__file__).parent / "data" / "learned_weights.json"
    if not path.exists():
        return {}
    try:
        import json as _json

        _LEARNED_WEIGHTS = _json.loads(path.read_text())
        return _LEARNED_WEIGHTS
    except Exception:
        return {}


def save_learned_weights(weights: dict) -> None:
    """
    Persist per-city model weights to data/learned_weights.json atomically.
    Called after a backtest to update city-specific model preferences.
    """
    import json as _json
    import os as _os
    import tempfile as _tmp

    path = Path(__file__).parent / "data" / "learned_weights.json"
    path.parent.mkdir(exist_ok=True)
    fd, tmp = _tmp.mkstemp(dir=path.parent, prefix=".lw_", suffix=".json")
    try:
        with _os.fdopen(fd, "w") as f:
            _json.dump(weights, f, indent=2)
        _os.replace(tmp, path)
    except Exception:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
    global _LEARNED_WEIGHTS
    _LEARNED_WEIGHTS = weights


def save_forecast_snapshot(ticker: str, forecast_data: dict) -> None:
    """
    Save raw forecast data used for a trade decision to data/forecast_snapshots/.
    Enables post-hoc analysis of why specific trades were taken.
    Silently skips if saving fails.
    """
    try:
        import json as _json
        from datetime import date as _date

        snap_dir = Path(__file__).parent / "data" / "forecast_snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        safe_ticker = ticker.replace("/", "-").replace(":", "-")
        path = snap_dir / f"{safe_ticker}_{_date.today().isoformat()}.json"
        # Don't overwrite existing snapshot for same ticker+day
        if not path.exists():
            snapshot = {
                "ticker": ticker,
                "snapshot_date": _date.today().isoformat(),
                "forecast": forecast_data,
            }
            path.write_text(_json.dumps(snapshot, indent=2, default=str))
    except Exception as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("save_forecast_snapshot: %s", exc)


def _feels_like(
    temp_f: float, wind_mph: float = 10.0, humidity_pct: float = 50.0
) -> float:
    """
    Compute apparent (feels-like) temperature from actual temp, wind, and humidity.
    Uses wind chill formula for cold temps, heat index for hot/humid conditions.
    """
    if temp_f <= 50.0 and wind_mph >= 3.0:
        # NWS Wind Chill formula (valid for T<=50°F, W>=3 mph)
        w016 = wind_mph**0.16
        wc = 35.74 + 0.6215 * temp_f - 35.75 * w016 + 0.4275 * temp_f * w016
        # #29: Moist-cold regime — high humidity makes cold feel colder
        # 1.5°F penalty per 10% humidity above 70%, applied on top of wind chill
        if humidity_pct >= 70.0:
            humidity_penalty = (humidity_pct - 70.0) / 10.0 * 1.5
            wc -= humidity_penalty
        return wc
    elif temp_f >= 80.0 and humidity_pct >= 40.0:
        # Rothfusz Heat Index formula
        T, H = temp_f, humidity_pct
        hi = (
            -42.379
            + 2.04901523 * T
            + 10.14333127 * H
            - 0.22475541 * T * H
            - 0.00683783 * T * T
            - 0.05481717 * H * H
            + 0.00122874 * T * T * H
            + 0.00085282 * T * H * H
            - 0.00000199 * T * T * H * H
        )
        return hi
    # #29: Moist-cold intermediate regime (no strong wind, temp<=50, humidity>=70)
    if temp_f <= 50.0 and humidity_pct >= 70.0:
        humidity_penalty = (humidity_pct - 70.0) / 10.0 * 1.5
        return temp_f - humidity_penalty
    return temp_f


_MAE_WEIGHTS_CACHE: dict[
    tuple[str, int], dict[str, float]
] = {}  # (city, days_back) -> weights, session cache


def _weights_from_mae(
    city: str, min_n: int = 20, days_back: int = 60
) -> dict[str, float] | None:
    """
    #25/#118: Derive per-model blend weights from inverse-MAE scores in tracker.
    Uses a rolling days_back window (default 60 days) to capture recent model drift.
    Returns None if insufficient data (< min_n observations per model).
    Lower MAE → higher weight. Normalised so weights sum to the number of models.
    City-specific data is preferred; falls back to global MAE if city data is thin.
    """
    cache_key = (city, days_back)
    if cache_key in _MAE_WEIGHTS_CACHE:
        return _MAE_WEIGHTS_CACHE[cache_key]
    try:
        from tracker import get_member_accuracy

        acc = get_member_accuracy(
            days_back=days_back
        )  # {model: {mae, n, city_breakdown}}
    except Exception:
        return None

    if not acc:
        return None

    weights: dict[str, float] = {}
    for model, stats in acc.items():
        city_bd = stats.get("city_breakdown", {})
        # Prefer city-level MAE if we have enough data there
        city_mae = city_bd.get(city)
        city_n = sum(1 for _ in city_bd) if city_bd else 0
        mae = city_mae if (city_mae is not None and city_n >= min_n) else stats["mae"]
        n = stats["n"]
        if n < min_n or mae <= 0:
            return None  # too little data — don't trust yet
        weights[model] = 1.0 / mae

    if not weights:
        return None

    # Normalise so weights sum to len(weights) (keeps same scale as seasonal priors)
    total = sum(weights.values())
    n_models = len(weights)
    normalised = {m: v / total * n_models for m, v in weights.items()}
    _MAE_WEIGHTS_CACHE[cache_key] = normalised
    return normalised


def _dynamic_model_weights(
    city: str | None = None, month: int | None = None, min_samples: int = 5
) -> dict | None:
    """
    #25: Derive per-model blend weights from tracker MAE data via
    get_ensemble_member_accuracy(). Returns inverse-MAE weights normalised so
    weights sum to the number of models. Returns None if < min_samples per model.
    Lower MAE → higher weight.
    """
    try:
        from tracker import get_ensemble_member_accuracy

        season = None
        if month is not None:
            season = "winter" if month in (10, 11, 12, 1, 2, 3) else "summer"

        acc = get_ensemble_member_accuracy(city=city, season=season)
    except Exception:
        return None

    if not acc:
        return None

    weights: dict[str, float] = {}
    for model, stats in acc.items():
        count = stats.get("count", 0)
        mae = stats.get("mae", 0.0)
        if count < min_samples or mae <= 0:
            return None  # insufficient data for at least one model — don't use
        weights[model] = 1.0 / mae

    if not weights:
        return None

    # Normalise so weights sum to len(weights)
    total = sum(weights.values())
    n_models = len(weights)
    return {m: v / total * n_models for m, v in weights.items()}


def update_learned_weights_from_tracker(min_n: int = 20) -> dict:
    """
    #118: Compute per-city inverse-MAE weights from tracker data and persist to
    data/learned_weights.json.  Call this after each backtest walk-forward run.
    Returns the weights dict that was saved.
    """
    try:
        from tracker import get_member_accuracy

        acc = get_member_accuracy(
            days_back=60
        )  # use same 60-day window as _weights_from_mae
    except Exception:
        return {}

    if not acc:
        return {}

    # Collect all cities that appear in any model's city_breakdown
    all_cities: set[str] = set()
    for stats in acc.values():
        all_cities.update(stats.get("city_breakdown", {}).keys())

    city_weights: dict[str, dict[str, float]] = {}
    for city in all_cities:
        w = _weights_from_mae(city, min_n=min_n)
        if w:
            city_weights[city] = w

    if city_weights:
        save_learned_weights(city_weights)
    return city_weights


def learn_seasonal_weights(city: str, min_n: int = 20) -> dict[str, float]:
    """
    #118: Compute and persist per-city model weights from tracker MAE data.
    Returns the weights for `city` (or {} if insufficient data).
    Saves results to data/learned_weights.json for use by _forecast_model_weights.
    """
    all_weights = update_learned_weights_from_tracker(min_n=min_n)
    return dict(all_weights.get(city, {}))


def _model_weights(city: str, month: int | None = None) -> dict[str, float]:
    """
    Return per-model weights for the ensemble blend.
    Priority order:
      1. Per-city inverse-MAE weights derived from tracker data (#25/#118)
      2. Manually learned weights from data/learned_weights.json (from backtest)
      3. Seasonal ECMWF/GFS priors (original behaviour)
    """
    # 1. Dynamic: derive from recent tracker MAE data
    mae_weights = _weights_from_mae(city)
    if mae_weights:
        # Blend MAE-derived weights with seasonal prior at 70/30 so we don't
        # completely abandon meteorological priors with limited data
        is_winter = (month or 0) in (10, 11, 12, 1, 2, 3)
        ecmwf_prior = 2.0 if is_winter else 1.5
        prior = {"icon_seamless": 1.0, "gfs_seamless": 1.0, "ecmwf_ifs04": ecmwf_prior}
        blended: dict[str, float] = {}
        for m in set(mae_weights) | set(prior):
            blended[m] = 0.7 * mae_weights.get(m, 1.0) + 0.3 * prior.get(m, 1.0)
        return blended

    # 2. Pre-saved learned weights from last backtest run
    lw = load_learned_weights()
    if city in lw:
        return dict(lw[city])

    # 3. Seasonal ECMWF weight: better in winter for mid-latitude US cities
    if month is not None:
        is_winter = month in (10, 11, 12, 1, 2, 3)
        ecmwf_w = 2.0 if is_winter else 1.5
    else:
        ecmwf_w = 1.5  # conservative default

    return {"icon_seamless": 1.0, "gfs_seamless": 1.0, "ecmwf_ifs04": ecmwf_w}


def get_ensemble_temps(
    city: str, target_date: date, hour: int | None = None, var: str = "max"
) -> list[float]:
    """
    Return all ensemble member temperatures for a city/date, combining
    ICON (51 members) and GFS (31 members). Results are cached.
    Model contributions are weighted by historical Brier performance.

    var: "max" for daily high, "min" for daily low (ignored if hour is set).
    hour: local hour (0-23) for hourly markets like KXTEMPNYCH.
    """
    cache_key = (city, target_date.isoformat(), hour, var)
    cached = _ENSEMBLE_CACHE.get(cache_key)
    if cached is not None:
        data, ts = cached
        if time.monotonic() - ts < _ttl_until_next_cycle():
            return data

    coords = CITY_COORDS.get(city)
    if not coords:
        return []
    lat, lon, tz = coords

    weights = _model_weights(city, month=target_date.month)

    # We only reach here when building fresh data (stale cache was discarded above,
    # or no cache existed). Always use full model weights for a fresh fetch.
    decay = 1.0

    all_temps: list[float] = []
    ensemble_models_with_ecmwf = [*ENSEMBLE_MODELS, "ecmwf_ifs04"]
    for model in ensemble_models_with_ecmwf:
        try:
            temps = _fetch_model_ensemble(lat, lon, tz, target_date, model, hour, var)
            base_w = weights.get(model, 1.0)
            # Decay towards equal weighting (1.0) as cache ages
            w = 1.0 + (base_w - 1.0) * decay
            # Replicate members proportionally to apply weight.
            repeats = max(1, round(w * 2))
            all_temps.extend(temps * repeats)
        except Exception:
            pass

    _ENSEMBLE_CACHE[cache_key] = (all_temps, time.monotonic())
    return all_temps


def is_forecast_anomalous(ens_stats: dict, threshold_multiplier: float = 1.5) -> bool:
    """
    Return True if the ensemble spread (p90-p10) is unusually wide — a sign the
    forecast models disagree strongly and uncertainty is high.
    Typical spread is ~8-12°F; anything beyond 1.5× that is flagged.
    """
    if not ens_stats:
        return False
    spread = ens_stats.get("p90", 0) - ens_stats.get("p10", 0)
    # Typical p10-p90 spread for US cities: ~8°F within 7 days
    return spread > 8.0 * threshold_multiplier


def ensemble_stats(temps: list[float]) -> dict:
    """Summary statistics for a list of ensemble member temperatures."""
    if not temps:
        return {}
    return {
        "n": len(temps),
        "mean": statistics.mean(temps),
        "std": statistics.stdev(temps) if len(temps) > 1 else 0.0,
        "min": min(temps),
        "max": max(temps),
        "p10": sorted(temps)[min(int(len(temps) * 0.10), len(temps) - 1)],
        "p90": sorted(temps)[min(int(len(temps) * 0.90), len(temps) - 1)],
    }


def censoring_correction(
    probs: list[float],
    condition: dict,
    censor_pct: float = 0.01,
) -> float:
    """
    Correct ensemble probability for member censoring at 0 or 1 (#23).

    When > censor_pct fraction of ensemble members are exactly 0.0 or 1.0,
    blends the raw mean toward 0.5 using blend = censored_fraction * 0.5.
    Returns 0.5 for empty input.
    """
    if not probs:
        return 0.5

    n = len(probs)
    raw_mean = sum(probs) / n
    censored = sum(1 for p in probs if p == 0.0 or p == 1.0)
    censored_fraction = censored / n

    if censored_fraction <= censor_pct:
        return raw_mean

    blend = censored_fraction * 0.5
    corrected = raw_mean * (1.0 - blend) + 0.5 * blend
    return max(0.0, min(1.0, corrected))


# ── Market parsing ────────────────────────────────────────────────────────────


def parse_market_price(market: dict) -> dict:
    """Extract yes/no bid prices and implied probability from a market."""
    # API returns either yes_bid/yes_ask (legacy) or yes_bid_dollars/yes_ask_dollars (current)
    yes_bid = market.get("yes_bid") or market.get("yes_bid_dollars") or 0
    yes_ask = market.get("yes_ask") or market.get("yes_ask_dollars") or 0
    no_bid = market.get("no_bid") or market.get("no_bid_dollars") or 0

    # Prices may be cents (int) or dollar strings depending on API version
    def to_float(v) -> float:
        if isinstance(v, str):
            return float(v)
        if isinstance(v, int | float) and v > 1:
            return v / 100.0  # legacy cents format
        return float(v)

    yes_bid_f = to_float(yes_bid)
    yes_ask_f = to_float(yes_ask)
    no_bid_f = to_float(no_bid)
    mid = (yes_bid_f + yes_ask_f) / 2 if yes_ask_f > 0 else yes_bid_f

    return {
        "yes_bid": yes_bid_f,
        "yes_ask": yes_ask_f,
        "no_bid": no_bid_f,
        "mid": mid,
        "implied_prob": mid,  # mid-price ≈ market probability
    }


# ── Weather series detection ──────────────────────────────────────────────────

WEATHER_KEYWORDS = {
    "temp",
    "high",
    "low",
    "rain",
    "snow",
    "precip",
    "storm",
    "hurricane",
    "wind",
    "frost",
    "heat",
    "cold",
    "weather",
}


def is_stale(market: dict) -> bool:
    """
    Returns True if a market has no volume AND closes within 60 minutes.
    Stale markets have meaningless edge calculations — skip them.
    """
    volume = market.get("volume") or 0
    open_interest = market.get("open_interest") or 0
    if volume > 0 or open_interest > 0:
        return False
    close_time_str = market.get("close_time", "")
    if not close_time_str:
        return False
    try:
        close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        minutes_left = (close_time - datetime.now(UTC)).total_seconds() / 60
        return minutes_left < 60
    except (ValueError, TypeError):
        return False


def is_weather_market(market: dict) -> bool:
    title = (market.get("title") or "").lower()
    subtitle = (market.get("subtitle") or "").lower()
    ticker = (market.get("ticker") or "").lower()
    series = (market.get("series_ticker") or "").lower()
    text = f"{title} {subtitle} {ticker} {series}"
    return any(kw in text for kw in WEATHER_KEYWORDS)


def get_weather_markets(
    client: KalshiClient, limit: int = 200, force: bool = False
) -> list[dict]:
    """
    Fetch open markets and filter to weather-related ones.
    #66: Results cached for 60 seconds to avoid hammering the API.
    Pass force=True to bypass cache.
    """
    global _MARKETS_CACHE
    now = time.monotonic()
    if not force and _MARKETS_CACHE is not None:
        cached_markets, cached_ts = _MARKETS_CACHE
        if now - cached_ts < _MARKETS_CACHE_TTL:
            return cached_markets

    results = []
    seen = set()

    # Strategy 1: fetch open markets and filter
    try:
        markets = client.get_markets(status="open", limit=limit)
        for m in markets:
            if m.get("ticker") not in seen and is_weather_market(m) and not is_stale(m):
                results.append(m)
                seen.add(m["ticker"])
    except Exception as e:
        print(f"[warn] Could not fetch markets: {e}")

    # Strategy 2: known weather series tickers — fetch in parallel (#127)
    known_series = [
        "KXHIGHNY",
        "KXHIGHCHI",
        "KXHIGHLA",
        "KXHIGHBOS",
        "KXHIGHMIA",
        "KXHIGHTDAL",
        "KXHIGHTPHX",
        "KXHIGHTSEA",
        "KXHIGHDEN",
        "KXHIGHTATL",
        "KXHIGHAUS",
        "KXHIGHTDC",
        "KXHIGHTPHIL",
        "KXHIGHTOKC",
        "KXHIGHTSFO",
        "KXHIGHTMIN",
        "KXHIGHHOUM",
        "KXHIGHTSATX",
        "KXLOWNY",
        "KXLOWCHI",
        "KXLOWLA",
        "KXLOWBOS",
        "KXLOWMIA",
        "KXLOWTDAL",
        "KXLOWTPHX",
        "KXLOWTSEA",
        "KXLOWDEN",
        "KXLOWTATL",
        "KXLOWAUS",
        "KXLOWTDC",
        "KXLOWTPHIL",
        "KXLOWTOKC",
        "KXLOWTSFO",
        "KXLOWTMIN",
        "KXLOWHOUM",
        "KXLOWTSATX",
        "KXRAIN",
        "KXSNOW",
    ]

    def _fetch_series(series: str) -> list[dict]:
        try:
            return client.get_markets(series_ticker=series, status="open", limit=50)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_series, s): s for s in known_series}
        for fut in as_completed(futures):
            for m in fut.result():
                if m.get("ticker") not in seen:
                    results.append(m)
                    seen.add(m["ticker"])

    _MARKETS_CACHE = (results, now)
    return results


MONTH_MAP = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def enrich_with_forecast(market: dict) -> dict:
    """
    Attach forecast data to a market dict.
    Parses city, date, and (for hourly markets) hour from the ticker.
    """
    ticker = market.get("ticker", "")
    title = (market.get("title") or "").lower()
    ticker_up = ticker.upper()

    # Detect city
    city = None
    if "NY" in ticker_up or "new york" in title:
        city = "NYC"
    elif "CHI" in ticker_up or "chicago" in title:
        city = "Chicago"
    elif "LA" in ticker_up or "los angeles" in title:
        city = "LA"
    elif "BOS" in ticker_up or "boston" in title:
        city = "Boston"
    elif "MIA" in ticker_up or "miami" in title:
        city = "Miami"
    elif "TDAL" in ticker_up or "dallas" in title:
        city = "Dallas"
    elif "TPHX" in ticker_up or "phoenix" in title:
        city = "Phoenix"
    elif "TSEA" in ticker_up or "seattle" in title:
        city = "Seattle"
    elif "DEN" in ticker_up or "denver" in title:
        city = "Denver"
    elif "TATL" in ticker_up or "atlanta" in title:
        city = "Atlanta"
    elif "AUS" in ticker_up or "austin" in title:
        city = "Austin"
    elif "TDC" in ticker_up or "washington" in title:
        city = "Washington"
    elif "TPHIL" in ticker_up or "philadelphia" in title:
        city = "Philadelphia"
    elif "TOKC" in ticker_up or "oklahoma" in title:
        city = "OklahomaCity"
    elif "TSFO" in ticker_up or "san francisco" in title:
        city = "SanFrancisco"
    elif "TMIN" in ticker_up or "minneapolis" in title:
        city = "Minneapolis"
    elif "HOUM" in ticker_up or "houston" in title:
        city = "Houston"
    elif "TSATX" in ticker_up or "san antonio" in title:
        city = "SanAntonio"

    # Detect date + optional hour
    # Hourly tickers: KXTEMPNYCH-26APR0908-T45.99  → date=26APR09, hour=08
    # Daily tickers:  KXHIGHNY-26APR10-T68         → date=26APR10, hour=None
    target_date = None
    hour = None

    hourly_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(\d{2})", ticker_up)
    daily_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(?!\d)", ticker_up)

    if hourly_match:
        yy, mon_str, dd, hh = hourly_match.groups()
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                target_date = date(2000 + int(yy), month, int(dd))
                hour = int(hh)
            except ValueError:
                pass
    elif daily_match:
        yy, mon_str, dd = daily_match.groups()
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                target_date = date(2000 + int(yy), month, int(dd))
            except ValueError:
                pass

    forecast = None
    if city and target_date:
        forecast = get_weather_forecast(city, target_date)

    import time as _time_enrich

    return {
        **market,
        "_city": city,
        "_date": target_date,
        "_hour": hour,
        "_forecast": forecast,
        "data_fetched_at": _time_enrich.time(),
    }


# ── Trade analysis ────────────────────────────────────────────────────────────


def _forecast_uncertainty(target_date: date) -> float:
    """
    Estimated standard deviation of forecast error in °F.
    Weather forecasts get less accurate further out.
    """
    days_out = (target_date - date.today()).days
    if days_out <= 1:
        return 3.0
    elif days_out <= 3:
        return 4.0
    elif days_out <= 5:
        return 5.0
    elif days_out <= 7:
        return 6.0
    else:
        return 7.5


def _time_risk(close_time_str: str, tz: str) -> tuple[str, float]:
    """
    Determine time-of-day risk level and forecast sigma multiplier.

    Returns (risk_label, sigma_multiplier):
      "LOW" / 0.5  — within 2 hours of close (near-real-time data available)
      "LOW" / 0.7  — market closes after 8pm local (weather station already read)
      "LOW" / 0.8  — same-day market (closes today local time)
      "MEDIUM" / 0.85 — closes within 24 hours (tomorrow's market)
      "HIGH" / 1.0 — far-out market, no timing advantage

    sigma_multiplier < 1.0 means reduce forecast uncertainty (we know more).
    """
    if not close_time_str:
        return ("HIGH", 1.0)
    try:
        from zoneinfo import ZoneInfo

        close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        hours_to_close = (close_dt - datetime.now(UTC)).total_seconds() / 3600
        local_close = close_dt.astimezone(ZoneInfo(tz))
        local_hour = local_close.hour
        closes_today = local_close.date() == datetime.now(ZoneInfo(tz)).date()
        if hours_to_close <= 2:
            return ("LOW", 0.5)
        elif local_hour >= 20:
            return ("LOW", 0.7)
        elif closes_today:
            return ("LOW", 0.8)
        elif hours_to_close <= 24:
            return ("MEDIUM", 0.85)
        else:
            return ("HIGH", 1.0)
    except Exception:
        return ("HIGH", 1.0)


def _parse_market_condition(market: dict) -> dict | None:
    """
    Parse what outcome a market is asking about from its ticker and title.
    Returns a dict like:
      {"type": "above", "threshold": 68.0}         — temperature above X°F
      {"type": "below", "threshold": 53.0}         — temperature below X°F
      {"type": "between", "lower": 67.0, "upper": 68.0}
      {"type": "precip_above", "threshold": 0.10}  — precip > 0.10 in
      {"type": "precip_any"}                        — any measurable precip (>0.01 in)
    Returns None if unparseable.
    """
    ticker = market.get("ticker", "")
    title = (market.get("title") or "").lower()
    ticker_up = ticker.upper()

    # ── Precipitation markets ─────────────────────────────────────────────────
    # Whitelist known precipitation series to avoid false positives from
    # title-matching unrelated markets that contain words like "rain".
    PRECIP_SERIES = {"KXRAIN", "KXSNOW", "KXPRECIP"}
    series_up = (market.get("series_ticker") or "").upper()
    is_precip_series = any(s in ticker_up or s in series_up for s in PRECIP_SERIES)
    is_precip_title = (
        ("rain" in title or "precip" in title or "snow" in title)
        and "temperature" not in title
        and "high" not in title
        and "low" not in title
    )
    is_precip = is_precip_series or is_precip_title

    # ── Snow/ice markets ──────────────────────────────────────────────────────
    SNOW_SERIES = {"KXSNOW", "KXICE"}
    is_snow_series = any(s in ticker_up or s in series_up for s in SNOW_SERIES)
    is_snow_title = (
        ("snow" in title or "ice" in title or "sleet" in title)
        and "temperature" not in title
        and "high" not in title
        and "low" not in title
    )
    # Check ticker directly for SNOW/ICE keywords
    is_snow_ticker = "SNOW" in ticker_up or "ICE" in ticker_up
    if is_snow_series or is_snow_ticker or (is_snow_title and not is_precip_series):
        # Parse threshold from title: "more than 2 inches of snow"
        snow_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch|in\b)", title)
        if snow_match:
            threshold = float(snow_match.group(1))
            return {"type": "precip_snow", "threshold": threshold, "unit": "inches"}
        # Explicit threshold in ticker: -P2.0
        snow_ticker_match = re.search(r"-P(\d+(?:\.\d+)?)(?:-|$)", ticker)
        if snow_ticker_match:
            return {
                "type": "precip_snow",
                "threshold": float(snow_ticker_match.group(1)),
                "unit": "inches",
            }
        # Binary any-snow
        return {"type": "precip_snow", "threshold": 0.0, "unit": "inches"}

    if is_precip:
        # Explicit threshold: e.g. KXRAIN-26APR10-P0.25 → precip > 0.25 in
        precip_match = re.search(r"-P(\d+(?:\.\d+)?)(?:-|$)", ticker)
        if precip_match:
            return {"type": "precip_above", "threshold": float(precip_match.group(1))}
        # Threshold in title: "more than 0.50 inches"
        amt_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inch|in\b)", title)
        if amt_match:
            threshold = float(amt_match.group(1))
            if "more than" in title or "exceed" in title or ">" in title:
                return {"type": "precip_above", "threshold": threshold}
        # Binary any-precip (only if series is a known precip series)
        if is_precip_series or "measurable" in title or "any" in title:
            return {"type": "precip_any"}
        return None

    # ── Temperature markets ───────────────────────────────────────────────────
    # Extract the condition part after the date, e.g. "T68", "T53", "B67.5"
    cond_match = re.search(r"-([TB])(\d+(?:\.\d+)?)$", ticker)
    if not cond_match:
        return None

    kind, val_str = cond_match.group(1), cond_match.group(2)
    val = float(val_str)

    if kind == "B":
        # Bucket: B67.5 means range [67, 68]
        return {"type": "between", "lower": val - 0.5, "upper": val + 0.5}
    else:
        # T: determine above or below from title
        if ">" in title or "above" in title or " be >" in title:
            return {"type": "above", "threshold": val}
        elif "<" in title or "below" in title or " be <" in title:
            return {"type": "below", "threshold": val}
        else:
            return None


def _forecast_probability(condition: dict, forecast_temp: float, sigma: float) -> float:
    """Estimate probability of the market condition given a forecast temperature."""
    if condition["type"] == "above":
        return 1.0 - normal_cdf(condition["threshold"], forecast_temp, sigma)
    elif condition["type"] == "below":
        return normal_cdf(condition["threshold"], forecast_temp, sigma)
    elif condition["type"] == "between":
        p_upper = normal_cdf(condition["upper"], forecast_temp, sigma)
        p_lower = normal_cdf(condition["lower"], forecast_temp, sigma)
        return p_upper - p_lower
    return 0.0


def is_liquid(market: dict) -> bool:
    """
    True if the market has real two-sided quotes (not just 0/0).
    A market with no quotes can still be traded — you'd be the first to post —
    but the implied probability of 0% is misleading for edge calculations.
    """
    prices = parse_market_price(market)
    has_yes = prices["yes_bid"] > 0 or prices["yes_ask"] > 0
    has_no = prices["no_bid"] > 0
    volume = market.get("volume", 0) or 0
    return has_yes or has_no or volume > 0


def _edge_label(edge: float) -> str:
    """Convert a probability edge to a human-readable signal."""
    abs_edge = abs(edge)
    if abs_edge < 0.05:
        return "NEUTRAL"
    direction = "YES" if edge > 0 else "NO "
    if abs_edge >= 0.25:
        return f"STRONG BUY {direction}"
    elif abs_edge >= 0.15:
        return f"BUY {direction}      "
    else:
        return f"WEAK {direction}     "


def _blend_weights(
    days_out: int,
    has_nws: bool,
    has_clim: bool,
    city: str | None = None,
    season: str | None = None,
) -> tuple[float, float, float]:
    """Return (w_ensemble, w_climatology, w_nws).

    Priority: city-specific calibration > seasonal calibration > hardcoded schedule.
    """
    # 1. City-specific calibration weights
    if city and city in _CITY_WEIGHTS:
        cal = _CITY_WEIGHTS[city]
        w_ens = cal["ensemble"]
        w_clim = cal["climatology"]
        w_nws = cal["nws"]
        if not has_nws:
            w_ens += w_nws * 0.6
            w_clim += w_nws * 0.4
            w_nws = 0.0
        if not has_clim:
            w_ens += w_clim
            w_clim = 0.0
        total = w_ens + w_clim + w_nws
        if total > 0.0:
            return w_ens / total, w_clim / total, w_nws / total
        # Degenerate calibration data; fall through to seasonal/hardcoded

    # 2. Seasonal calibration weights
    if season and season in _SEASONAL_WEIGHTS:
        cal = _SEASONAL_WEIGHTS[season]
        w_ens = cal["ensemble"]
        w_clim = cal["climatology"]
        w_nws = cal["nws"]
        if not has_nws:
            w_ens += w_nws * 0.6
            w_clim += w_nws * 0.4
            w_nws = 0.0
        if not has_clim:
            w_ens += w_clim
            w_clim = 0.0
        total = w_ens + w_clim + w_nws
        if total > 0.0:
            return w_ens / total, w_clim / total, w_nws / total
        # Degenerate calibration data; fall through to hardcoded schedule

    # 3. Hardcoded schedule (original logic)
    if days_out <= 3:
        w_nws = 0.35
    elif days_out <= 7:
        w_nws = 0.25
    else:
        w_nws = 0.10

    w_rem = 1.0 - w_nws
    if days_out <= 1:
        w_ens = w_rem * 0.94
        w_clim = w_rem * 0.06
    elif days_out <= 3:
        w_ens = w_rem * 0.87
        w_clim = w_rem * 0.13
    elif days_out <= 5:
        w_ens = w_rem * 0.69
        w_clim = w_rem * 0.31
    elif days_out <= 7:
        w_ens = w_rem * 0.53
        w_clim = w_rem * 0.47
    elif days_out <= 10:
        w_ens = w_rem * 0.26
        w_clim = w_rem * 0.74
    else:
        w_ens = w_rem * 0.13
        w_clim = w_rem * 0.87

    if not has_nws:
        w_ens += w_nws * 0.6
        w_clim += w_nws * 0.4
        w_nws = 0.0
    if not has_clim:
        w_ens += w_clim
        w_clim = 0.0

    total = w_ens + w_clim + w_nws
    return w_ens / total, w_clim / total, w_nws / total


_ENS_STD_REF = 4.0  # °F — typical tight ensemble spread

# Per-condition-type confidence multiplier applied on top of horizon discount (#14/#39).
# Precipitation forecasts have higher irreducible uncertainty; snow requires two
# thresholds (precip AND temperature), making it the hardest to forecast.
_CONDITION_CONFIDENCE: dict[str, float] = {
    "above": 1.00,
    "below": 1.00,
    "between": 1.00,
    "precip_any": 0.90,
    "precip_above": 0.85,
    "precip_snow": 0.80,
}


def _confidence_scaled_blend_weights(
    days_out: int,
    has_nws: bool,
    has_clim: bool,
    ens_std: float | None = None,
    city: str | None = None,
    season: str | None = None,
) -> tuple[float, float, float]:
    """#31: _blend_weights scaled by inverse ensemble variance."""
    w_ens, w_clim, w_nws = _blend_weights(
        days_out, has_nws, has_clim, city=city, season=season
    )
    if ens_std is None or ens_std <= 0:
        return w_ens, w_clim, w_nws
    scale = max(0.5, min(1.5, _ENS_STD_REF / ens_std))
    # Clamp w_ens_scaled so it cannot exceed the available weight budget (w_ens stays ≤ 1.0)
    w_ens_scaled = min(w_ens * scale, 1.0)
    delta = w_ens - w_ens_scaled
    total_others = w_clim + w_nws
    if total_others > 0:
        w_clim_new = w_clim + delta * (w_clim / total_others)
        w_nws_new = w_nws + delta * (w_nws / total_others)
    else:
        w_clim_new = w_clim
        w_nws_new = w_nws
    total = w_ens_scaled + w_clim_new + w_nws_new
    return w_ens_scaled / total, w_clim_new / total, w_nws_new / total


def wet_bulb_temp(temp_f: float, rh_pct: float) -> float:
    """#34: Stull (2011) wet-bulb temperature approximation."""
    import math as _math

    T = (temp_f - 32) * 5 / 9
    RH = rh_pct
    Tw_c = (
        T * _math.atan(0.151977 * (RH + 8.313659) ** 0.5)
        + _math.atan(T + RH)
        - _math.atan(RH - 1.676331)
        + 0.00391838 * RH**1.5 * _math.atan(0.023101 * RH)
        - 4.686035
    )
    return Tw_c * 9 / 5 + 32


def snow_liquid_ratio(wet_bulb_f: float) -> int:
    """#34: Empirical SLR from wet-bulb temp (NOAA operational).
    >32°F → 0 (rain), 28-32°F → 10, 20-28°F → 15, <=20°F → 20.
    """
    if wet_bulb_f > 32.0:
        return 0
    elif wet_bulb_f > 28.0:
        return 10
    elif wet_bulb_f > 20.0:
        return 15
    else:
        return 20


def liquid_equiv_of_snow_threshold(snow_inches: float, slr: int) -> float:
    """#34: Convert snow threshold (inches) to liquid water equivalent."""
    if slr <= 0:
        return float("inf")
    return snow_inches / slr


def _blend_probabilities(
    ensemble_prob: float | None,
    nws_prob: float | None,
    clim_prob: float | None,
    days_out: int = 3,
) -> float | None:
    """
    #33: Blend ensemble, NWS, and climatological probabilities with NWS always included.

    NWS weights:
      days_out 0–3: 0.35
      days_out 4–7: 0.25
      days_out 7+:  0.10

    Handles None inputs by renormalizing weights among available sources.
    Returns None only if all inputs are None.
    """
    if days_out <= 3:
        w_nws_base = 0.35
    elif days_out <= 7:
        w_nws_base = 0.25
    else:
        w_nws_base = 0.10

    # Remaining weight split evenly between ensemble and clim
    w_rem = 1.0 - w_nws_base
    w_ens_base = w_rem * 0.65  # ensemble gets ~2/3 of remaining
    w_clim_base = w_rem * 0.35  # climatology gets ~1/3 of remaining

    sources = []
    if ensemble_prob is not None:
        sources.append((ensemble_prob, w_ens_base))
    if nws_prob is not None:
        sources.append((nws_prob, w_nws_base))
    if clim_prob is not None:
        sources.append((clim_prob, w_clim_base))

    if not sources:
        return None

    total_w = sum(w for _, w in sources)
    return sum(p * w for p, w in sources) / total_w


def bayesian_kelly(
    ci_low: float,
    ci_high: float,
    price: float,
    fee_rate: float = KALSHI_FEE_RATE,
    n_steps: int = 50,
) -> float:
    """
    #39: Bayesian Kelly — integrate kelly_fraction over a uniform posterior on
    [ci_low, ci_high] rather than using the point-estimate probability.

    A uniform posterior is the maximum-entropy choice given only CI bounds.
    Averaging Kelly over the distribution gives a more conservative sizing that
    accounts for genuine uncertainty in the probability estimate.

    Returns 0.0 when the CI is trivially wide (full [0, 1] range).
    """
    ci_low = max(0.01, ci_low)
    ci_high = min(0.99, ci_high)
    if ci_high <= ci_low:
        return kelly_fraction(ci_low, price, fee_rate)
    if ci_high - ci_low >= 0.99:
        return 0.0  # no information — don't bet

    step = (ci_high - ci_low) / n_steps
    total = 0.0
    for i in range(n_steps + 1):
        p = ci_low + i * step
        total += kelly_fraction(p, price, fee_rate)
    return round(total / (n_steps + 1), 6)


def bayesian_kelly_fraction(
    our_prob: float,
    market_prob: float,
    n_predictions: int = 20,
    confidence: float = 0.90,
    fee_rate: float = KALSHI_FEE_RATE,
) -> float:
    """
    #39: Bayesian Kelly with Beta posterior uncertainty shrinkage.

    Builds a Beta(alpha, beta) posterior from n_predictions pseudo-observations
    centred on our_prob, then uses the Wilson lower bound at `confidence` as a
    conservative probability estimate before calling kelly_fraction.

    Alpha = our_prob * n_predictions + 1
    Beta  = (1 - our_prob) * n_predictions + 1

    The Wilson lower bound at `confidence` is the (1-confidence)/2 quantile of
    the Beta distribution, approximated via a normal approximation on the logit
    scale (suitable for probabilities not near 0 or 1).

    Returns kelly_fraction(conservative_p, market_prob), capped at 0.25.
    Never returns a negative value.
    """
    import math

    our_prob = max(0.01, min(0.99, our_prob))
    market_prob = max(0.01, min(0.99, market_prob))

    alpha = our_prob * n_predictions + 1.0
    beta = (1.0 - our_prob) * n_predictions + 1.0
    n_total = alpha + beta

    # Beta mean and variance
    mu = alpha / n_total
    var = (alpha * beta) / (n_total**2 * (n_total + 1))
    sigma = math.sqrt(var)

    # Normal approximation: lower bound at (1 - confidence) / 2 tail
    z = _normal_quantile((1.0 - confidence) / 2.0)  # negative value for lower tail
    conservative_p = mu + z * sigma  # z is negative, so this shrinks toward 0

    conservative_p = max(0.01, min(0.99, conservative_p))
    result = kelly_fraction(conservative_p, market_prob, fee_rate=fee_rate)
    return min(max(0.0, result), 0.25)


def _normal_quantile(p: float) -> float:
    """Approximate inverse CDF of the standard normal (rational approximation)."""
    import math

    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    # Rational approximation (Abramowitz & Stegun 26.2.17)
    c = [2.515517, 0.802853, 0.010328]
    d = [1.432788, 0.189269, 0.001308]
    t = math.sqrt(-2.0 * math.log(p if p < 0.5 else 1.0 - p))
    num = c[0] + c[1] * t + c[2] * t**2
    den = 1.0 + d[0] * t + d[1] * t**2 + d[2] * t**3
    x = t - num / den
    return -x if p < 0.5 else x


def _bootstrap_ci(
    temps: list[float], condition: dict, n: int = 500
) -> tuple[float, float]:
    """
    Bootstrap 90% confidence interval on the ensemble probability estimate.
    #114: Returns (0.0, 1.0) wide CI if N < 30 (too few for reliable estimate).
    #128: Caps bootstrap reps at 1000 and subsamples large ensembles.
    """
    if len(temps) < 5:
        return (0.0, 1.0)
    if len(temps) < 30:
        # Too few members for a reliable CI; return maximally uncertain
        return (0.0, 1.0)

    # Cap reps and subsample huge ensembles to avoid slowness
    n = min(n, 1000)
    sample_temps = temps if len(temps) <= 10_000 else random.sample(temps, 10_000)

    def prob_from(sample):
        if condition["type"] == "above":
            return sum(1 for t in sample if t > condition["threshold"]) / len(sample)
        elif condition["type"] == "below":
            return sum(1 for t in sample if t < condition["threshold"]) / len(sample)
        else:
            lo, hi = condition["lower"], condition["upper"]
            return sum(1 for t in sample if lo <= t <= hi) / len(sample)

    k = len(sample_temps)
    boot = sorted(prob_from(random.choices(sample_temps, k=k)) for _ in range(n))
    p05 = boot[min(int(n * 0.05), n - 1)]
    p95 = boot[min(int(n * 0.95), n - 1)]
    return (p05, p95)


def _bootstrap_ci_precip(
    members: list[float], condition: dict, n: int = 500
) -> tuple[float, float]:
    """Bootstrap 90% CI for a precipitation ensemble probability."""
    if len(members) < 5:
        return (0.0, 1.0)

    def prob_from(sample: list[float]) -> float:
        if condition["type"] == "precip_any":
            return sum(1 for p in sample if p > 0.01) / len(sample)
        thresh = condition.get("threshold", 0.0)
        return sum(1 for p in sample if p > thresh) / len(sample)

    k = len(members)
    boot = sorted(prob_from(random.choices(members, k=k)) for _ in range(n))
    return (boot[min(int(n * 0.05), n - 1)], boot[min(int(n * 0.95), n - 1)])


def edge_confidence(days_out: int, condition_type: str | None = None) -> float:
    """Horizon + condition discount factor for edge signal (#63/#14).

    Combines the existing piecewise horizon discount with a per-condition
    multiplier from _CONDITION_CONFIDENCE. Precipitation and snow markets are
    inherently harder to forecast, so their effective edge is discounted further.

    Piecewise linear horizon:
      days_out 0–2  : 1.00
      days_out 3–7  : linear 1.00 → 0.80
      days_out 8–14 : linear 0.80 → 0.60
      days_out > 14 : 0.60 (floor)
    """
    if days_out <= 2:
        horizon = 1.0
    elif days_out <= 7:
        horizon = 1.0 - (days_out - 2) / 5.0 * 0.20
    elif days_out <= 14:
        horizon = 0.80 - (days_out - 7) / 7.0 * 0.20
    else:
        horizon = 0.60
    cond = _CONDITION_CONFIDENCE.get(condition_type or "", 1.0)
    return round(horizon * cond, 4)


def _get_consensus_probs(
    city: str,
    target_date,
    condition: dict,
    hour: int | None = None,
    var: str = "max",
) -> tuple[float | None, float | None, float | None, float | None]:
    """Fetch per-model ensemble probabilities for ICON and GFS separately.

    Returns (icon_prob, gfs_prob). Either may be None if that model returned
    fewer than 5 members. Used for model_consensus check in analyze_trade().
    Only supports temperature conditions (above/below/range).
    """

    def _model_prob_and_mean(model_name: str) -> tuple[float | None, float | None]:
        """Return (prob, mean_temp) for model_name. Either may be None."""
        try:
            coords = CITY_COORDS.get(city)
            if not coords:
                return None, None
            lat, lon = coords[0], coords[1]
            tz = coords[2] if len(coords) > 2 else "UTC"
            var_field = f"temperature_2m_{'max' if var == 'max' else 'min'}"
            cache_key = (model_name, city, target_date.isoformat(), var, hour)
            cached = _ENSEMBLE_CACHE.get(cache_key)
            if cached:
                temps, ts = cached
                if time.time() - ts < _ENSEMBLE_CACHE_TTL:
                    pass  # use cached
                else:
                    temps = None
            else:
                temps = None

            if temps is None:
                if _ensemble_cb.is_open():
                    _log.warning(
                        "[CircuitBreaker] open_meteo circuit open — skipping ensemble fetch"
                    )
                    return None, None
                params = {
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": tz,
                    "daily": [var_field],
                    "temperature_unit": "fahrenheit",
                    "models": model_name,
                    "start_date": target_date.isoformat(),
                    "end_date": target_date.isoformat(),
                    "forecast_days": 7,
                }
                try:
                    resp = _om_request("GET", ENSEMBLE_BASE, params=params, timeout=20)
                    if not resp:
                        return None, None
                    resp.raise_for_status()
                    _ensemble_cb.record_success()
                except Exception as _exc:
                    _ensemble_cb.record_failure()
                    _log.warning("open_meteo ensemble fetch failed: %s", _exc)
                    return None, None
                data = resp.json()
                daily = data.get("daily", {})
                members = [
                    float(v[0])
                    for k, v in daily.items()
                    if k.startswith(var_field) and v and v[0] is not None
                ]
                temps = members
                _ENSEMBLE_CACHE[cache_key] = (temps, time.time())

            if len(temps) < 5:
                return None, None

            mean_temp = round(sum(temps) / len(temps), 2)
            thresh = condition.get("threshold")
            ctype = condition.get("type", "")
            if ctype == "above" and thresh is not None:
                return sum(1 for t in temps if t > thresh) / len(temps), mean_temp
            elif ctype == "below" and thresh is not None:
                return sum(1 for t in temps if t < thresh) / len(temps), mean_temp
            elif ctype == "range":
                lo = condition.get("lower", 0)
                hi = condition.get("upper", 999)
                return sum(1 for t in temps if lo <= t <= hi) / len(temps), mean_temp
            return None, mean_temp
        except Exception:
            return None, None

    icon_prob, icon_mean = _model_prob_and_mean("icon_seamless")
    gfs_prob, gfs_mean = _model_prob_and_mean("gfs_seamless")
    return icon_prob, gfs_prob, icon_mean, gfs_mean


def kelly_fraction(our_prob: float, price: float, fee_rate: float = 0.0) -> float:
    """
    Half-Kelly criterion for a binary prediction market.
    price    = cost per contract in dollars (e.g. 0.30 means you pay $0.30, win $0.70)
    fee_rate = fraction of winnings charged as fee (e.g. 0.07 for Kalshi's 7% fee)
    Returns recommended fraction of bankroll to bet (0–1).

    Kelly formula: f* = (b*p - q) / b  where b = net odds (win per $1 risked)
    For Kalshi: you pay `price`, win `(1-price)*(1-fee_rate)` net of fee.
    Net odds b = (1-price)*(1-fee_rate) / price
    """
    if our_prob <= 0 or our_prob >= 1 or price <= 0 or price >= 1:
        return 0.0
    winnings = (1 - price) * (1 - fee_rate)  # net winnings per contract after fee
    b = winnings / price  # net odds: win $b for every $1 staked
    q = 1 - our_prob
    full_kelly = (b * our_prob - q) / b
    half_kelly = max(0.0, full_kelly / 2)  # half-Kelly for safety
    return min(half_kelly, 0.33)  # hard cap at 33% of bankroll


def time_decay_edge(
    raw_edge: float,
    close_time: datetime,
    reference_hours: float = 48.0,
) -> float:
    """
    #63: Scale edge linearly to zero as the market approaches close.

    At reference_hours or more before close: full edge returned.
    At close_time or past: 0.0 returned.

    hours_left = (close_time - now).total_seconds() / 3600
    decay      = min(1.0, hours_left / reference_hours)   clamped at [0, 1]
    returns    raw_edge * decay
    """
    now = datetime.now(UTC)
    hours_left = (close_time - now).total_seconds() / 3600
    if hours_left <= 0.0:
        return 0.0
    decay = min(1.0, hours_left / reference_hours)
    return raw_edge * decay


def _fetch_ensemble_precip(
    lat: float, lon: float, tz: str, target_date: date
) -> list[float]:
    """
    Fetch ensemble precipitation members (inches) for a city/date.
    ECMWF is fetched separately and appended twice (2× weight) to match the
    temperature ensemble weighting in _model_weights().
    """
    results = []
    target_str = target_date.isoformat()
    prefix = "precipitation_sum_member"
    date_in_range = False  # #35: track whether any model covered this date

    def _fetch_model(model: str) -> list[float]:
        nonlocal date_in_range
        if _ensemble_cb.is_open():
            _log.warning(
                "[CircuitBreaker] open_meteo circuit open — skipping ensemble fetch"
            )
            return []
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "models": model,
                "daily": "precipitation_sum",
                "precipitation_unit": "inch",
                "timezone": tz,
                "forecast_days": 16,
            }
            resp = _om_request("GET", ENSEMBLE_BASE, params=params, timeout=20)
            resp.raise_for_status()
            _ensemble_cb.record_success()
            daily = resp.json().get("daily", {})
            times = daily.get("time", [])
            if target_str not in times:
                return []
            date_in_range = True  # at least one model has this date
            idx = times.index(target_str)
            return [
                vals[idx]
                for k, vals in daily.items()
                if k.startswith(prefix) and vals[idx] is not None
            ]
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.warning("open_meteo ensemble fetch failed: %s", _exc)
            return []

    for model in ENSEMBLE_MODELS:
        results.extend(_fetch_model(model))

    # ECMWF weighted 3× in winter, 2× in summer (seasonal accuracy advantage)
    ecmwf_members = _fetch_model("ecmwf_ifs04")
    ecmwf_mult = 3 if target_date.month in (10, 11, 12, 1, 2, 3) else 2
    results.extend(ecmwf_members * ecmwf_mult)

    # #70: return None instead of [] when no members fetched (caller can distinguish)
    if not results and not date_in_range:
        return None  # type: ignore[return-value]  # date outside forecast range
    return results


def _analyze_precip_trade(
    enriched: dict, forecast: dict, condition: dict, target_date: date, coords: tuple
) -> dict | None:
    """
    Probability analysis for precipitation markets (rain/snow).
    Uses ensemble precipitation members + climatological rain frequency.
    """
    lat, lon, tz = coords
    days_out = max(0, (target_date - date.today()).days)

    # ── Ensemble precipitation probability ───────────────────────────────────
    _raw_members = _fetch_ensemble_precip(lat, lon, tz, target_date)
    precip_members: list[float] = _raw_members if _raw_members is not None else []
    ens_prob: float | None = None
    if len(precip_members) >= 10:
        if condition["type"] == "precip_any":
            ens_prob = sum(1 for p in precip_members if p > 0.01) / len(precip_members)
        else:
            thresh = condition["threshold"]
            ens_prob = sum(1 for p in precip_members if p > thresh) / len(
                precip_members
            )

    # ── Forecast precip as fallback ───────────────────────────────────────────
    forecast_precip = forecast.get("precip_in", 0.0) or 0.0
    if ens_prob is None:
        # Normal distribution around forecast precip
        sigma = max(0.2, forecast_precip * 0.5)
        if condition["type"] == "precip_any":
            ens_prob = 1.0 - normal_cdf(0.01, forecast_precip, sigma)
        else:
            ens_prob = 1.0 - normal_cdf(condition["threshold"], forecast_precip, sigma)

    # ── Same-day live precipitation observation override ─────────────────────
    obs_precip_val: float | None = None
    if days_out == 0:
        try:
            from nws import get_live_precip_obs

            obs_precip_raw = get_live_precip_obs(enriched.get("_city", ""), coords)
            if obs_precip_raw is not None:
                obs_precip_val = obs_precip_raw
        except Exception:
            pass

    # ── Dynamic blend weights (mirrors temperature path) ─────────────────────
    w_ens, w_clim, _ = _blend_weights(
        days_out, has_nws=False, has_clim=True
    )  # calibration not yet wired for precip/snow path
    clim_prior = 0.30  # rough historical rain frequency as fallback prior
    blended_prob = ens_prob * w_ens + clim_prior * w_clim

    # Same-day override: observation is near-certain (precip already fell or didn't)
    if obs_precip_val is not None:
        if condition["type"] == "precip_any":
            obs_p = 1.0 if obs_precip_val > 0.01 else 0.0
        else:
            obs_p = 1.0 if obs_precip_val > condition.get("threshold", 0.0) else 0.0
        blended_prob = 0.90 * obs_p + 0.10 * blended_prob

    # ── Bias correction from tracker (same as temperature path) ──────────────
    bias = 0.0
    try:
        from tracker import get_bias

        city = enriched.get("_city")
        bias = get_bias(city, target_date.month, condition_type=condition["type"])
        blended_prob = blended_prob - bias
    except Exception as _exc:
        # #109: log with ticker so failures are traceable
        _log.debug(
            "Bias correction skipped for %s: %s", enriched.get("ticker", "?"), _exc
        )

    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"
    entry_price = prices["yes_ask"] if rec_side == "yes" else prices["no_bid"]
    if entry_price == 0:
        entry_price = 1 - market_prob if rec_side == "no" else market_prob

    payout = 1 - entry_price
    p_win = blended_prob if rec_side == "yes" else 1 - blended_prob
    net_ev = p_win * payout * (1 - KALSHI_FEE_RATE) - (1 - p_win) * entry_price
    net_edge = net_ev / entry_price if entry_price > 0 else 0.0
    edge = blended_prob - market_prob
    kelly = kelly_fraction(p_win, entry_price)
    fee_kel = kelly_fraction(p_win, entry_price, fee_rate=KALSHI_FEE_RATE)

    # ── Bootstrap CI on precip ensemble ──────────────────────────────────────
    ci_low, ci_high = blended_prob, blended_prob
    if len(precip_members) >= 5:
        ci_low, ci_high = _bootstrap_ci_precip(precip_members, condition)

    # ── Consensus signal for precip: ensemble and clim_prior agree with blend ──
    precip_consensus = (
        (
            (ens_prob > 0.5 and clim_prior > 0.5 and blended_prob > 0.5)
            or (ens_prob < 0.5 and clim_prior < 0.5 and blended_prob < 0.5)
        )
        if ens_prob is not None
        else False
    )

    # #39: Bayesian Kelly — integrate over uniform posterior on CI range
    ci_adj_kelly = bayesian_kelly(
        ci_low, ci_high, entry_price, fee_rate=KALSHI_FEE_RATE
    )
    if precip_consensus:
        ci_adj_kelly = round(ci_adj_kelly * 1.25, 6)
    condition_type_scale = _CONDITION_CONFIDENCE.get(condition["type"], 1.0)
    ci_adj_kelly = round(ci_adj_kelly * condition_type_scale, 6)
    ci_adj_kelly = min(ci_adj_kelly, 0.25)

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge),
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast_precip,  # precipitation in inches (reuses key for table display)
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": None,
        "clim_adj_prob": None,
        "obs_prob": obs_precip_val,
        "live_obs": obs_precip_val,
        "index_adj": 0.0,
        "bias_correction": bias,
        "blend_sources": {"ensemble": w_ens, "climatology": w_clim},
        "method": "precip_ensemble" if precip_members else "precip_normal",
        "ensemble_stats": None,
        "n_members": len(precip_members),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": kelly,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "time_risk": "HIGH",
        "consensus": precip_consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
    }


def _analyze_snow_trade(
    enriched: dict, forecast: dict, condition: dict, target_date: date, coords: tuple
) -> dict | None:
    """
    Probability analysis for snow/ice markets.
    Uses ensemble precipitation probability as a proxy for snow probability.
    Falls back to a climatological base rate: 20% in winter (Dec-Feb), 5% otherwise.
    """
    lat, lon, tz = coords
    days_out = max(0, (target_date - date.today()).days)

    # ── Ensemble precipitation as proxy ──────────────────────────────────────
    _raw_snow = _fetch_ensemble_precip(lat, lon, tz, target_date)
    precip_members: list[float] = _raw_snow if _raw_snow is not None else []
    ens_prob: float | None = None
    threshold = condition.get("threshold", 0.0)

    # #34: Wet-bulb SLR — convert snow threshold to liquid equivalent for comparison
    _forecast_temp = forecast.get("high_f") or forecast.get("low_f") or 32.0
    _forecast_rh = forecast.get("humidity_pct") or 80.0
    try:
        _wb = wet_bulb_temp(float(_forecast_temp), float(_forecast_rh))
        _slr = snow_liquid_ratio(_wb)
    except Exception:
        _slr = 10  # fallback: 1:10 ratio

    if len(precip_members) >= 10:
        if threshold <= 0.0:
            ens_prob = sum(1 for p in precip_members if p > 0.01) / len(precip_members)
        else:
            if _slr == 0:
                ens_prob = 0.01  # essentially no snow above freezing
            else:
                liquid_thresh = liquid_equiv_of_snow_threshold(threshold, _slr)
                ens_prob = sum(1 for p in precip_members if p > liquid_thresh) / len(
                    precip_members
                )

    # ── Climatological base rate fallback ────────────────────────────────────
    is_winter_month = target_date.month in (12, 1, 2)
    clim_prior = 0.20 if is_winter_month else 0.05

    if ens_prob is None:
        ens_prob = clim_prior

    # ── Blend ensemble with climatological prior ──────────────────────────────
    w_ens, w_clim, _ = (
        _confidence_scaled_blend_weights(  # calibration not yet wired for precip/snow path
            days_out, has_nws=False, has_clim=True, ens_std=None
        )
    )
    blended_prob = ens_prob * w_ens + clim_prior * w_clim
    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"
    entry_price = prices["yes_ask"] if rec_side == "yes" else prices["no_bid"]
    if entry_price == 0:
        entry_price = 1 - market_prob if rec_side == "no" else market_prob

    payout = 1 - entry_price
    p_win = blended_prob if rec_side == "yes" else 1 - blended_prob
    net_ev = p_win * payout * (1 - KALSHI_FEE_RATE) - (1 - p_win) * entry_price
    net_edge = net_ev / entry_price if entry_price > 0 else 0.0
    edge = blended_prob - market_prob
    kelly = kelly_fraction(p_win, entry_price)
    fee_kel = kelly_fraction(p_win, entry_price, fee_rate=KALSHI_FEE_RATE)

    ci_low, ci_high = blended_prob, blended_prob
    if len(precip_members) >= 5:
        ci_low, ci_high = _bootstrap_ci_precip(precip_members, condition)

    # #39: Bayesian Kelly
    ci_adj_kelly = bayesian_kelly(
        ci_low, ci_high, entry_price, fee_rate=KALSHI_FEE_RATE
    )
    condition_type_scale = _CONDITION_CONFIDENCE.get(condition["type"], 1.0)
    ci_adj_kelly = round(ci_adj_kelly * condition_type_scale, 6)
    ci_adj_kelly = min(ci_adj_kelly, 0.25)

    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf

    return {
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": _edge_label(edge),
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": _edge_label(adjusted_edge),
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast.get("high_f") or forecast.get("temp_high") or 0.0,
        "ensemble_prob": ens_prob,
        "nws_prob": None,
        "clim_prob": clim_prior,
        "clim_adj_prob": None,
        "obs_prob": None,
        "live_obs": None,
        "index_adj": 0.0,
        "bias_correction": 0.0,
        "blend_sources": {"ensemble": w_ens, "climatology": w_clim},
        "method": "snow_ensemble" if len(precip_members) >= 10 else "snow_clim",
        "ensemble_stats": None,
        "n_members": len(precip_members),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": kelly,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "time_risk": "HIGH",
        "consensus": False,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
    }


def analyze_trade(enriched: dict) -> dict | None:
    """
    Full multi-source trade analysis pipeline:
      1. Ensemble probability (80+ members, ICON + GFS)
      2. NWS official forecast probability
      3. Climatological baseline (30yr history)
      4. Climate index adjustment (AO, NAO, ENSO) on climatology
      5. Live observation override for same-day markets
      6. Weighted blend by days-out
      7. Bias correction from tracker (if data available)
      8. Bootstrap confidence interval
      9. Kelly fraction
    """
    # #116: explicit precondition check with helpful error context
    if not isinstance(enriched, dict):
        raise ValueError(
            f"analyze_trade: enriched must be a dict, got {type(enriched)}"
        )
    forecast = enriched.get("_forecast")
    target_date = enriched.get("_date")
    city = enriched.get("_city")
    hour = enriched.get("_hour")
    if not forecast:
        return None  # no forecast data available for this market
    if not target_date:
        return None  # could not parse target date from ticker
    if not city:
        return None  # unrecognized city in ticker

    # P0.3: Reject stale enriched data. Absence of timestamp → treat as fresh.
    import time as _time_wm

    _fetched_at = enriched.get("data_fetched_at")
    if _fetched_at is not None:
        data_age = _time_wm.time() - _fetched_at
        if data_age > FORECAST_MAX_AGE_SECS:
            _log.warning(
                "analyze_trade: rejecting stale data for %s (age=%.0fs > limit=%ds)",
                enriched.get("ticker", "?"),
                data_age,
                FORECAST_MAX_AGE_SECS,
            )
            return None

    condition = _parse_market_condition(enriched)
    if not condition:
        return None

    coords = CITY_COORDS.get(city)
    if not coords:
        return None

    # ── Days-out gate: only trade markets expiring within MAX_DAYS_OUT days ──
    _days_out_check = max(0, (target_date - date.today()).days)
    if _days_out_check > MAX_DAYS_OUT:
        return None

    # ── Liquidity gate: skip markets with no real open interest ──────────────
    # Accept both legacy (volume/open_interest) and current API names (volume_fp/open_interest_fp)
    _vol = float(enriched.get("volume_fp") or enriched.get("volume") or 0) + float(
        enriched.get("open_interest_fp") or enriched.get("open_interest") or 0
    )
    if _vol < MIN_LIQUIDITY:
        return None

    # ── Spread gate: skip illiquid markets with wide bid-ask spreads ─────────
    _prices = parse_market_price(enriched)
    _yes_ask = _prices.get("yes_ask", 0) or 0
    _yes_bid = _prices.get("yes_bid", 0) or 0
    if _yes_ask > 0 and _yes_bid > 0:
        _mid = (_yes_ask + _yes_bid) / 2
        if _mid > 0 and (_yes_ask - _yes_bid) / _mid > 0.30:
            return None  # spread > 30% of mid — not tradeable

    # ── Time-of-day risk assessment ──────────────────────────────────────────
    _tz = coords[2] if len(coords) > 2 else "UTC"
    time_risk_label, sigma_mult = _time_risk(enriched.get("close_time", ""), _tz)

    # ── Precipitation market fast-path ───────────────────────────────────────
    if condition["type"] in ("precip_above", "precip_any"):
        result = _analyze_precip_trade(
            enriched, forecast, condition, target_date, coords
        )
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── Snow/ice market fast-path ─────────────────────────────────────────────
    if condition["type"] == "precip_snow":
        result = _analyze_snow_trade(enriched, forecast, condition, target_date, coords)
        if result is not None:
            result["time_risk"] = time_risk_label
            result["edge_calc_version"] = EDGE_CALC_VERSION
        return result

    # ── METAR same-day lock-in check ─────────────────────────────────────────
    # After 2 PM local time, if METAR confirms the outcome, skip slow ensemble.
    metar_locked = False
    metar_lockout: dict = {}
    _metar_obs = None
    try:
        import metar as _metar

        _metar_sta = _metar_station_for_city(city)
        if (
            _metar_sta
            and target_date == date.today()
            and condition.get("type") in ("above", "below")
            and condition.get("threshold")
        ):
            _metar_obs = _metar.fetch_metar(_metar_sta)
            if _metar_obs:
                _metar_lockout = _metar.check_metar_lockout(
                    current_temp_f=_metar_obs["current_temp_f"],
                    threshold_f=float(condition["threshold"]),
                    direction=condition["type"],
                    obs_time=_metar_obs["obs_time"],
                    city_tz=_CITY_TZ.get(city, "America/New_York"),
                )
                if _metar_lockout["locked"]:
                    metar_locked = True
                    metar_lockout = _metar_lockout
                    _metar_p = (
                        _metar_lockout["confidence"]
                        if _metar_lockout["outcome"] == "yes"
                        else (1.0 - _metar_lockout["confidence"])
                    )
                    _log.info(
                        "METAR lock-in %s: %s (conf=%.0f%%) — %s",
                        enriched.get("ticker", "?"),
                        _metar_lockout["outcome"],
                        _metar_lockout["confidence"] * 100,
                        _metar_lockout["reason"],
                    )
                    blended_prob = max(0.01, min(0.99, _metar_p))
    except Exception as _metar_exc:
        _log.debug(
            "METAR lock-in check failed for %s: %s",
            enriched.get("ticker", "?"),
            _metar_exc,
        )
        metar_locked = False
        metar_lockout = {}

    if not metar_locked:
        series = (enriched.get("series_ticker") or enriched.get("ticker", "")).upper()
        var = "min" if "LOW" in series else "max"
        condition["var"] = var

        forecast_temp = forecast["low_f"] if var == "min" else forecast["high_f"]
        if forecast_temp is None:
            return None

        # Apply per-city static bias correction before probability calculation
        forecast_temp_raw = forecast_temp
        forecast_temp = apply_station_bias(city, forecast_temp)

        days_out = max(0, (target_date - date.today()).days)

    if not metar_locked:
        # ── 1. Ensemble probability ──────────────────────────────────────────────
        temps = get_ensemble_temps(city, target_date, hour=hour, var=var)

        # For hourly markets, use ensemble mean of the hourly temps as forecast_temp
        # (daily high is misleading for e.g. "temp at 9am" markets)
        if hour is not None and len(temps) >= 5:
            forecast_temp = statistics.mean(temps)
        ens_stats = ensemble_stats(temps) if len(temps) >= 10 else None
        method = "normal_dist"
        ens_prob: float | None = None

        if len(temps) >= 10:
            method = "ensemble"
            if condition["type"] == "above":
                ens_prob = sum(1 for t in temps if t > condition["threshold"]) / len(
                    temps
                )
            elif condition["type"] == "below":
                ens_prob = sum(1 for t in temps if t < condition["threshold"]) / len(
                    temps
                )
            else:
                lo, hi = condition["lower"], condition["upper"]
                ens_prob = sum(1 for t in temps if lo <= t <= hi) / len(temps)
        else:
            sigma = _forecast_uncertainty(target_date) * sigma_mult
            ens_prob = _forecast_probability(condition, forecast_temp, sigma)

        # ── Phase C: extended ensemble members (NBM + ECMWF AIFS) ───────────────
        model_temps: dict[str, float | None] = {}
        try:
            model_temps["nbm"] = fetch_temperature_nbm(city, target_date)
            model_temps["ecmwf"] = fetch_temperature_ecmwf(city, target_date)
        except Exception as _ext_exc:
            _log.debug(
                "Phase C extended ensemble fetch failed for %s: %s", city, _ext_exc
            )

        ensemble_spread_f = _compute_ensemble_spread(model_temps)

        # Convert temperature spread to probability spread
        # Rule of thumb: 1°F std dev ≈ 0.04 probability units at typical thresholds
        ensemble_spread_prob = ensemble_spread_f * 0.04 if ensemble_spread_f else 0.0

        # ── Phase C: Gaussian probability + blend with raw ensemble fraction ─────
        target_month = target_date.month
        sigma_gauss = get_historical_sigma(city, target_month)
        cond_type = condition.get("type", "above")
        if cond_type in ("above", "below"):
            p_win_gaussian = gaussian_probability(
                forecast_mean=forecast_temp,
                threshold=float(condition.get("threshold", 0)),
                sigma=sigma_gauss,
                direction=cond_type,
            )
        else:
            p_win_gaussian = None

        # Blend Gaussian with ensemble fraction (fall back to ens_prob if temps available)
        n_valid = len([t for t in model_temps.values() if t is not None])
        raw_fraction = sum(
            1
            for t in model_temps.values()
            if t is not None
            and (
                t > condition.get("threshold", 0)
                if condition.get("type") == "above"
                else t < condition.get("threshold", 0)
            )
        ) / max(1, n_valid)

        if (
            n_valid >= 1
            and condition.get("type") in ("above", "below")
            and p_win_gaussian is not None
        ):
            # Only blend when we have raw model_temps and a simple direction condition
            gaussian_blend = (
                0.6 * p_win_gaussian + 0.4 * raw_fraction
                if n_valid >= 3
                else 0.8 * p_win_gaussian + 0.2 * raw_fraction
            )
            # Only use Gaussian blend when large ensemble didn't produce a result
            if ens_prob is None:
                ens_prob = gaussian_blend

        # ── Model consensus check ────────────────────────────────────────────────
        model_consensus = True
        icon_forecast_mean: float | None = None
        gfs_forecast_mean: float | None = None
        if ens_prob is not None and len(temps) >= 10:
            try:
                icon_p, gfs_p, icon_forecast_mean, gfs_forecast_mean = (
                    _get_consensus_probs(
                        city, target_date, condition, hour=hour, var=var
                    )
                )
                if icon_p is not None and gfs_p is not None:
                    if abs(icon_p - gfs_p) > 0.12:
                        model_consensus = False
            except Exception as _e:
                _log.warning(
                    "analyze_trade: _get_consensus_probs failed for %s — defaulting to consensus=True: %s",
                    enriched.get("ticker", "?"),
                    _e,
                )

        # ── Near-threshold detection ─────────────────────────────────────────────
        threshold_val = condition.get("threshold")
        near_threshold = (
            threshold_val is not None and abs(forecast_temp - threshold_val) <= 3.0
        )

        # ── 2. NWS forecast probability ──────────────────────────────────────────
        _nws_prob: float | None = None
        try:
            _nws_prob = nws_prob(city, coords, target_date, condition)
        except Exception as _e:
            _log.warning(
                "analyze_trade: nws_prob failed for %s: %s",
                enriched.get("ticker", "?"),
                _e,
            )

        # ── 3+4. Climatological probability + climate index adjustment ───────────
        clim_prob_raw: float | None = None
        index_adj: float = 0.0
        try:
            clim_prob_raw = climatological_prob(city, coords, target_date, condition)
            index_adj = temperature_adjustment(city, target_date)
        except Exception as _e:
            _log.warning(
                "analyze_trade: climatological_prob failed for %s: %s",
                enriched.get("ticker", "?"),
                _e,
            )

        # Apply index adjustment by shifting the effective threshold
        clim_prob: float | None = None
        if clim_prob_raw is not None:
            # Shift the condition threshold by the index adjustment and recompute
            adj_condition = dict(condition)
            if condition["type"] in ("above", "below"):
                adj_condition["threshold"] = condition["threshold"] - index_adj
            elif condition["type"] == "between":
                adj_condition["lower"] = condition["lower"] - index_adj
                adj_condition["upper"] = condition["upper"] - index_adj
            clim_prob = climatological_prob(city, coords, target_date, adj_condition)
            if clim_prob is None:
                clim_prob = clim_prob_raw

        # ── 5. Live observation override (same-day markets) ──────────────────────
        live_obs: dict | None = None
        obs_override: float | None = None
        if days_out == 0:
            try:
                live_obs = get_live_observation(city, coords)
                if live_obs:
                    obs_override = obs_prob(live_obs, condition)
            except Exception:
                pass

        # ── 5b. Persistence baseline (days_out <= 2 only) ────────────────────────
        persistence_p: float | None = None
        if days_out <= 2:
            try:
                from climatology import persistence_prob as _persistence_prob
                from nws import get_live_observation as _get_live_obs

                _live = _get_live_obs(city, coords) if days_out <= 1 else None
                _live_temp = _live.get("temp_f") if _live else None
                _current_temp: float = (
                    float(_live_temp) if _live_temp is not None else forecast_temp_raw
                )
                _cond_type = condition["type"]
                _tlo = condition.get("threshold", condition.get("lower", forecast_temp))
                _thi = condition.get("upper")
                persistence_p = _persistence_prob(_cond_type, _tlo, _thi, _current_temp)
            except Exception:
                pass

        # ── 6. Weighted blend ────────────────────────────────────────────────────
        if obs_override is not None:
            # Same-day with live obs — trust almost entirely
            blended_prob = (
                obs_override * 0.95 + (ens_prob if ens_prob is not None else 0.5) * 0.05
            )
            blend_sources = {"obs": 0.95, "ensemble": 0.05}
        else:
            _month = (
                target_date.month
                if target_date
                else __import__("datetime").datetime.now().month
            )
            _season = {
                12: "winter",
                1: "winter",
                2: "winter",
                3: "spring",
                4: "spring",
                5: "spring",
                6: "summer",
                7: "summer",
                8: "summer",
                9: "fall",
                10: "fall",
                11: "fall",
            }.get(_month, "spring")
            w_ens, w_clim, w_nws = _confidence_scaled_blend_weights(
                days_out,
                _nws_prob is not None,
                clim_prob is not None,
                ens_std=ens_stats.get("std") if ens_stats else None,
                city=city,
                season=_season,
            )
            # #26: persistence baseline at 15% for days_out <= 2
            if persistence_p is not None and days_out <= 2:
                w_persist = 0.15
                scale = 1.0 - w_persist
                w_ens = w_ens * scale
                w_clim = w_clim * scale
                w_nws = w_nws * scale
            else:
                w_persist = 0.0
                persistence_p = None

            blended_prob = (
                w_ens * (ens_prob if ens_prob is not None else 0.5)
                + w_clim * (clim_prob if clim_prob is not None else 0.5)
                + w_nws * (_nws_prob if _nws_prob is not None else 0.5)
                + w_persist * (persistence_p if persistence_p is not None else 0.5)
            )
            blend_sources = {
                "ensemble": w_ens,
                "climatology": w_clim,
                "nws": w_nws,
                **({"persistence": w_persist} if w_persist > 0 else {}),
            }

        # ── 7. Bias correction from tracker ─────────────────────────────────────
        bias = 0.0
        try:
            from tracker import get_bias

            bias = get_bias(city, target_date.month, condition_type=condition["type"])
            blended_prob = max(0.01, min(0.99, blended_prob - bias))
        except Exception as _exc:
            # #109: log with ticker/city so failures are traceable
            _log.debug(
                "Bias correction skipped for %s (%s): %s",
                enriched.get("ticker", "?"),
                city,
                _exc,
            )

        # ── Consensus signal: all available sources agree on direction ───────────
        sources_with_data = [
            p for p in [ens_prob, _nws_prob, clim_prob] if p is not None
        ]
        consensus = len(sources_with_data) >= 2 and (
            all(p > 0.5 for p in sources_with_data)
            or all(p < 0.5 for p in sources_with_data)
        )

        # ── 8. Confidence interval (bootstrap on ensemble members) ───────────────
        ci_low, ci_high = (blended_prob, blended_prob)
        if temps:
            ci_low, ci_high = _bootstrap_ci(temps, condition)

        # ── 9. Data quality score ────────────────────────────────────────────────
        # 1.0 = all sources available; reduced by 0.25 per missing source.
        # Used to scale down Kelly sizing when we're flying partially blind.
        sources_available = sum(
            [
                ens_prob is not None,
                _nws_prob is not None,
                clim_prob is not None,
            ]
        )
        data_quality = round(sources_available / 3, 4)

        # Flag anomalously wide ensemble spread (models disagree strongly)
        anomalous = is_forecast_anomalous(ens_stats or {})

    else:
        # METAR locked: pre-assign all pipeline outputs so Kelly section can run
        series = (enriched.get("series_ticker") or enriched.get("ticker", "")).upper()
        var = "min" if "LOW" in series else "max"
        condition["var"] = var
        days_out = max(0, (target_date - date.today()).days)
        _fallback_temp = forecast["low_f"] if var == "min" else forecast["high_f"]
        forecast_temp = (
            _metar_obs["current_temp_f"] if _metar_obs else (_fallback_temp or 0.0)
        )
        forecast_temp_raw = forecast_temp
        temps = []
        ens_prob = None
        ens_stats = None
        method = "metar_lockout"
        _nws_prob = None
        clim_prob = None
        clim_prob_raw = None
        obs_override = None
        live_obs = None
        persistence_p = None
        blend_sources = {"metar_lockout": 1.0}
        bias = 0.0
        consensus = True
        model_consensus = True
        near_threshold = False
        icon_forecast_mean = None
        gfs_forecast_mean = None
        index_adj = 0.0
        _confidence_boost = 1.0
        ci_low = blended_prob
        ci_high = blended_prob
        data_quality = 1.0
        anomalous = False
        model_temps = {}
        ensemble_spread_f = 0.0
        ensemble_spread_prob = 0.0
        p_win_gaussian = None
        sigma_gauss = None

    # Regime detection
    _regime_info: dict = {}
    _confidence_boost = 1.0
    try:
        from regime import detect_regime as _detect_regime

        _regime_info = _detect_regime(city, ens_stats or {}, days_out)
        _confidence_boost = _regime_info.get("confidence_boost", 1.0)
    except Exception:
        pass

    # Log source availability for per-city reliability tracking
    try:
        from tracker import log_source_attempt as _log_src

        _log_src(city, "ensemble", ens_prob is not None)
        _log_src(city, "nws", _nws_prob is not None)
        _log_src(city, "climatology", clim_prob is not None)
    except Exception:
        pass

    # ── 10. Kelly fraction ───────────────────────────────────────────────────
    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"
    entry_price = prices["yes_ask"] if rec_side == "yes" else prices["no_bid"]
    if entry_price == 0:
        entry_price = 1 - market_prob if rec_side == "no" else market_prob
    kelly = kelly_fraction(
        blended_prob if rec_side == "yes" else 1 - blended_prob, entry_price
    )

    # ── 10a. Bid-ask spread cost ─────────────────────────────────────────────
    # Wide spreads mean real slippage beyond the Kalshi fee.
    # Use the actual spread as a fraction of mid; default 5% for illiquid markets.
    yes_ask_p, yes_bid_p = prices["yes_ask"], prices["yes_bid"]
    if yes_ask_p > 0 and yes_bid_p > 0 and yes_ask_p > yes_bid_p:
        spread_abs = yes_ask_p - yes_bid_p
        mid_p = (yes_ask_p + yes_bid_p) / 2
        spread_cost = spread_abs / mid_p if mid_p > 0 else 0.05
    else:
        spread_cost = 0.05  # conservative default for markets with no live quote
    # A 5% spread → 10% reduction; 25% spread → 50% reduction; floor at 0.50
    spread_scale = max(0.50, 1.0 - spread_cost * 2)

    # ── MOS forecast (station-specific post-processing) ──────────────────
    mos_data = None
    try:
        import mos as _mos

        _mos_station = _mos.get_mos_station(city)
        if _mos_station:
            mos_data = _mos.fetch_mos(_mos_station, target_date=target_date)
    except Exception:
        pass

    # If MOS data available, blend it with blended_prob before edge computation
    if mos_data and mos_data.get("max_temp_f") is not None:
        _mos_temp = mos_data["max_temp_f"]
        try:
            _mos_sigma = _forecast_uncertainty(target_date)
            _mos_p = _forecast_probability(condition, _mos_temp, _mos_sigma)
            if _mos_p is not None:
                # Blend: 50% existing blended + 50% MOS-based probability
                blended_prob = 0.5 * blended_prob + 0.5 * _mos_p
                blended_prob = max(0.01, min(0.99, blended_prob))
        except Exception as _mos_exc:
            _log.debug("MOS probability blend failed for %s: %s", city, _mos_exc)

    edge = blended_prob - market_prob

    # #63: Time-decay edge — scale linearly to zero as market approaches close
    _close_str = enriched.get("close_time", "")
    if _close_str:
        try:
            _close_dt = datetime.fromisoformat(_close_str.replace("Z", "+00:00"))
            edge = time_decay_edge(edge, _close_dt, reference_hours=48.0)
        except (ValueError, TypeError):
            pass

    signal = _edge_label(edge)

    # #61: entry-side edge uses actual ask/bid rather than mid-price
    if rec_side == "yes":
        entry_side_market_prob = (
            prices["yes_ask"] if prices["yes_ask"] > 0 else market_prob
        )
    else:
        entry_side_market_prob = (
            (1 - prices["no_bid"]) if prices["no_bid"] > 0 else market_prob
        )
    entry_side_edge = blended_prob - entry_side_market_prob

    # #62: explicit illiquid flag (spread > 5%)
    illiquid = spread_cost > 0.05

    # ── 11. Fee-adjusted edge ────────────────────────────────────────────────
    if rec_side == "yes":
        payout = 1 - entry_price
        net_ev = (
            blended_prob * payout * (1 - KALSHI_FEE_RATE)
            - (1 - blended_prob) * entry_price
        )
    else:
        payout = 1 - entry_price
        p_win = 1 - blended_prob
        net_ev = p_win * payout * (1 - KALSHI_FEE_RATE) - blended_prob * entry_price

    net_edge = net_ev / entry_price if entry_price > 0 else 0.0
    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf
    net_signal = _edge_label(adjusted_edge)
    fee_adjusted_kelly = kelly_fraction(
        blended_prob if rec_side == "yes" else 1 - blended_prob,
        entry_price,
        fee_rate=KALSHI_FEE_RATE,
    )

    # Scale Kelly down for low data quality and anomalous forecasts
    quality_scale = 0.5 + 0.5 * data_quality  # 0.5 at quality=0, 1.0 at quality=1
    anomaly_scale = 0.70 if anomalous else 1.0

    # Time-value Kelly: reduce bet size for far-out markets (more uncertainty).
    # Scale: 1.0 at 0-1 days → 0.5 at ≥14 days. Intermediate values are linear.
    time_kelly_scale = max(0.35, 1.0 - (days_out / 14.0) * 0.50)

    # #39: Bayesian Kelly — integrate over uniform posterior on [ci_low, ci_high]
    # Then apply the same quality/anomaly/spread/time modifiers as before.
    bk = bayesian_kelly(ci_low, ci_high, entry_price, fee_rate=KALSHI_FEE_RATE)
    condition_type_scale = _CONDITION_CONFIDENCE.get(condition["type"], 1.0)
    ci_adjusted_kelly = round(
        bk
        * quality_scale
        * anomaly_scale
        * spread_scale
        * time_kelly_scale
        * _confidence_boost
        * condition_type_scale,  # #39: scale down Kelly for harder-to-forecast conditions
        6,
    )
    ci_adjusted_kelly = min(ci_adjusted_kelly, 0.25)

    # Consensus bonus: all sources agree → size up 25%
    if consensus:
        ci_adjusted_kelly = round(ci_adjusted_kelly * 1.25, 6)
    ci_adjusted_kelly = min(ci_adjusted_kelly, 0.25)

    # Near-threshold penalty: forecast is within ±3°F of threshold → high flip risk
    if near_threshold:
        ci_adjusted_kelly = round(ci_adjusted_kelly * 0.75, 6)

    _result = {
        # Core
        "forecast_prob": blended_prob,
        "market_prob": market_prob,
        "edge": edge,
        "signal": signal,
        "net_edge": net_edge,
        "adjusted_edge": round(adjusted_edge, 6),
        "edge_confidence_factor": _edge_conf,
        "net_signal": net_signal,
        "recommended_side": rec_side,
        "condition": condition,
        "forecast_temp": forecast_temp,
        # Sources
        "ensemble_prob": ens_prob,
        "nws_prob": _nws_prob,
        "clim_prob": clim_prob_raw,
        "clim_adj_prob": clim_prob,
        "obs_prob": obs_override,
        "live_obs": live_obs,
        "index_adj": index_adj,
        "bias_correction": bias,
        "mos_max_temp": mos_data["max_temp_f"] if mos_data else None,
        "metar_locked": metar_locked,
        "metar_reason": metar_lockout.get("reason", "") if metar_locked else "",
        "blend_sources": blend_sources,
        "method": method,
        # Ensemble details
        "ensemble_stats": ens_stats,
        "n_members": len(temps),
        # Confidence + sizing
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": ci_high - ci_low,
        "kelly": kelly,
        "fee_adjusted_kelly": fee_adjusted_kelly,
        "ci_adjusted_kelly": ci_adjusted_kelly,
        "time_risk": time_risk_label,
        # Data quality
        "data_quality": data_quality,
        "forecast_anomalous": anomalous,
        "spread_cost": round(spread_cost, 4),
        "spread_scale": round(spread_scale, 4),
        "illiquid": illiquid,  # #62: True if spread > 5%
        "entry_side_edge": round(entry_side_edge, 4),  # #61: edge vs actual ask/bid
        "time_kelly_scale": round(time_kelly_scale, 4),
        # Consensus signal
        "consensus": consensus,
        "model_consensus": model_consensus,
        "near_threshold": near_threshold,
        "days_out": days_out,
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
        # Per-model forecast means for ensemble scoring
        "icon_forecast_mean": icon_forecast_mean,
        "gfs_forecast_mean": gfs_forecast_mean,
        # Phase C: extended ensemble spread + Gaussian probability
        "ensemble_spread": ensemble_spread_prob,
        "ensemble_spread_f": ensemble_spread_f,
        "n_ensemble_members": sum(1 for v in model_temps.values() if v is not None),
        "p_win_gaussian": p_win_gaussian,
        "forecast_sigma": sigma_gauss,
        # Regime detection
        "regime": _regime_info.get("regime", "normal"),
        "regime_description": _regime_info.get("description", ""),
        # Feels-like temperature (informational)
        "feels_like": round(
            _feels_like(ens_stats.get("mean", 65.0)) if ens_stats else 65.0,
            1,
        ),
        # Edge calculation version — increment when kelly/edge logic changes
        "edge_calc_version": EDGE_CALC_VERSION,
    }
    save_forecast_snapshot(enriched.get("ticker", "unknown"), forecast)
    return _result


def detect_hedge_opportunity(analysis: dict, open_trades: list[dict]) -> bool:
    """
    Return True if the new trade would partially hedge an existing open position
    (i.e., the opposite side of the same city+date is already open).
    A hedge reduces net directional risk, so it can be sized slightly larger.
    """
    city = analysis.get("city") or analysis.get("_city")
    if not city:
        return False
    rec_side = analysis.get("recommended_side", "yes")
    opposite = "no" if rec_side == "yes" else "yes"
    return any(
        t.get("city") == city and t.get("side") == opposite
        for t in open_trades
        if not t.get("settled")
    )


def analyze_markets_parallel(
    markets: list[dict],
    max_workers: int = 4,
) -> list[dict | None]:
    """
    Run analyze_trade on each market concurrently (#127).
    Returns list of result dicts (one per market, None on per-market error).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[dict | None] = [None] * len(markets)

    def _worker(idx: int, market: dict) -> tuple[int, dict | None]:
        enriched = enrich_with_forecast(market)
        return idx, analyze_trade(enriched)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, i, m): i for i, m in enumerate(markets)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                _, analysis = fut.result()
                results[idx] = analysis
            except Exception as exc:
                _log.warning(
                    "analyze_markets_parallel: market index %d failed: %s", idx, exc
                )
                results[idx] = None

    return results
