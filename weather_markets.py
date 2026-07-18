"""
Fetch and analyze Kalshi weather prediction markets.
Compares market-implied probabilities with Open-Meteo forecast data.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import random
import re
import statistics
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import climate_indices as _ci
import metar as _metar
import safe_io as _safe_io
from calibration import load_city_weights as _load_city_weights
from calibration import load_condition_weights as _load_condition_weights
from calibration import load_seasonal_weights as _load_seasonal_weights
from circuit_breaker import CircuitBreaker
from climate_indices import get_enso_index, temperature_adjustment
from climatology import climatological_prob
from forecast_cache import ForecastCache
from kalshi_client import KalshiClient, _request_with_retry
from nws import fetch_nbm_forecast, get_live_observation, nws_prob, obs_prob
from paths import SERIES_DRIFT_PATH
from schema_validator import is_all_null, validate_forecast
from utils import (
    BETWEEN_FLOOR_MODEL_MAX,
    KALSHI_FEE_RATE,
    KALSHI_MAKER_FEE_RATE,
    KELLY_CAP,
    KELLY_CAP_CONSENSUS_MULT,
    MAX_DAYS_OUT,
    normal_cdf,
)
from utils import prob_threshold as _prob_threshold

_log = logging.getLogger(__name__)

# Thread-safe gate counter — reset by cron between scans to track why analyze_trade returns None.
_gate_counts: dict[str, int] = {}
_gate_counts_lock = threading.Lock()


def _count_gate(name: str) -> None:
    with _gate_counts_lock:
        _gate_counts[name] = _gate_counts.get(name, 0) + 1


def reset_gate_counts() -> None:
    with _gate_counts_lock:
        _gate_counts.clear()


def get_gate_counts() -> dict[str, int]:
    with _gate_counts_lock:
        return dict(_gate_counts)


# Primary circuit breaker: 3-model daily forecast (FORECAST_BASE).
# burst_window=5s: parallel model fetches that all fail within the same request
# batch count as one failure event, not three.  recovery_timeout=30 min is
# proportional to Open-Meteo's typical MTTR (minutes, not hours).
_forecast_cb = CircuitBreaker(
    name="open_meteo_forecast",
    failure_threshold=10,  # raised from 6 — need more real failures before tripping
    recovery_timeout=300,  # lowered from 1800s — retry after 5 min not 30 min
    burst_window=10.0,  # wider burst window absorbs parallel fetches
)
# Supplementary circuit breaker: ensemble spread and ECMWF high-res (ENSEMBLE_BASE).
# Failures here degrade quality but don't block primary signals.
_ensemble_cb = CircuitBreaker(
    name="open_meteo_ensemble",
    failure_threshold=3,
    recovery_timeout=300,  # 300s: outlasts inter-run gap so circuit stays open across
    burst_window=2.0,  # runs when endpoint is consistently down (same as nbm_om_cb)
)

# Separate circuit breaker for the NBM (Open-Meteo model="nbm") fetch.
# NBM and ensemble hit the same API but are independent signals — one failing
# should NOT gate the other.
# burst_window=2s: absorbs the few truly-simultaneous parallel hits during
# analysis without being so wide that a flaky endpoint hangs for minutes.
_nbm_om_cb = CircuitBreaker(
    name="nbm_openmeteo",
    failure_threshold=3,
    recovery_timeout=300,  # 300s: outlasts the gap between cron runs so circuit stays
    burst_window=2.0,  # open across runs — prevents re-burning 30 s of timeouts
)  # each run when the endpoint is consistently down

# Separate circuit breaker for the ECMWF deterministic fetch (FORECAST_BASE,
# models="ecmwf_ifs025") — same rationale as _nbm_om_cb: this hits a
# different host/endpoint than _ensemble_cb's ENSEMBLE_BASE traffic, so a
# success here must not force-close (record_success() resets failure_count
# and _opened_at) an _ensemble_cb that's genuinely tracking a down
# ensemble-api.open-meteo.com, and a run of ECMWF-only failures must not trip
# the breaker that gates unrelated ICON/GFS/AIFS ensemble fetches.
_ecmwf_om_cb = CircuitBreaker(
    name="ecmwf_openmeteo",
    failure_threshold=3,
    recovery_timeout=300,
    burst_window=2.0,
)

# ── Trading filters ───────────────────────────────────────────────────────────
# Only analyse markets expiring within this many days. Days 3-4 carry higher
# uncertainty but the horizon discount in edge_confidence() and Kelly sizing
# handle that automatically. Override via MAX_DAYS_OUT env var.

# Minimum combined volume + open_interest required to trade a market.
# Below this the market is effectively illiquid — fills are unreliable.
MIN_LIQUIDITY: int = 50

# Volume-only gate: skip signals where volume alone is below this threshold.
# At very low volume the market price is set by a handful of trades and is
# not reliable as a probability estimate. Override via MIN_SIGNAL_VOLUME env var.
MIN_SIGNAL_VOLUME: int = int(os.getenv("MIN_SIGNAL_VOLUME", "50"))

# Model-spread gate: suppress signals when the multi-model high/low spread is
# wider than this many °F. Wide spread = models disagree = high flip risk.
# Override via MAX_MODEL_SPREAD_F env var.
MAX_MODEL_SPREAD_F: float = float(os.getenv("MAX_MODEL_SPREAD_F", "8.0"))

# MOS blend weight: fraction of the final blended probability assigned to MOS
# when a MOS forecast is available.  The remaining (1 - weight) fraction stays
# with the existing ensemble+NWS+climatology blend, preserving its internal
# proportions.  Must be in [0.0, 0.5).  Override via MOS_BLEND_WEIGHT env var.
_MOS_BLEND_WEIGHT: float = float(os.getenv("MOS_BLEND_WEIGHT", "0.20"))

# Extreme-price gate: skip markets where yes_ask is below this floor or above
# 1 - floor.  When the market prices an outcome at < 5¢ or > 95¢ it has near-
# certainty that our blended model cannot beat.  Betting against extreme consensus
# inflates net_edge via small denominator and almost always loses.
# Override via MIN_MARKET_PRICE env var (e.g. MIN_MARKET_PRICE=0.03).
MIN_MARKET_PRICE: float = float(os.getenv("MIN_MARKET_PRICE", "0.05"))

# Maximum ensemble sigma (°F) for above/below threshold markets.
# Raw GFS ensemble spread (5–10°F) overstates 1-day uncertainty; NWS calibrated RMSE is
# 1.5–2°F.  These caps apply only to above/below direction markets.
# Override via SIGMA_1DAY_CAP / SIGMA_2DAY_CAP env vars.
_SIGMA_1DAY_CAP: float = float(os.getenv("SIGMA_1DAY_CAP", "3.0"))
_SIGMA_2DAY_CAP: float = float(os.getenv("SIGMA_2DAY_CAP", "4.0"))

# Tighter sigma caps for "between" bracket markets.  A 2°F-wide bin with σ=3°F
# can only ever reach 26.6% probability — well below the 40–50% the market correctly
# prices these at.  NWS RMSE of 1.5–2°F gives a max between-prob of ~40–53%,
# which matches observed settlement rates.  Keeping above/below caps separate avoids
# inadvertently tightening direction-market uncertainty.
# Override via BETWEEN_SIGMA_1DAY_CAP / BETWEEN_SIGMA_2DAY_CAP env vars.
_BETWEEN_SIGMA_1DAY_CAP: float = float(os.getenv("BETWEEN_SIGMA_1DAY_CAP", "1.8"))
_BETWEEN_SIGMA_2DAY_CAP: float = float(os.getenv("BETWEEN_SIGMA_2DAY_CAP", "2.5"))

# Dynamic temperature bias cache: (city, var) → (signed_error_f, sample_count, monotonic_ts)
# Populated lazily from tracker.get_dynamic_station_bias(). TTL matches model cache.
_DYNAMIC_BIAS_CACHE: dict[tuple, tuple[float, int, float]] = {}
_DYNAMIC_BIAS_CACHE_TTL: float = 4 * 60 * 60  # 4 hours

# Market price credibility anchor weights by condition type.
# Between markets have a ~23% systematic cold bias vs market ~46%; anchor more heavily.
# Above/below: 10/10 directional accuracy — anchor lightly for calibration only.
# Set to 0.0 to disable. Override via env vars.
_MARKET_ANCHOR_BETWEEN: float = float(os.getenv("MARKET_ANCHOR_BETWEEN", "0.25"))
_MARKET_ANCHOR_ABOVE: float = float(os.getenv("MARKET_ANCHOR_ABOVE", "0.10"))
_MARKET_ANCHOR_BELOW: float = float(os.getenv("MARKET_ANCHOR_BELOW", "0.10"))

# Minimum settled-trade count before any ML bias correction tier activates.
# Guards against applying models trained on backtesting data to live paper trades.
# Override via MIN_BIAS_CORRECTION_TRADES env var.
_MIN_BIAS_CORRECTION_TRADES: int = int(os.getenv("MIN_BIAS_CORRECTION_TRADES", "50"))

# Single source of truth for edge calculation logic version.
# Increment whenever kelly_fraction, edge_confidence, or time_decay_edge logic
# changes, so outputs can be traced.
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
        "Chicago": (41.7868, -87.7522, "America/Chicago"),
        "LA": (34.0190, -118.2910, "America/Los_Angeles"),
        "Miami": (25.8175, -80.3164, "America/New_York"),
        "Boston": (42.3606, -71.0106, "America/New_York"),
        "Dallas": (32.8998, -97.0403, "America/Chicago"),
        "Phoenix": (33.4373, -112.0078, "America/Phoenix"),
        "Seattle": (47.4502, -122.3088, "America/Los_Angeles"),
        "Denver": (39.8561, -104.6737, "America/Denver"),
        "Atlanta": (33.6407, -84.4277, "America/New_York"),
        # Additional cities detected in Kalshi tickers but previously missing coords
        "Austin": (30.1945, -97.6699, "America/Chicago"),
        "Washington": (38.9531, -77.4565, "America/New_York"),
        "Philadelphia": (39.8719, -75.2411, "America/New_York"),
        "OklahomaCity": (35.3931, -97.6008, "America/Chicago"),
        "SanFrancisco": (37.6190, -122.3750, "America/Los_Angeles"),
        "Minneapolis": (44.8848, -93.2223, "America/Chicago"),
        "Houston": (29.6454, -95.2789, "America/Chicago"),
        "SanAntonio": (29.5337, -98.4698, "America/Chicago"),
        # KLAS / KMSY settlement stations — added for KXHIGHTLV/KXLOWTLV and
        # KXHIGHTNOLA/KXLOWTNOLA, previously untracked entirely.
        "LasVegas": (36.0840, -115.1537, "America/Los_Angeles"),
        "NewOrleans": (29.9934, -90.2580, "America/Chicago"),
    }


CITY_COORDS = _load_city_coords()

# Per-city static bias corrections (°F) — subtract from model forecast before
# computing probability. Positive = model runs warm; negative = model runs cold.
# Sources: Weather Edge MCP field data, NWS station comparison reports.
# B4: Split station bias by HIGH (max) vs LOW (min) markets.
# Warm biases in GFS/ICON are strongest for daytime peaks; overnight lows differ.
_STATION_BIAS_HIGH: dict[str, float] = {
    # East Coast
    "NYC": 1.0,  # KNYC: NWS gridpoint overshoots Central Park by ~1°F (warm)
    "Boston": 0.5,  # KBOS: Minor warm bias similar to NYC
    "Philadelphia": 1.0,  # KPHL: Similar to NYC urban heat island
    "Washington": 1.0,  # KDCA: Urban heat + GFS warm bias
    # South/Gulf
    "Miami": 3.0,  # KMIA: GFS southern warm bias, confirmed via field research
    "Atlanta": 1.0,  # KATL: Southeast warm bias
    "Houston": 2.0,  # KHOU: Humid subtropical, GFS runs hot
    "NewOrleans": 2.0,  # KMSY: Gulf humid subtropical, same profile as Houston
    "Dallas": 0.5,  # KDFW: GFS southern warm bias (minor)
    "Austin": 1.5,  # KAUS: Similar to Dallas but higher elevation variation
    "SanAntonio": 1.5,  # KSAT: Southern Texas warm bias
    "OklahomaCity": 1.0,  # KOKC: Southern Plains warm bias
    # Southwest
    "Phoenix": 2.5,  # KPHX: Desert environment; GFS routinely overshoots high temps
    "LasVegas": 2.5,  # KLAS: Desert climate, same GFS/ICON warm-bias artifact as Phoenix
    # Mountain
    "Denver": 2.0,  # KDEN: Mountain terrain uncertainty, conservative correction
    # Midwest
    "Chicago": 0.5,  # KMDW: Minor warm bias
    "Minneapolis": 1.5,  # KMSP: Continental interior; GFS warm bias stronger than coasts
    # West Coast
    "LA": 0.0,  # KLAX: Marine influence largely corrects GFS bias
    "SanFrancisco": 0.0,  # KSFO: Strong marine layer, GFS frequently cold — no correction
    "Seattle": -0.5,  # KSEA: GFS tends cold for Pacific Northwest marine climate
}
_STATION_BIAS_LOW: dict[str, float] = {
    # East Coast
    "NYC": 0.5,  # Overnight lows: smaller warm bias than daytime highs
    "Boston": 0.0,  # KBOS lows: no consistent bias
    "Philadelphia": 0.5,  # Similar to NYC nights
    "Washington": 0.5,  # KDCA nights: urban heat retained
    # South/Gulf
    "Miami": 1.5,  # KMIA overnight lows still warm-biased but less than highs
    "Atlanta": 0.5,  # KATL nights
    "Houston": 1.0,  # KHOU: Humid subtropical, nights stay warm
    "NewOrleans": 1.0,  # KMSY nights: mirrors Houston
    "Dallas": 0.0,  # KDFW lows: no consistent bias observed
    "Austin": 0.5,  # KAUS nights
    "SanAntonio": 0.5,  # KSAT nights
    "OklahomaCity": 0.0,  # KOKC lows: no consistent bias
    # Southwest
    "Phoenix": 0.5,  # KPHX nights: desert cools rapidly, smaller bias than highs
    "LasVegas": 0.5,  # KLAS nights: mirrors Phoenix
    # Mountain
    "Denver": 1.0,  # Denver nights: model still warm but less extreme
    # Midwest
    "Chicago": 0.0,  # KMDW lows: no consistent bias observed
    "Minneapolis": 0.5,  # KMSP nights
    # West Coast
    "LA": 0.0,  # KLAX: No known systematic bias
    "SanFrancisco": 0.0,  # KSFO: No correction
    "Seattle": 0.0,  # KSEA nights: no consistent bias
}
# Legacy alias — used by any callers that don't pass var
_STATION_BIAS = _STATION_BIAS_HIGH


def _get_combined_station_bias(city: str, var: str = "max") -> float:
    """Return the best available temperature bias correction for a city.

    Blends the static hand-coded bias table with a dynamic correction derived from
    real METAR observations logged at settlement.  As sample count grows, the dynamic
    correction takes over — at 10 samples it contributes 20%, at 50+ samples 100%.

    This means the static table is the reliable fallback for new cities while the
    dynamic correction gradually dominates once the data is trustworthy.
    """
    static_bias = (_STATION_BIAS_LOW if var == "min" else _STATION_BIAS_HIGH).get(
        city, 0.0
    )

    cached = _DYNAMIC_BIAS_CACHE.get((city, var))
    if cached is not None and time.monotonic() - cached[2] < _DYNAMIC_BIAS_CACHE_TTL:
        dyn_bias, count = cached[0], cached[1]
    else:
        try:
            from tracker import get_dynamic_station_bias as _gdbs

            dyn_bias, count = _gdbs(city, var, min_samples=10)
        except Exception:
            dyn_bias, count = 0.0, 0
        _DYNAMIC_BIAS_CACHE[(city, var)] = (dyn_bias, count, time.monotonic())

    if count < 10:
        return static_bias

    # Blend: 0% dynamic at 10 samples → 100% dynamic at 50+ samples.
    # The transition is linear so the correction stabilises quickly once we have
    # enough observations without jumping abruptly from static to dynamic.
    dynamic_weight = min(1.0, (count - 10) / 40.0)
    return static_bias * (1.0 - dynamic_weight) + dyn_bias * dynamic_weight


# City → timezone (keys match CITY_COORDS / metar.MARKET_STATION_MAP).
# Derived from CITY_COORDS (each tuple's 3rd element) so it can never drift,
# including once CITY_COORDS starts loading dynamically from data/cities.json.
_CITY_TZ: dict[str, str] = {city: coords[2] for city, coords in CITY_COORDS.items()}

# City → primary ICAO observation station (single source of truth: metar.MARKET_STATION_MAP)
_CITY_METAR_STATION: dict[str, str] = _metar.MARKET_STATION_MAP


def _metar_station_for_city(city: str) -> str | None:
    """Return the METAR/ASOS station for a city (matches Kalshi settlement)."""
    return _CITY_METAR_STATION.get(city)


# Cities where airport dew point depression suppresses afternoon high temperatures.
# On humid days, sea breeze and evaporative cooling cause METAR stations to read
# 3–7°F cooler than dry-air model forecasts.
_DEW_POINT_SENSITIVE_CITIES = {"Miami", "Houston", "SanFrancisco", "Seattle"}


def _dew_point_temp_correction(
    city: str, dew_point_f: float, forecast_temp_f: float
) -> float:
    """Return a bias correction (°F, negative = cooler) based on dew point depression.

    On humid days (dew point depression < 20°F), sea breeze and evaporative cooling
    suppress afternoon high temperatures at airport stations relative to model forecasts.
    """
    if city not in _DEW_POINT_SENSITIVE_CITIES:
        return 0.0

    depression = forecast_temp_f - dew_point_f
    if depression >= 20.0:
        return 0.0

    max_correction = -3.0
    correction = max_correction * (1.0 - depression / 20.0)
    # Clamp handles supersaturation (dew > forecast_temp, depression < 0) on marine-layer days
    return round(max(-5.0, correction), 2)


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

# Ensemble cache: key -> list[float] (TTL handled by ForecastCache)
# 8-hour TTL: NWP forecasts don't change dramatically between model cycles and
# the longer window prevents rate-limit hammering on consecutive manual cron runs.
_ensemble_cache: ForecastCache[list[float]] = ForecastCache(ttl_secs=8 * 3600)
_ENSEMBLE_CACHE_TTL = 8 * 60 * 60  # seconds — mirrors in-memory TTL
_ENSEMBLE_DISK_CACHE_PATH = Path("data/ensemble_cache.json")
_ENSEMBLE_DISK_LOCK = threading.Lock()

# Path for one-time auto-activation notifications surfaced on the dashboard.
_FEATURE_ACTIVATIONS_PATH = Path(__file__).parent / "data" / "feature_activations.json"

# Two separate rate limiters: forecast endpoint is more permissive than ensemble.
# ensemble-api.open-meteo.com is the stricter one (0.1s caused 429s+60s retries);
# api.open-meteo.com (forecast) handled 0.5s without throttling.
# Splitting them avoids per-city NBM/ECMWF forecast calls being serialized at
# the ensemble rate, which was adding ~80s to the prewarm (54 calls × 1.5s).
_OM_FORECAST_RATE_LOCK = threading.Lock()
_OM_FORECAST_MIN_INTERVAL: float = 0.5  # api.open-meteo.com — 2 req/s
_OM_FORECAST_STATE: list[float] = [0.0]  # [last_ts]; list so closure can mutate

_OM_ENSEMBLE_RATE_LOCK = threading.Lock()
_OM_ENSEMBLE_MIN_INTERVAL: float = 1.5  # ensemble-api.open-meteo.com — strict
_OM_ENSEMBLE_STATE: list[float] = [0.0]


def _om_rate_limit(url: str) -> None:
    """Block until the per-endpoint minimum inter-request interval has elapsed.

    IMPORTANT: the lock is released BEFORE sleeping so that concurrent threads
    can each reserve their own time slot atomically without blocking each other
    for the full sleep duration.  Holding the lock during sleep serialised all
    12 analysis workers (each waiting 1.5 s while the lock was held), causing
    the cron to hang for many minutes.
    """
    if "ensemble-api" in url:
        lock, interval, state = (
            _OM_ENSEMBLE_RATE_LOCK,
            _OM_ENSEMBLE_MIN_INTERVAL,
            _OM_ENSEMBLE_STATE,
        )
    else:
        lock, interval, state = (
            _OM_FORECAST_RATE_LOCK,
            _OM_FORECAST_MIN_INTERVAL,
            _OM_FORECAST_STATE,
        )
    with lock:
        now = time.monotonic()
        wait = max(0.0, interval - (now - state[0]))
        # Reserve the next slot atomically: advance state[0] so the next caller
        # receives a slot that is interval seconds after ours, not after now.
        state[0] = now + wait
    if wait > 0:
        time.sleep(
            wait
        )  # sleep OUTSIDE the lock — other threads can reserve in parallel


def _build_om_session() -> requests.Session:
    """Build a dedicated session for Open-Meteo that does NOT auto-retry on 429.

    429 handling is done explicitly in _om_request so we control the backoff and
    can give up after a fixed number of attempts.  Auto-retrying 429 via the
    HTTPAdapter would cause Retry-After sleeps to stack with _om_request's own
    sleep, locking the cron for many minutes per city.

    Retry total reduced to 1: with timeout=12 per attempt, total=3 meant
    4 × 12 s + backoff ≈ 51 s per call.  Six sequential prewarm calls could
    therefore block for 5+ minutes on a slow/down endpoint before the circuit
    breaker trips.  total=1 caps a single call at 2 × 12 + 0.5 s ≈ 25 s.
    The circuit breaker (failure_threshold=10) handles persistent outages.
    """
    session = requests.Session()
    retry = Retry(
        total=1,
        backoff_factor=0.5,
        status_forcelist={500, 502, 503, 504},  # 5xx only — NOT 429
        allowed_methods={"GET"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_OM_SESSION = _build_om_session()


def _om_request(method: str, url: str, **kwargs) -> requests.Response:
    """Rate-limited wrapper for all Open-Meteo API calls.

    On 429: returns immediately without sleeping.  The caller's except block
    records a circuit-breaker failure; after the threshold is reached the CB
    opens and all further Open-Meteo calls are skipped instantly, allowing the
    Pirate Weather / NWS fallback to take over within seconds rather than
    waiting for Retry-After sleep cycles across every model and every city.
    """
    kwargs.setdefault("timeout", 8)
    _om_rate_limit(url)
    resp = _OM_SESSION.request(method, url, **kwargs)
    if resp.status_code == 429:
        _log.debug(
            "Open-Meteo rate limited (429) — CB failure recorded, fallback will engage"
        )
    return resp


# Forecast cache: (city, date_iso) -> dict (TTL handled by ForecastCache)
# 8-hour TTL matches ensemble cache — prevents cache misses on consecutive runs.
_forecast_cache: ForecastCache[dict] = ForecastCache(ttl_secs=8 * 3600)
# TTL constant kept for disk-cache loading/pruning logic below
_FORECAST_CACHE_TTL = 8 * 60 * 60

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
            # G6: clamp age to ≥0 to guard against NTP corrections or clock resets
            age = max(0.0, now - entry.get("ts_posix", 0))
            if age < _FORECAST_CACHE_TTL:
                # Reconstruct in-memory key as tuple; stored ts converted to monotonic approx
                city, date_iso = key_str.split("|", 1)
                mem_key = (city, date_iso)
                # Approximate monotonic timestamp from wall-clock age
                _forecast_cache.set_at(mem_key, entry["data"], time.monotonic() - age)
                loaded += 1
        if loaded:
            _log.debug("forecast disk cache: loaded %d entries", loaded)
    except Exception as exc:
        _log.debug("forecast disk cache load failed (non-fatal): %s", exc)


# Pending forecast entries accumulated during a run — flushed in one batch
# write at process exit via flush_forecast_disk_cache(). Mirrors the ensemble
# disk cache's pattern: per-entry daemon threads were unreliable (the analysis
# scan is the last thing that runs, so daemon threads were killed before they
# could write anything), losing entries from the last cities analyzed.
_forecast_disk_pending: dict[str, dict] = {}


def _save_forecast_disk_entry(cache_key: tuple, data: dict) -> None:
    """Queue a forecast cache entry for the next batch flush."""
    key_str = f"{cache_key[0]}|{cache_key[1]}"
    with _FORECAST_DISK_LOCK:
        _forecast_disk_pending[key_str] = {"data": data, "ts_posix": time.time()}


def flush_forecast_disk_cache() -> int:
    """Write all pending forecast entries to disk in one atomic operation.

    Call this at the end of a cron run (before process exit) so the entries
    survive to warm the next run. Returns the number of entries written.
    """
    import json as _json

    with _FORECAST_DISK_LOCK:
        if not _forecast_disk_pending:
            return 0
        pending = dict(_forecast_disk_pending)
        _forecast_disk_pending.clear()

    try:
        now = time.time()
        if _FORECAST_DISK_CACHE_PATH.exists():
            raw: dict = _json.loads(
                _FORECAST_DISK_CACHE_PATH.read_text(encoding="utf-8")
            )
        else:
            raw = {}
        raw.update(pending)
        # Prune expired entries so the file doesn't grow indefinitely
        raw = {
            k: v
            for k, v in raw.items()
            if now - v.get("ts_posix", 0) < _FORECAST_CACHE_TTL
        }
        import safe_io as _safe_io

        _safe_io.atomic_write_json(raw, _FORECAST_DISK_CACHE_PATH)
        _log.debug("forecast disk cache: flushed %d entries to disk", len(pending))
        return len(pending)
    except Exception as exc:
        _log.debug("forecast disk cache flush failed (non-fatal): %s", exc)
        return 0


# cron.py's _cmd_cron_body explicitly calls flush_forecast_disk_cache() (and its
# ensemble-cache sibling) near the end of a `cron` run for early visibility/
# logging — but that's the ONLY call site in the repo. Every other command that
# populates these caches (cmd_forecast, cmd_analyze, cmd_today, cmd_brief, the
# web dashboard, etc. — anything reaching get_weather_forecast/analyze_trade)
# never called it, so under the old per-entry-daemon-thread design those
# entries at least had a chance to write during the command's runtime; under
# the accumulate-then-flush design they would otherwise NEVER reach disk for
# any command except a fully-completed `cron` run. Register both flushes as
# atexit hooks so a normal process exit persists pending entries regardless of
# which command ran (cron.py's explicit calls become a harmless duplicate
# flush of an already-empty pending dict). This does not cover a hard kill
# (SIGKILL, the cron watchdog's forced termination, or os._exit) — same
# unavoidable limitation the daemon-thread design had at process death.
atexit.register(flush_forecast_disk_cache)


# Populate in-memory cache from disk on import
_load_forecast_disk_cache()


# ── Ensemble disk cache ───────────────────────────────────────────────────────
# Same pattern as forecast disk cache.  Keys are JSON-serialised tuples so
# they survive None values (hour=None) and variable-length forms cleanly.


def _load_ensemble_disk_cache() -> None:
    """Load non-expired ensemble entries from disk into the in-memory cache."""
    if not _ENSEMBLE_DISK_CACHE_PATH.exists():
        return
    try:
        import json as _json

        with _ENSEMBLE_DISK_LOCK:
            raw = _json.loads(_ENSEMBLE_DISK_CACHE_PATH.read_text(encoding="utf-8"))
        now = time.time()
        loaded = 0
        for key_str, entry in raw.items():
            age = max(0.0, now - entry.get("ts_posix", 0))
            # Entries are written with a cycle-aligned TTL (_ttl_until_next_cycle(),
            # often well under the flat _ENSEMBLE_CACHE_TTL used here only as a
            # backward-compat default for entries written before ttl_secs existed).
            # Using the flat TTL for both the load gate AND the restored cache
            # entry would resurrect ensemble data from a superseded model cycle
            # as if it were still fresh — restore the real per-entry TTL instead.
            ttl = entry.get("ttl_secs", _ENSEMBLE_CACHE_TTL)
            if age < ttl:
                mem_key = tuple(_json.loads(key_str))
                _ensemble_cache.set_at_with_ttl(
                    mem_key, entry["data"], time.monotonic() - age, ttl
                )
                loaded += 1
        if loaded:
            _log.debug("ensemble disk cache: loaded %d entries", loaded)
    except Exception as exc:
        _log.debug("ensemble disk cache load failed (non-fatal): %s", exc)


# Pending ensemble entries accumulated during a run — flushed in one batch
# write at process exit via flush_ensemble_disk_cache().  Background daemon
# threads were unreliable: the analysis scan is the last thing that runs, so
# daemon threads were killed before they could write anything.
_ensemble_disk_pending: dict[str, dict] = {}


def _save_ensemble_disk_entry(
    cache_key: tuple, data: list[float], ttl_secs: float = _ENSEMBLE_CACHE_TTL
) -> None:
    """Queue an ensemble cache entry for the next batch flush.

    ttl_secs should match whatever TTL was passed to the corresponding
    _ensemble_cache.set_with_ttl() call, so a reload from disk (see
    _load_ensemble_disk_cache) respects the same cycle-aligned expiry instead
    of falling back to the flat _ENSEMBLE_CACHE_TTL default.
    """
    import json as _json

    key_str = _json.dumps(list(cache_key))
    with _ENSEMBLE_DISK_LOCK:
        _ensemble_disk_pending[key_str] = {
            "data": data,
            "ts_posix": time.time(),
            "ttl_secs": ttl_secs,
        }


def flush_ensemble_disk_cache() -> int:
    """Write all pending ensemble entries to disk in one atomic operation.

    Call this at the end of a cron run (before process exit) so the entries
    survive to warm the next run.  Returns the number of entries written.
    """
    import json as _json

    with _ENSEMBLE_DISK_LOCK:
        if not _ensemble_disk_pending:
            return 0
        pending = dict(_ensemble_disk_pending)
        _ensemble_disk_pending.clear()

    try:
        now = time.time()
        if _ENSEMBLE_DISK_CACHE_PATH.exists():
            raw: dict = _json.loads(
                _ENSEMBLE_DISK_CACHE_PATH.read_text(encoding="utf-8")
            )
        else:
            raw = {}
        raw.update(pending)
        # Prune expired entries (per-entry ttl_secs when present) so the file
        # doesn't grow indefinitely.
        raw = {
            k: v
            for k, v in raw.items()
            if now - v.get("ts_posix", 0) < v.get("ttl_secs", _ENSEMBLE_CACHE_TTL)
        }
        import safe_io as _safe_io

        _safe_io.atomic_write_json(raw, _ENSEMBLE_DISK_CACHE_PATH)
        _log.debug("ensemble disk cache: flushed %d entries to disk", len(pending))
        return len(pending)
    except Exception as exc:
        _log.debug("ensemble disk cache flush failed (non-fatal): %s", exc)
        return 0


# Same rationale as flush_forecast_disk_cache's atexit registration above —
# cron.py's explicit calls are the only ones in the repo, so every other
# command reaching get_ensemble_temps/analyze_trade never flushed this either.
atexit.register(flush_ensemble_disk_cache)


# Populate ensemble in-memory cache from disk on import
_load_ensemble_disk_cache()


# Maximum age of forecast data before analyze_trade rejects it.
# Set higher than _FORECAST_CACHE_TTL so cache expiry happens first — otherwise
# a cache HIT (up to _FORECAST_CACHE_TTL old) could still fail this staleness
# gate, and since a cache hit short-circuits before any refetch, the market
# would silently produce no signal until the cache entry finally expires.
# _FORECAST_CACHE_TTL is 8h; this must stay above that. Override via
# FORECAST_MAX_AGE_SECS env var.
FORECAST_MAX_AGE_SECS = int(
    os.getenv("FORECAST_MAX_AGE_SECS", str(9 * 3600))
)  # 9 hours — above the 8h cache TTL so a cache hit is never rejected as stale

# #66: Market listing cache to avoid hammering the API on every analyze call
_MARKETS_CACHE: tuple[list, float] | None = None
_MARKETS_CACHE_TTL = 60  # 60 seconds

# ── Calibration data (loaded once at import; empty dicts = use hardcoded weights) ──
_CITY_WEIGHTS: dict[str, dict[str, float]] = _load_city_weights()
_SEASONAL_WEIGHTS: dict[str, dict[str, float]] = _load_seasonal_weights()
_CONDITION_WEIGHTS: dict[str, dict[str, float]] = _load_condition_weights()

# ── Per-city Platt scaling models (loaded once; None = not yet loaded) ────────
_PLATT_MODELS: dict[str, tuple[float, float]] | None = None

# Minimum settled below predictions required before the two data-sparse below-market
# gates can be manually activated (BELOW_GATE_ENABLED=1 in .env).
_BELOW_GATE_MIN_SAMPLES: int = 30


def _below_gates_active() -> bool:
    """Return True only when BELOW_GATE_ENABLED=1 AND >= 30 settled below predictions.

    Controls two aggressive fixes (extreme-ens block, NWS-trim skip) that are based
    on thin evidence (N=3 and N=7).  Gated so they can be activated manually once
    enough data accumulates to confirm the patterns are real.
    """
    import os

    if os.getenv("BELOW_GATE_ENABLED", "").strip().lower() not in ("1", "true", "yes"):
        return False
    try:
        from tracker import count_settled_below_predictions

        return count_settled_below_predictions() >= _BELOW_GATE_MIN_SAMPLES
    except Exception:
        return False


def _load_platt_models() -> dict[str, tuple[float, float]]:
    """Load platt_models.json once per process; return empty dict when absent."""
    global _PLATT_MODELS
    if _PLATT_MODELS is None:
        import json

        path = Path(__file__).parent / "data" / "platt_models.json"
        try:
            raw = (
                {k: tuple(v) for k, v in json.loads(path.read_text()).items()}
                if path.exists()
                else {}
            )
            validated: dict[str, tuple[float, float]] = {}
            for city, (a, b) in raw.items():
                if a <= 0:
                    _log.error(
                        "Platt model for %s has A=%s (<=0) — signal would be inverted; skipping",
                        city,
                        a,
                    )
                    continue
                # H-16: re-validate coefficient bounds at load time — training enforces
                # |A|≤5 and |B|≤5 but a corrupted/manually edited file bypasses that.
                if abs(a) > 5 or abs(b) > 5:
                    _log.warning(
                        "Platt model for %s has out-of-bounds coefficients "
                        "(A=%.2f B=%.2f) — skipping to prevent extreme miscalibration",
                        city,
                        a,
                        b,
                    )
                    continue
                validated[city] = (float(a), float(b))
            _PLATT_MODELS = validated
        except Exception:
            _PLATT_MODELS = {}
    return _PLATT_MODELS


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

    Priority order (#122, #28), applied per-model so the result always contains
    exactly the three real fetchable models (callers use these keys to decide which
    Open-Meteo models to request):
      1. Dynamic from tracker MAE (city + season specific)
      2. Per-city learned weights from data/learned_weights.json
      3. Static seasonal weights + ENSO adjustment (original behaviour)
    """
    # 3. Static seasonal + ENSO fallback — computed first as the baseline/floor
    is_winter = month in (10, 11, 12, 1, 2, 3)
    ecmwf_w = 2.5 if is_winter else 1.5

    if is_winter:
        enso_phase = _get_enso_phase()
        if enso_phase == "el_nino":
            ecmwf_w += 0.5  # El Niño winters: ECMWF skill advantage grows
        elif enso_phase == "la_nina":
            ecmwf_w += 0.3  # La Niña winters: moderate ECMWF boost

    baseline = {
        "gfs_seamless": 1.0,
        "ecmwf_ifs025": ecmwf_w,
        "icon_seamless": 1.0,
    }

    if city is None:
        return baseline

    # 2. Per-city learned weights from last backtest (per-model, only known keys)
    lw = load_learned_weights()
    city_data = lw.get(city)
    if city_data is not None and not isinstance(city_data, dict):
        _log.debug(
            "[ModelWeights] %s: learned_weights.json has %s (expected dict) — "
            "skipping, using seasonal defaults",
            city,
            type(city_data).__name__,
        )
        city_data = None
    learned = city_data if isinstance(city_data, dict) else {}

    # 1. Dynamic from tracker MAE (per-model, only known keys)
    # tracker.get_model_weights() returns softmax weights that sum to 1.0, but
    # `learned`/`baseline` are on an "average 1.0 per model" scale (see
    # _weights_from_mae's matching normalisation) — rescale so merging doesn't
    # silently over/under-weight a model purely from a units mismatch.
    dyn_raw = _dynamic_model_weights(city=city, month=month) or {}
    dyn = {m: v * len(dyn_raw) for m, v in dyn_raw.items()} if dyn_raw else {}

    return {
        model: dyn.get(model, learned.get(model, default))
        for model, default in baseline.items()
    }


def get_weather_forecast(city: str, target_date: date) -> dict | None:
    """
    Fetch daily high/low/precip from three forecast models (GFS, ECMWF, ICON)
    and return the averaged values. Results are cached for 90 minutes.
    """
    cache_key = (city, target_date.isoformat())
    data = _forecast_cache.get(cache_key)
    if data is not None:
        return data

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, tz = coords

    # Seasonal model weights — ECMWF more accurate in winter, GFS competitive in summer
    model_weights = _forecast_model_weights(target_date.month, city=city)
    _log.debug(
        "[weights] %s: %s", city, {m: round(v, 3) for m, v in model_weights.items()}
    )
    highs: list[tuple[float, float]] = []  # (value, weight)
    lows: list[tuple[float, float]] = []
    precips: list[tuple[float, float]] = []

    def _fetch_one(model: str, weight: float) -> tuple | None:
        """Fetch one model's forecast; returns (high, low, precip, weight) or None."""
        if _forecast_cb.is_open():
            _log.info(
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
            daily = resp.json().get("daily", {})
            if is_all_null(daily.get("temperature_2m_max")):
                raise ValueError(
                    f"model {model} returned all-null daily data (dead model?)"
                )
            _forecast_cb.record_success()
        except Exception as _exc:
            _forecast_cb.record_failure()
            _log.info("open_meteo forecast fetch failed: %s", _exc)
            return None
        validate_forecast(daily, source="open_meteo")
        dates = daily.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in dates:
            return None
        idx = dates.index(target_str)
        h = (daily.get("temperature_2m_max") or [None])[idx]
        lo = (daily.get("temperature_2m_min") or [None])[idx]
        p = (daily.get("precipitation_sum") or [None])[idx]
        return (h, lo, p, weight)

    # Manual pool management (no `with` block) so we can call shutdown(wait=False)
    # if as_completed times out.  Using `with ThreadPoolExecutor` calls
    # shutdown(wait=True) on __exit__, which blocks forever if a thread is stuck
    # on a hung Windows SSL connection that ignores the socket timeout.
    _pool = ThreadPoolExecutor(max_workers=len(model_weights))  # #124: dynamic
    try:
        futures = {
            _pool.submit(_fetch_one, model, weight): model
            for model, weight in model_weights.items()
        }
        try:
            # 60 s timeout: 3 models × max ~24.5 s each; if a thread slips past
            # its HTTP timeout (Windows SSL edge case) this caps the wait.
            for fut in as_completed(futures, timeout=60):
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
        except TimeoutError:
            _log.debug(
                "get_weather_forecast(%s): model fetch pool timed out — using partial results",
                city,
            )
    finally:
        # wait=False: don't block on threads that are stuck on a dead socket.
        # The watchdog will kill the process if truly hung; threads time out on
        # their own via the HTTP timeout and clean up eventually.
        _pool.shutdown(wait=False)

    if not highs:
        # Open-Meteo unavailable — try NBM (NWS gridpoints) + weatherapi first,
        # then fall back to Pirate Weather as a last resort.
        nbm_data = fetch_nbm_forecast(city, coords, target_date)
        if nbm_data is not None:
            if nbm_data.get("high_f") is not None:
                highs.append((nbm_data["high_f"], 1.0))
            if nbm_data.get("low_f") is not None:
                lows.append((nbm_data["low_f"], 1.0))

        wa_data = fetch_temperature_weatherapi(city, target_date)
        if wa_data is not None:
            if wa_data.get("high_f") is not None:
                highs.append((wa_data["high_f"], 1.0))
            if wa_data.get("low_f") is not None:
                lows.append((wa_data["low_f"], 1.0))

        if highs:
            _log.info(
                "[DataSource] open_meteo_ensemble disabled — using NBM + weatherapi for %s",
                city,
            )

    if not highs:
        # NBM + weatherapi also unavailable — try Pirate Weather (HRRR-based)
        pw_data = fetch_temperature_pirate_weather(city, target_date)
        if pw_data is not None:
            _log.info(
                "get_weather_forecast: using Pirate Weather fallback for %s", city
            )
            pw_high = pw_data["high_f"]
            result = {
                "date": target_date.isoformat(),
                "city": city,
                "high_f": pw_high,
                "low_f": pw_data.get("low_f"),
                "precip_in": pw_data.get("precip_in", 0.0),
                "models_used": 1,
                "high_range": (pw_high, pw_high),
                "_source": "pirate_weather",
                # Enriched Pirate Weather fields
                "precip_prob": pw_data.get("precip_prob"),
                "precip_type": pw_data.get("precip_type"),
                "dew_point_f": pw_data.get("dew_point_f"),
                "humidity": pw_data.get("humidity"),
                "wind_gust": pw_data.get("wind_gust"),
                "_wind_gust_time_unix": pw_data.get("_wind_gust_time_unix"),
                "_temp_max_time_unix": pw_data.get("_temp_max_time_unix"),
                "_hourly_window_high_f": pw_data.get("_hourly_window_high_f"),
                "_active_alerts": pw_data.get("_active_alerts", []),
                "_has_severe_alert": pw_data.get("_has_severe_alert", False),
                "_source_freshness_hours": pw_data.get("_source_freshness_hours", {}),
                "_stale_forecast": pw_data.get("_stale_forecast", False),
                "_precip_intensity_error": pw_data.get("_precip_intensity_error"),
                "_elevation_m": pw_data.get("_elevation_m"),
                "_liquid_accum_in": pw_data.get("_liquid_accum_in"),
                "_snow_accum_in": pw_data.get("_snow_accum_in"),
                "_ice_accum_in": pw_data.get("_ice_accum_in"),
            }
            # L5-A: align TTL to next NWS model cycle, not a flat 4 h window
            _forecast_cache.set_with_ttl(cache_key, result, _ttl_until_next_cycle())
            _save_forecast_disk_entry(cache_key, result)
            return result
        return None

    def _wavg(pairs: list[tuple[float, float]]) -> float:
        total_w = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total_w

    high_vals = [v for v, _ in highs]
    low_vals = [v for v, _ in lows]
    result = {
        "date": target_date.isoformat(),
        "city": city,
        "high_f": _wavg(highs),
        "low_f": _wavg(lows) if lows else None,
        "precip_in": _wavg(precips) if precips else 0.0,
        "models_used": len(highs),
        "high_range": (min(high_vals), max(high_vals)),
        # Low_range for model-spread gate on LOW markets
        "low_range": (min(low_vals), max(low_vals)) if low_vals else None,
    }
    # L5-A: align TTL to next NWS model cycle, not a flat 4 h window
    _forecast_cache.set_with_ttl(cache_key, result, _ttl_until_next_cycle())
    _save_forecast_disk_entry(cache_key, result)
    return result


def batch_prewarm_forecasts(
    city_dates: set[tuple[str, str]],
    progress_cb: Callable[[int, int, str, bool], None] | None = None,
) -> int:
    """Pre-warm _forecast_cache with batched Open-Meteo requests.

    Instead of one HTTP call per city per model (30 cities × 3 models = 90 calls),
    sends ONE request per model with all city lat/lons comma-separated.  Open-Meteo
    returns a JSON list with one element per location.  Total cost: 3 calls.

    Already-cached entries are skipped.  Returns the number of cache entries written.

    Args:
        city_dates: Set of (city, date_iso) pairs to pre-warm.
        progress_cb: Optional callback invoked after each model fetch with
            (current, total, model_name, success).  Use for progress display.
    """
    if _forecast_cb.is_open():
        _log.warning(
            "[batch_prewarm] forecast circuit breaker OPEN — skipping batch pre-warm (OM unavailable)"
        )
        return 0

    # Collect unique cities whose cache entry is absent or too old to pass the
    # FORECAST_MAX_AGE_SECS freshness gate in analyze_trade.
    import time as _time_prewarm

    cities_needed: set[str] = set()
    for city, date_iso in city_dates:
        _val, _hit, _ts = _forecast_cache.get_with_ts((city, date_iso))
        # get_with_ts() returns a wall-clock timestamp (time.time() - age), so compare with
        # time.time() not time.monotonic() (uptime ≈ 3600 s vs epoch ≈ 1.7e9 s — always negative).
        if not _hit or (_time_prewarm.time() - _ts) >= FORECAST_MAX_AGE_SECS:
            cities_needed.add(city)

    if not cities_needed:
        _log.debug(
            "[batch_prewarm] all entries already cached and fresh — nothing to fetch"
        )
        return 0

    coords_list = [
        (city, CITY_COORDS[city])
        for city in sorted(cities_needed)
        if city in CITY_COORDS
    ]
    if not coords_list:
        return 0

    lats = [c[1][0] for c in coords_list]
    lons = [c[1][1] for c in coords_list]
    city_names = [c[0] for c in coords_list]

    # Fetch 3 models in sequence (sequential to respect rate limit; each call covers
    # all cities so total latency ≈ 3 × one city's latency, not 30 × 3).
    batch_models = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]
    # city → model → daily dict
    city_model_data: dict[str, dict[str, dict]] = {c: {} for c in city_names}

    for idx, model in enumerate(batch_models, start=1):
        if _forecast_cb.is_open():
            _log.info("[batch_prewarm] circuit opened mid-batch — stopping")
            break
        ok = False
        try:
            resp = _om_request(
                "GET",
                FORECAST_BASE,
                params={
                    "latitude": ",".join(str(x) for x in lats),
                    "longitude": ",".join(str(x) for x in lons),
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "temperature_unit": "fahrenheit",
                    "precipitation_unit": "inch",
                    "timezone": "auto",
                    "forecast_days": 16,
                    "models": model,
                },
                timeout=12,  # was 30 — with Retry(total=3) a 30s timeout meant 4×30+backoff≈123s/call
            )
            resp.raise_for_status()
            results = resp.json()
            # Single location → dict; multiple → list of dicts
            if isinstance(results, dict):
                results = [results]
            # Check across ALL cities before deciding success/failure — a dead
            # model returns HTTP 200 with every city's array null. Checking
            # per-city after record_success() already fired would be too late
            # (record_success() resets the failure counter, silently
            # defeating the circuit breaker's ability to ever reach threshold).
            _flat_check = [
                v
                for r in results
                for v in (r.get("daily", {}).get("temperature_2m_max") or [])
            ]
            if is_all_null(_flat_check):
                raise ValueError(
                    f"model {model} returned all-null data across all cities (dead model?)"
                )
            _forecast_cb.record_success()
            for i, city in enumerate(city_names):
                if i < len(results):
                    city_model_data[city][model] = results[i].get("daily", {})
            ok = True
        except Exception as exc:
            _forecast_cb.record_failure()
            _log.info("[batch_prewarm] model %s failed: %s", model, exc)
        if progress_cb is not None:
            progress_cb(idx, len(batch_models), model, ok)

    # Blend available models and populate cache for each city/date pair.
    written = 0
    for city in city_names:
        model_data = city_model_data.get(city, {})
        if not model_data:
            continue
        # Use the date list from whichever model responded first
        dates_list: list[str] = next(
            (v.get("time", []) for v in model_data.values() if v.get("time")), []
        )
        # Derive month from the first available date string (YYYY-MM-DD)
        _month = int(dates_list[0][5:7]) if dates_list else 1
        _weights = _forecast_model_weights(_month, city)

        for j, date_str in enumerate(dates_list):
            cache_key = (city, date_str)
            highs: list[tuple[float, float]] = []
            lows: list[tuple[float, float]] = []
            precips: list[tuple[float, float]] = []
            for model_name, mdata in model_data.items():
                w = _weights.get(model_name, 1.0)
                h = mdata.get("temperature_2m_max") or []
                lo = mdata.get("temperature_2m_min") or []
                p = mdata.get("precipitation_sum") or []
                if j < len(h) and h[j] is not None:
                    highs.append((h[j], w))
                if j < len(lo) and lo[j] is not None:
                    lows.append((lo[j], w))
                if j < len(p) and p[j] is not None:
                    precips.append((p[j], w))
            if not highs:
                continue

            def _wavg_local(pairs: list[tuple[float, float]]) -> float:
                total_w = sum(wt for _, wt in pairs)
                return sum(v * wt for v, wt in pairs) / total_w

            high_vals = [v for v, _ in highs]
            low_vals = [v for v, _ in lows]
            entry: dict = {
                "date": date_str,
                "city": city,
                "high_f": _wavg_local(highs),
                "low_f": _wavg_local(lows) if lows else None,
                "precip_in": _wavg_local(precips) if precips else 0.0,
                "models_used": len(highs),
                "high_range": (min(high_vals), max(high_vals)),
                "low_range": (min(low_vals), max(low_vals)) if low_vals else None,
                "_source": "batch_prewarm",
            }
            _forecast_cache.set_with_ttl(cache_key, entry, _ttl_until_next_cycle())
            _save_forecast_disk_entry(cache_key, entry)
            written += 1

    _log.info(
        "[batch_prewarm] wrote %d cache entries for %d cities (%d models attempted)",
        written,
        len(city_names),
        len(batch_models),
    )
    return written


def batch_prewarm_ensemble(
    city_dates: set[tuple[str, str]],
    progress_cb: Callable[[int, int, str, bool], None] | None = None,
) -> int:
    """Pre-warm _ensemble_cache with batched ENSEMBLE_BASE requests.

    Instead of one request per city per model (30 cities × 3 models × 2 vars = 180
    calls), sends ONE request per (model, var) with all city lat/lons comma-separated.
    Total cost: 6 calls. At 1.5 s/call this cuts ensemble prewarm from ~270 s to
    ~30 s (rate overhead + HTTP latency).

    Returns the number of _ensemble_cache entries written.
    """
    if _ensemble_cb.is_open():
        _log.warning(
            "[batch_prewarm_ensemble] ensemble circuit OPEN — skipping batch prewarm"
        )
        return 0

    unique_cities: set[str] = {city for city, _ in city_dates}
    unique_dates: set[str] = {date_iso for _, date_iso in city_dates}

    coords_list = [
        (city, CITY_COORDS[city])
        for city in sorted(unique_cities)
        if city in CITY_COORDS
    ]
    if not coords_list:
        return 0

    city_names = [c[0] for c in coords_list]
    lats = [c[1][0] for c in coords_list]
    lons = [c[1][1] for c in coords_list]

    ensemble_models = [*ENSEMBLE_MODELS, "ecmwf_aifs025_ensemble"]
    vars_to_fetch = [("max", "temperature_2m_max"), ("min", "temperature_2m_min")]
    total_calls = len(ensemble_models) * len(vars_to_fetch)
    call_num = 0

    # raw_members[(city, date_iso, var_str)] accumulates members across models
    # before weighting; keyed by model for per-model weight application.
    raw_by_model: dict[str, dict[tuple[str, str, str], list[float]]] = {
        m: {} for m in ensemble_models
    }

    for model in ensemble_models:
        if _ensemble_cb.is_open():
            break
        for var_str, daily_key in vars_to_fetch:
            call_num += 1
            ok = False
            try:
                resp = _om_request(
                    "GET",
                    ENSEMBLE_BASE,
                    params={
                        "latitude": ",".join(str(x) for x in lats),
                        "longitude": ",".join(str(x) for x in lons),
                        "daily": daily_key,
                        "temperature_unit": "fahrenheit",
                        "timezone": "auto",
                        "forecast_days": 16,
                        "models": model,
                    },
                    timeout=8,
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    data = [data]

                # Check across ALL cities before deciding success/failure — see
                # the identical comment in batch_prewarm_forecasts for why this
                # must happen before record_success(), not after.
                _flat_check = [
                    v
                    for city_resp in data
                    if isinstance(city_resp, dict)
                    for k, arr in city_resp.get("daily", {}).items()
                    if k.startswith(f"{daily_key}_member") and isinstance(arr, list)
                    for v in arr
                ]
                if is_all_null(_flat_check):
                    raise ValueError(
                        f"model {model} returned all-null {var_str} ensemble members across all cities (dead model?)"
                    )
                _ensemble_cb.record_success()
                ok = True

                for i, city_name in enumerate(city_names):
                    if i >= len(data):
                        break
                    city_resp = data[i]
                    if not isinstance(city_resp, dict):
                        continue
                    daily = city_resp.get("daily", {})
                    if not isinstance(daily, dict):
                        continue
                    dates = daily.get("time", [])

                    for date_iso in unique_dates:
                        if date_iso not in dates:
                            continue
                        idx = dates.index(date_iso)
                        member_temps = [
                            daily[k][idx]
                            for k in daily
                            if k.startswith(f"{daily_key}_member")
                            and isinstance(daily[k], list)
                            and idx < len(daily[k])
                            and daily[k][idx] is not None
                        ]
                        if member_temps:
                            raw_by_model[model][(city_name, date_iso, var_str)] = (
                                member_temps
                            )

            except Exception as exc:
                _ensemble_cb.record_failure()
                _log.debug(
                    "batch_prewarm_ensemble: model=%s var=%s — %s: %s",
                    model,
                    var_str,
                    type(exc).__name__,
                    exc,
                )

            if progress_cb:
                progress_cb(call_num, total_calls, f"{model}/{var_str}", ok)

    # Combine raw members across models with the same weighting as get_ensemble_temps,
    # then populate _ensemble_cache for each (city, date, None, var).
    # H-14: also write per-model entries so _get_consensus_probs hits cache instead
    # of going to the network for every market.  _get_consensus_probs reads keys of
    # the form (model_name, city, date_iso, var, hour); daily markets use hour=None.
    written = 0
    for city_name in city_names:
        for date_iso in unique_dates:
            target_month = date.fromisoformat(date_iso).month
            weights = _model_weights(city_name, month=target_month)
            for var_str, _ in vars_to_fetch:
                cache_key = (city_name, date_iso, None, var_str)
                # Overwrite even if a (possibly stale, disk-resurrected) entry
                # already exists — the network cost of this fetch is already
                # paid, so skipping the write here would discard freshly
                # downloaded members in favor of data from a superseded model
                # cycle.
                all_temps: list[float] = []
                _cycle_ttl = _ttl_until_next_cycle()
                for model in ensemble_models:
                    member_temps = raw_by_model[model].get(
                        (city_name, date_iso, var_str), []
                    )
                    base_w = weights.get(model, 1.0)
                    w = 1.0 + (base_w - 1.0) * 1.0  # decay=1.0 for fresh data
                    repeats = max(1, round(w * 2))
                    all_temps.extend(member_temps * repeats)
                    # H-14: write per-model entry for _get_consensus_probs
                    if member_temps:
                        _model_key = (model, city_name, date_iso, var_str, None)
                        _ensemble_cache.set_with_ttl(
                            _model_key, member_temps, _cycle_ttl
                        )
                        _save_ensemble_disk_entry(_model_key, member_temps, _cycle_ttl)
                if all_temps:
                    _ensemble_cache.set_with_ttl(cache_key, all_temps, _cycle_ttl)
                    _save_ensemble_disk_entry(cache_key, all_temps, _cycle_ttl)
                    written += 1

    # Precipitation: 3 models × 1 var = 3 more ENSEMBLE_BASE calls.
    # Populates _PRECIP_ENSEMBLE_CACHE keyed by (lat, lon, date_iso) so
    # _fetch_ensemble_precip skips the wire during analysis.
    # Members are collected into a per-run local dict first (mirroring the
    # temperature path's raw_by_model above) and the cache entry is fully
    # overwritten once per run below — NOT appended onto the existing cache
    # entry — since cron calls this function every scan cycle and appending
    # would accumulate an ever-growing mix of stale + fresh member generations
    # that never ages out (each append also refreshes the TTL timestamp).
    precip_models = [*ENSEMBLE_MODELS, "ecmwf_ifs025"]
    precip_raw_by_model: dict[str, dict[tuple, list[float]]] = {
        m: {} for m in precip_models
    }
    for model in precip_models:
        if _ensemble_cb.is_open():
            break
        ok = False
        try:
            resp = _om_request(
                "GET",
                ENSEMBLE_BASE,
                params={
                    "latitude": ",".join(str(x) for x in lats),
                    "longitude": ",".join(str(x) for x in lons),
                    "daily": "precipitation_sum",
                    "precipitation_unit": "inch",
                    "timezone": "auto",
                    "forecast_days": 16,
                    "models": model,
                },
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                data = [data]

            # Check across ALL cities before deciding success/failure — see
            # the identical comment in batch_prewarm_forecasts for why this
            # must happen before record_success(), not after.
            _flat_check = [
                v
                for city_resp in data
                if isinstance(city_resp, dict)
                for k, arr in city_resp.get("daily", {}).items()
                if k.startswith("precipitation_sum_member") and isinstance(arr, list)
                for v in arr
            ]
            if is_all_null(_flat_check):
                raise ValueError(
                    f"model {model} returned all-null precip ensemble members across all cities (dead model?)"
                )
            _ensemble_cb.record_success()
            ok = True

            for i, city_name in enumerate(city_names):
                if i >= len(data):
                    break
                city_resp = data[i]
                if not isinstance(city_resp, dict):
                    continue
                daily = city_resp.get("daily", {})
                if not isinstance(daily, dict):
                    continue
                dates_list = daily.get("time", [])
                lat_i, lon_i = lats[i], lons[i]

                for date_iso in unique_dates:
                    if date_iso not in dates_list:
                        continue
                    idx = dates_list.index(date_iso)
                    members = [
                        daily[k][idx]
                        for k in daily
                        if k.startswith("precipitation_sum_member")
                        and isinstance(daily[k], list)
                        and idx < len(daily[k])
                        and daily[k][idx] is not None
                    ]
                    if members:
                        precip_raw_by_model[model][(lat_i, lon_i, date_iso)] = members

        except Exception as exc:
            _ensemble_cb.record_failure()
            _log.debug(
                "batch_prewarm_ensemble precip: model=%s — %s: %s",
                model,
                type(exc).__name__,
                exc,
            )

    all_precip_keys: set[tuple] = {
        key for by_key in precip_raw_by_model.values() for key in by_key
    }
    for cache_key_p in all_precip_keys:
        # Only overwrite when every model contributed to THIS key this run — a
        # partial run (one model's request failed, or the circuit breaker
        # opened mid-loop) must not clobber a complete, still-fresh existing
        # entry with a thinner one (e.g. dropping ECMWF's 2-3x seasonal
        # weighting) just because the cache key happens to match.
        if not all(precip_raw_by_model[m].get(cache_key_p) for m in precip_models):
            continue
        # Keyed by the market's TARGET date's month (matching
        # _fetch_ensemble_precip's convention), not the current date at
        # prewarm time — otherwise the same market gets a different ECMWF
        # weight depending on which code path populated the cache, causing
        # the blended probability to flap across season boundaries with no
        # underlying data change.
        _target_month = date.fromisoformat(cache_key_p[2]).month
        ecmwf_mult = 3 if _target_month in (10, 11, 12, 1, 2, 3) else 2
        combined = []
        for model in precip_models:
            mult = ecmwf_mult if model == "ecmwf_ifs025" else 1
            combined.extend(precip_raw_by_model[model][cache_key_p] * mult)
        _PRECIP_ENSEMBLE_CACHE[cache_key_p] = (combined, time.monotonic())
        written += 1

    _log.info(
        "[batch_prewarm_ensemble] wrote %d cache entries (%d cities, %d dates)",
        written,
        len(city_names),
        len(unique_dates),
    )
    return written


# ── NBM (National Blend of Models) ──────────────────────────────────────────

_NBM_CACHE: dict[tuple, tuple[float | None, float]] = {}
_ECMWF_CACHE: dict[tuple, tuple[float | None, float]] = {}
# Keyed by (lat, lon, date_iso) — shared across all _fetch_ensemble_precip callers.
_PRECIP_ENSEMBLE_CACHE: dict[tuple, tuple[list[float], float]] = {}
_MODEL_CACHE_TTL = 4 * 60 * 60  # 4 hours


def fetch_temperature_nbm(
    city: str, target_date: date, var: str = "max"
) -> float | None:
    """
    Fetch the real NBM (National Blend of Models) daily max/min for a city,
    via IEM's NBS station bulletin (mos.fetch_nbm_iem) -- the actual NBM,
    at the exact ASOS station Kalshi settles on (see backlog.txt: REAL NBM
    VIA IEM NBS STATION BULLETINS). Falls back to Open-Meteo model="best_match"
    (an uncalibrated auto-selection, NOT real NBM -- Open-Meteo dropped the
    "nbm" model name in 2026) when NBS has no coverage for this station/date,
    e.g. same-day markets, where NBS's own forecast horizon typically has
    zero rows -- use the METAR pipeline for those instead, as the rest of
    this codebase already does.

    var: "max" for daily high (default), "min" for daily low.
    H-13: LOW markets require min(temps), not max(temps).
    Returns temperature in °F for target_date, or None on failure.
    """
    cache_key = (city, target_date.isoformat(), var)
    cached = _NBM_CACHE.get(cache_key)
    if cached is not None:
        val, ts = cached
        if time.monotonic() - ts < _MODEL_CACHE_TTL:
            return val

    station = _metar_station_for_city(city)
    if station:
        try:
            import mos as _mos_mod

            _iem_val = _mos_mod.fetch_nbm_iem(
                station,
                target_date,
                _CITY_TZ.get(city, "America/New_York"),
                var=var,
            )
        except Exception as exc:
            _log.debug(
                "fetch_temperature_nbm: IEM NBS fetch failed for %s: %s", city, exc
            )
            _iem_val = None
        if _iem_val is not None:
            now = time.monotonic()
            _NBM_CACHE[cache_key] = (_iem_val, now)
            return _iem_val

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _nbm_om_cb.is_open():
        _log.debug("[CircuitBreaker] nbm_openmeteo circuit open — skipping NBM fetch")
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
                "models": "best_match",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "timezone": "auto",
            },
            timeout=5,
        )
        resp.raise_for_status()
        _nbm_om_cb.record_success()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        # H-13: return min for LOW markets, max for HIGH markets.
        # The request is identical regardless of var (same hourly series), so
        # opportunistically populate the OTHER var-keyed cache entry too from
        # this one response — otherwise a caller that warms both vars (e.g.
        # cron's prewarm) would re-issue a byte-identical HTTP request for the
        # second var every time. But never clobber an OTHER-var entry that's
        # still fresh: it may hold a real IEM NBM value (fetch_nbm_iem above
        # has per-var coverage gaps at NBS's ~3-day horizon edge -- a date can
        # have a 00Z max row but no 12Z min row yet, or vice versa), and this
        # Open-Meteo best_match fallback is exactly the uncalibrated
        # substitute that value exists to replace. Confirmed via independent
        # review 2026-07-17 (backlog.txt: REAL NBM VIA IEM NBS STATION
        # BULLETINS) that the unconditional dual-write silently and
        # order-dependently reintroduced the placeholder this fix removes.
        now = time.monotonic()
        if valid:
            _extremes = {"max": float(max(valid)), "min": float(min(valid))}
            _NBM_CACHE[(city, target_date.isoformat(), var)] = (_extremes[var], now)
            _other_var = "min" if var == "max" else "max"
            _other_key = (city, target_date.isoformat(), _other_var)
            _other_existing = _NBM_CACHE.get(_other_key)
            if (
                _other_existing is None
                or (now - _other_existing[1]) >= _MODEL_CACHE_TTL
            ):
                _NBM_CACHE[_other_key] = (_extremes[_other_var], now)
        else:
            _NBM_CACHE[cache_key] = (None, now)
        return _NBM_CACHE[cache_key][0]
    except Exception as exc:
        _nbm_om_cb.record_failure()
        _log.debug(
            "nbm_openmeteo: failure #%d (NBM/%s) — %s: %s",
            _nbm_om_cb.failure_count,
            city,
            type(exc).__name__,
            exc,
        )
        _NBM_CACHE[cache_key] = (None, time.monotonic())
        return None


# ── HRRR (High-Resolution Rapid Refresh) — same-day only ────────────────────
# HRRR runs every hour at 3 km resolution and is the best available model for
# same-day (days_out == 0) CONUS markets after ~10 AM local time.
# Open-Meteo exposes HRRR implicitly via model=best_match for CONUS locations.
# This is a standalone utility; it is NOT wired into analyze_trade yet — that
# happens once HRRR data has been validated against settled same-day trades.

_HRRR_CACHE: dict[str, tuple[float | None, float]] = {}


def _fetch_hrrr_temp(city: str, target_date: date, var: str = "max") -> float | None:
    """Fetch HRRR-derived hourly temperature and return the daily max or min.

    Uses Open-Meteo's hourly forecast endpoint with model=best_match, which
    selects HRRR for CONUS cities.  Returns daily max when var='max', daily min
    when var='min'.  Returns None if HRRR data is unavailable or the city is not
    mapped in CITY_COORDS.

    Intended for same-day markets (days_out == 0) only.  Uses a 4-hour in-process
    cache matching the TTL of the other model caches (_MODEL_CACHE_TTL).
    """
    import requests as _req

    cache_key = f"{city}_{target_date.isoformat()}_{var}"
    cached = _HRRR_CACHE.get(cache_key)
    if cached is not None:
        val, ts = cached
        if time.monotonic() - ts < _MODEL_CACHE_TTL:
            return val

    city_info = CITY_COORDS.get(city)
    if not city_info:
        return None

    # CITY_COORDS stores (lat, lon, timezone) tuples — unpack directly.
    lat, lon, tz = city_info[0], city_info[1], city_info[2]

    date_str = target_date.isoformat()
    try:
        resp = _req.get(
            FORECAST_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "timezone": tz,
                "start_date": date_str,
                "end_date": date_str,
                "models": "best_match",
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        if not valid:
            _HRRR_CACHE[cache_key] = (None, time.monotonic())
            return None
        result = float(max(valid) if var == "max" else min(valid))
        _HRRR_CACHE[cache_key] = (result, time.monotonic())
        return result
    except Exception as exc:
        _log.debug("_fetch_hrrr_temp: %s %s failed: %s", city, date_str, exc)
        _HRRR_CACHE[cache_key] = (None, time.monotonic())
        return None


# ── weatherapi.com (commercial, independent model chain) ─────────────────────

WEATHERAPI_KEY: str = os.getenv("WEATHERAPI_KEY", "")
_WEATHERAPI_BASE = "https://api.weatherapi.com/v1/forecast.json"
_weatherapi_cb = CircuitBreaker(
    name="weatherapi", failure_threshold=3, recovery_timeout=3600
)
_WEATHERAPI_CACHE: dict[tuple, tuple[dict | None, float]] = {}


def fetch_temperature_weatherapi(city: str, target_date: date) -> dict | None:
    """
    Fetch high/low from weatherapi.com (free tier: 1M calls/month).

    Returns {"high_f": float, "low_f": float} or None if WEATHERAPI_KEY is
    unset, the circuit is open, or the request fails.
    """
    if not WEATHERAPI_KEY:
        return None

    cache_key = (city, target_date.isoformat())
    cached = _WEATHERAPI_CACHE.get(cache_key)
    if cached is not None:
        val, ts = cached
        if time.monotonic() - ts < _MODEL_CACHE_TTL:
            return val

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _weatherapi_cb.is_open():
        _log.debug("[CircuitBreaker] weatherapi circuit open — skipping fetch")
        return None

    # Compute against the city's LOCAL date, not UTC — WeatherAPI's forecastday
    # list starts at the location's local today. From ~19:00 ET (00:00 UTC)
    # until local midnight, UTC's date is already tomorrow-local; using it here
    # would undercount days_ahead by 1 for a tomorrow-local target, causing the
    # target-date match below to fail and negative-caching the miss for 4h —
    # exactly during the evening window this source is most needed as an
    # Open-Meteo-ensemble-circuit-open fallback.
    try:
        from zoneinfo import ZoneInfo as _ZI3

        _today_local = datetime.now(_ZI3(_CITY_TZ.get(city, "America/New_York"))).date()
    except Exception:
        _today_local = datetime.now(UTC).date()
    days_ahead = max(1, (target_date - _today_local).days + 1)
    if days_ahead > 14:
        _WEATHERAPI_CACHE[cache_key] = (None, time.monotonic())
        return None

    try:
        resp = requests.get(
            _WEATHERAPI_BASE,
            params={
                "key": WEATHERAPI_KEY,
                "q": f"{lat},{lon}",
                "days": str(days_ahead),
                "aqi": "no",
                "alerts": "no",
            },
            timeout=8,
        )
        resp.raise_for_status()
        _weatherapi_cb.record_success()
        data = resp.json()
        target_str = target_date.isoformat()
        forecast_days = data.get("forecast", {}).get("forecastday", [])
        day_data = next((d for d in forecast_days if d.get("date") == target_str), None)
        if day_data is None:
            _WEATHERAPI_CACHE[cache_key] = (None, time.monotonic())
            return None
        day = day_data.get("day", {})
        high = day.get("maxtemp_f")
        low = day.get("mintemp_f")
        result = (
            {"high_f": float(high), "low_f": float(low)}
            if high is not None and low is not None
            else None
        )
        _WEATHERAPI_CACHE[cache_key] = (result, time.monotonic())
        return result
    except Exception as exc:
        _weatherapi_cb.record_failure()
        _log.debug(
            "fetch_temperature_weatherapi(%s): %s: %s", city, type(exc).__name__, exc
        )
        _WEATHERAPI_CACHE[cache_key] = (None, time.monotonic())
        return None


_PIRATE_FORECAST_BASE = "https://api.pirateweather.net/forecast"
_PIRATE_TIMEMACHINE_BASE = "https://timemachine.pirateweather.net/forecast"

# Separate circuit breaker for Pirate Weather so Open-Meteo failures don't bleed over.
_pirate_cb = CircuitBreaker(
    name="pirate_weather", failure_threshold=3, recovery_timeout=3 * 3600
)


def fetch_temperature_pirate_weather(city: str, target_date: date) -> dict | None:
    """
    Fetch weather data from Pirate Weather (HRRR/GFS/GEFS blend).
    Used as fallback when Open-Meteo circuit breakers are open.

    Future/today dates use the forecast endpoint (with extend=hourly and version=2);
    past dates use the time machine (version=2 only — extend=hourly not supported).
    Requires PIRATE_WEATHER_API_KEY in environment.

    Returns a dict with high_f and many enriched fields, or None on failure.
    """
    api_key = os.getenv("PIRATE_WEATHER_API_KEY", "")
    if not api_key:
        return None

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _pirate_cb.is_open():
        _log.debug("[CircuitBreaker] pirate_weather circuit open — skipping fetch")
        return None

    today = datetime.now(UTC).date()
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
                "exclude": "currently,minutely,alerts",
                "units": "us",
                "version": 2,
            }
        else:
            # Forecast endpoint — 7-day daily block, find matching day by timestamp
            url = f"{_PIRATE_FORECAST_BASE}/{api_key}/{lat},{lon}"
            params = {
                "exclude": "currently,minutely",
                "units": "us",
                "version": 2,
                "extend": "hourly",
            }

        resp = _request_with_retry("GET", url, params=params, timeout=8)
        resp.raise_for_status()
        _pirate_cb.record_success()
        data = resp.json()
        daily_data = data.get("daily", {}).get("data", [])
        if not daily_data:
            return None

        if is_historical:
            entry = daily_data[0]
        else:
            # M-14: Match by local calendar date — Pirate Weather `time` is midnight
            # in the city's local timezone, not UTC midnight.  Converting through the
            # city tz avoids up to ±12-hour mismatches that silently returned today's
            # block when tomorrow's data was requested.
            import zoneinfo as _zi

            _city_tz = _zi.ZoneInfo(_CITY_TZ.get(city, "America/New_York"))
            entry = next(
                (
                    d
                    for d in daily_data
                    if datetime.fromtimestamp(d.get("time", 0), tz=_city_tz).date()
                    == target_date
                ),
                None,
            )
            if entry is None:
                # Fail closed: this is the last-resort fallback (Open-Meteo, NBM,
                # and weatherapi all unavailable) — substituting daily_data[0]
                # (today's block) would hand the pricing engine today's high
                # labeled as target_date's high, with no distinguishing signal
                # beyond a warning log. Better to return no forecast at all than
                # a confidently-wrong one for the wrong day.
                _log.warning(
                    "fetch_temperature_pirate_weather(%s): no block matched %s "
                    "(target date beyond Pirate Weather's daily block range) — "
                    "returning no forecast rather than substituting the wrong day",
                    city,
                    target_date,
                )
                return None

        # temperatureMax is the absolute daily extreme; prefer over temperatureHigh
        # (daytime only). Explicit None-check — a legitimate 0.0°F temperatureMax
        # (routine in winter for the cities this bot trades) is falsy and would
        # otherwise silently fall through to temperatureHigh, which can differ
        # by several degrees on exactly the days this matters most.
        high = entry.get("temperatureMax")
        if high is None:
            high = entry.get("temperatureHigh")
        if high is None:
            return None
        high_f = float(high)

        # ── Item 5: temperatureMaxTime ────────────────────────────────────────
        temp_max_time_unix = entry.get("temperatureMaxTime")

        # ── Item 6: precipProbability, precipAccumulation, precipType ────────
        precip_prob = entry.get("precipProbability")
        precip_accum = entry.get("precipAccumulation")
        precip_in = float(precip_accum) if precip_accum is not None else 0.0
        precip_type = entry.get("precipType")

        # ── Item 9: liquidAccumulation, snowAccumulation, iceAccumulation (v2) ─
        liquid_accum = entry.get("liquidAccumulation")
        snow_accum = entry.get("snowAccumulation")
        ice_accum = entry.get("iceAccumulation")

        # ── Item 10: dewPoint, humidity ───────────────────────────────────────
        dew_point_f = entry.get("dewPoint")
        humidity = entry.get("humidity")

        # ── Item 11: windGust, windGustTime ───────────────────────────────────
        wind_gust = entry.get("windGust")
        wind_gust_time_unix = entry.get("windGustTime")

        # ── Item 8: elevation (top-level field) ───────────────────────────────
        elevation_m = data.get("elevation")

        # ── Item 3: hourly settlement-window high (forecast only) ─────────────
        hourly_window_high_f: float | None = None
        if not is_historical:
            hourly_data = data.get("hourly", {}).get("data", [])
            if hourly_data:
                # Collect hours 6am-9pm LOCAL time for target_date. Both the day
                # boundary and the hour-of-day check must be anchored in the
                # city's timezone (_city_tz, from the M-14 fix above) — anchoring
                # in UTC instead gave e.g. 1am-4pm local for ET cities and
                # 10pm(prev day)-1pm local for Pacific cities, silently missing
                # the actual afternoon-high hours the window claims to cover.
                target_ts_start_h = int(
                    datetime(
                        target_date.year,
                        target_date.month,
                        target_date.day,
                        tzinfo=_city_tz,
                    ).timestamp()
                )
                target_ts_end_h = target_ts_start_h + 86400
                window_temps = []
                for h_entry in hourly_data:
                    h_ts = h_entry.get("time", 0)
                    # Filter to the target calendar day (local-anchored)
                    if not (target_ts_start_h <= h_ts < target_ts_end_h):
                        continue
                    # Hour-of-day within the LOCAL day: 6am (6h) to 9pm (21h)
                    _local_hour = datetime.fromtimestamp(h_ts, tz=_city_tz).hour
                    if 6 <= _local_hour <= 21:
                        t_val = h_entry.get("temperature")
                        if t_val is not None:
                            window_temps.append(float(t_val))
                if window_temps:
                    hourly_window_high_f = max(window_temps)

        # ── Item 7: precipIntensityError — average over hourly data for target_date ─
        precip_intensity_error: float | None = None
        hourly_data_all = data.get("hourly", {}).get("data", [])
        if hourly_data_all:
            target_ts_start_pie = int(
                datetime(
                    target_date.year, target_date.month, target_date.day, tzinfo=UTC
                ).timestamp()
            )
            target_ts_end_pie = target_ts_start_pie + 86400
            pie_values = [
                float(h.get("precipIntensityError"))
                for h in hourly_data_all
                if target_ts_start_pie <= h.get("time", 0) < target_ts_end_pie
                and h.get("precipIntensityError") is not None
            ]
            if pie_values:
                precip_intensity_error = sum(pie_values) / len(pie_values)

        # ── Item 4: alerts — severity check ──────────────────────────────────
        alerts_raw = data.get("alerts", [])
        now_ts = int(datetime.now(UTC).timestamp())
        active_alerts = [
            {
                "title": a.get("title", ""),
                "severity": a.get("severity", ""),
                "expires": a.get("expires"),
            }
            for a in (alerts_raw or [])
            if a.get("expires") is None or a.get("expires", 0) > now_ts
        ]
        has_severe_alert = any(
            a["severity"] in ("Severe", "Extreme") for a in active_alerts
        )

        # ── Item 2: flags.sourceTimes — model freshness weighting ─────────────
        source_times_raw = data.get("flags", {}).get("sourceTimes", {})
        source_freshness_hours: dict[str, float] = {}
        stale_forecast = False
        if source_times_raw and isinstance(source_times_raw, dict):
            for model_key, time_str in source_times_raw.items():
                try:
                    # Format: "2025-06-07 16Z"
                    st_dt = datetime.strptime(time_str, "%Y-%m-%d %HZ").replace(
                        tzinfo=UTC
                    )
                    age_hours = (datetime.now(UTC) - st_dt).total_seconds() / 3600.0
                    source_freshness_hours[model_key] = round(age_hours, 2)
                except (ValueError, TypeError):
                    pass
            # Check HRRR staleness (covers hrrr_0-18 or similar keys)
            hrrr_age = next(
                (v for k, v in source_freshness_hours.items() if "hrrr" in k.lower()),
                None,
            )
            if hrrr_age is not None and hrrr_age > 6.0:
                stale_forecast = True

        # Explicit None-check — see the identical temperatureMax fix above;
        # a legitimate 0.0°F temperatureMin must not fall through to
        # temperatureLow (daytime-only, can differ by several degrees).
        low = entry.get("temperatureMin")
        if low is None:
            low = entry.get("temperatureLow")

        return {
            # Core fields (must match what the caller expects)
            "high_f": high_f,
            "low_f": float(low) if low is not None else None,
            "precip_in": precip_in,
            # Item 6
            "precip_prob": precip_prob,
            "precip_type": precip_type,
            # Item 10
            "dew_point_f": float(dew_point_f) if dew_point_f is not None else None,
            "humidity": float(humidity) if humidity is not None else None,
            # Item 11
            "wind_gust": float(wind_gust) if wind_gust is not None else None,
            "_wind_gust_time_unix": wind_gust_time_unix,
            # Item 5
            "_temp_max_time_unix": temp_max_time_unix,
            # Item 3
            "_hourly_window_high_f": hourly_window_high_f,
            # Item 4
            "_active_alerts": active_alerts,
            "_has_severe_alert": has_severe_alert,
            # Item 2
            "_source_freshness_hours": source_freshness_hours,
            "_stale_forecast": stale_forecast,
            # Item 7
            "_precip_intensity_error": precip_intensity_error,
            # Item 8
            "_elevation_m": float(elevation_m) if elevation_m is not None else None,
            # Item 9
            "_liquid_accum_in": float(liquid_accum)
            if liquid_accum is not None
            else None,
            "_snow_accum_in": float(snow_accum) if snow_accum is not None else None,
            "_ice_accum_in": float(ice_accum) if ice_accum is not None else None,
        }
    except Exception as exc:
        _pirate_cb.record_failure()
        _log.debug("fetch_temperature_pirate_weather(%s): %s", city, exc)
        return None


def _compute_ensemble_spread(temps: dict[str, float | None]) -> float:
    """Compute std dev of non-None values. Returns 0.0 if fewer than 2 valid."""
    values = [v for v in temps.values() if v is not None]
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


# NWS Day-3 high/low temperature forecast RMSE (σ, °F) per city/season.
# L8-C fix: (1) keyed by the city names enrich_with_forecast() stores in _city
#           (previous keys were abbreviated codes — "LAX","CHI","DAL" — which
#           never matched the full names "LA","Chicago","Dallas", so all cities
#           except NYC silently fell through to _DEFAULT_SIGMA = 5.0°F).
#           (2) values reduced from climatological std (5–8°F) to actual NWS
#           forecast RMSE (~2–4°F); sigma_mult applied at call site to scale
#           further for time-of-day horizon.
# Season: 1=Winter(DJF), 2=Spring(MAM), 3=Summer(JJA), 4=Fall(SON)
_HISTORICAL_SIGMA: dict[str, dict[int, float]] = {
    "NYC": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "Chicago": {1: 4.0, 2: 3.5, 3: 3.0, 4: 4.0},  # continental, volatile winter
    "LA": {1: 2.5, 2: 3.0, 3: 2.5, 4: 3.0},  # marine layer stabilises
    "Miami": {1: 2.0, 2: 2.5, 3: 2.0, 4: 2.5},  # tropical, very stable
    "Dallas": {1: 3.5, 2: 3.5, 3: 3.0, 4: 3.5},
    "Denver": {1: 4.5, 2: 4.0, 3: 3.5, 4: 4.0},  # mountain terrain, volatile
    "Boston": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "Phoenix": {1: 3.0, 2: 3.0, 3: 2.5, 4: 3.0},  # desert, low variability
    "Seattle": {1: 2.5, 2: 3.0, 3: 2.5, 4: 2.5},  # marine, stable
    "Atlanta": {1: 3.5, 2: 3.5, 3: 3.0, 4: 3.5},
    "Austin": {1: 3.5, 2: 3.5, 3: 3.0, 4: 3.5},
    "Houston": {1: 3.0, 2: 3.0, 3: 2.5, 4: 3.0},
    "Minneapolis": {1: 4.5, 2: 4.0, 3: 3.0, 4: 4.0},  # extreme winter variability
    "Washington": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "Philadelphia": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "SanFrancisco": {1: 2.5, 2: 3.0, 3: 2.5, 4: 2.5},  # marine, very stable
    "SanAntonio": {1: 3.0, 2: 3.5, 3: 3.0, 4: 3.0},
    "OklahomaCity": {1: 4.0, 2: 4.0, 3: 3.5, 4: 4.0},  # tornado alley, variable
}
_DEFAULT_SIGMA = 3.5


def _month_to_season(month: int) -> int:
    """Convert month (1-12) to season index (1=Winter, 2=Spring, 3=Summer, 4=Fall)."""
    return {12: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3, 9: 4, 10: 4, 11: 4}[
        month
    ]


_dynamic_sigma: dict = {}


def _load_dynamic_sigma() -> dict:
    """Lazily load+memoize per-city, per-month sigma computed from the 30yr
    climate archive (climatology.load_all_sigmas). Restored 2026-07-12 --
    silently lost in the 24559a7 mystery-revert (see backlog.txt)."""
    global _dynamic_sigma
    if _dynamic_sigma:
        return _dynamic_sigma
    try:
        from climatology import load_all_sigmas

        _dynamic_sigma = load_all_sigmas(CITY_COORDS)
    except Exception as _e:
        _log.debug("Dynamic sigma unavailable: %s", _e)
    return _dynamic_sigma


def get_historical_sigma(city: str, month: int, var: str = "max") -> float:
    """Return forecast RMSE sigma (°F) for a city/month.

    Prefers dynamic values computed from the 30yr climate archive (per-month
    resolution, covers every city in CITY_COORDS including cities absent from
    the static _HISTORICAL_SIGMA table below). Falls back to the static
    seasonal table, then _DEFAULT_SIGMA, if dynamic data is unavailable.

    City must match the name stored in the _city field by enrich_with_forecast()
    (e.g. "NYC", "Chicago", "LA", "Miami").
    """
    dynamic = _load_dynamic_sigma()
    city_data = dynamic.get(city, {})
    var_key = "min" if var == "min" else "max"
    dyn_val = city_data.get(var_key, {}).get(str(month))
    if dyn_val:
        return float(dyn_val)
    # Static fallback (seasonal granularity)
    season = _month_to_season(month)
    return _HISTORICAL_SIGMA.get(city, {}).get(season, _DEFAULT_SIGMA)


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


def fetch_temperature_ecmwf(
    city: str, target_date: date, var: str = "max"
) -> float | None:
    """
    Fetch ECMWF deterministic max or min daily temperature for a city.
    Uses Open-Meteo with models="ecmwf_ifs025" — the deterministic IFS product.
    "ecmwf_aifs025" was tried previously but returns HTTP 200 with null data
    on the deterministic /v1/forecast endpoint (that AIFS ensemble model is
    only served via the separate ensemble-api.open-meteo.com endpoint), so
    this function silently returned None every call until this fix.

    var: "max" for daily high (default), "min" for daily low.
    H-13: LOW markets require min(temps), not max(temps).
    Returns temperature in °F for target_date, or None on failure.
    """
    cache_key = (city, target_date.isoformat(), var)
    cached = _ECMWF_CACHE.get(cache_key)
    if cached is not None:
        val, ts = cached
        if time.monotonic() - ts < _MODEL_CACHE_TTL:
            return val

    coords = CITY_COORDS.get(city)
    if not coords:
        return None
    lat, lon, _ = coords

    if _ecmwf_om_cb.is_open():
        _log.debug(
            "[CircuitBreaker] ecmwf_openmeteo circuit open — skipping ECMWF fetch"
        )
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
                "models": "ecmwf_ifs025",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "timezone": "auto",
            },
            timeout=5,  # reduced from 8s — matches NBM timeout; circuit opens fast on slow endpoints
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        if is_all_null(temps):
            raise ValueError("ecmwf_ifs025 returned all-null hourly data (dead model?)")
        _ecmwf_om_cb.record_success()
        valid = [t for t in temps if t is not None]
        # H-13: return min for LOW markets, max for HIGH markets.
        # The request is identical regardless of var (same hourly series), so
        # populate BOTH var-keyed cache entries from this one response —
        # otherwise a caller that warms both vars (e.g. cron's prewarm) would
        # re-issue a byte-identical HTTP request for the second var every time.
        now = time.monotonic()
        if valid:
            _ECMWF_CACHE[(city, target_date.isoformat(), "max")] = (
                float(max(valid)),
                now,
            )
            _ECMWF_CACHE[(city, target_date.isoformat(), "min")] = (
                float(min(valid)),
                now,
            )
        else:
            _ECMWF_CACHE[cache_key] = (None, now)
        return _ECMWF_CACHE[cache_key][0]
    except Exception as exc:
        _ecmwf_om_cb.record_failure()
        _log.info(
            "ecmwf_openmeteo: failure #%d (ECMWF/%s) — %s: %s",
            _ecmwf_om_cb.failure_count,
            city,
            type(exc).__name__,
            exc,
        )
        _ECMWF_CACHE[cache_key] = (None, time.monotonic())
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
        _log.debug("[CircuitBreaker] open_meteo circuit open — skipping ensemble fetch")
        return []

    if hour is not None:
        params["hourly"] = "temperature_2m"
        try:
            resp = _om_request(
                "GET", ENSEMBLE_BASE, params=params, timeout=12
            )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
            resp.raise_for_status()
            _ensemble_cb.record_success()
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.info(
                "open_meteo_ensemble: failure #%d (hourly) — %s: %s",
                _ensemble_cb.failure_count,
                type(_exc).__name__,
                _exc,
            )
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
            resp = _om_request(
                "GET", ENSEMBLE_BASE, params=params, timeout=12
            )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
            resp.raise_for_status()
            _ensemble_cb.record_success()
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.info(
                "open_meteo_ensemble: failure #%d (daily) — %s: %s",
                _ensemble_cb.failure_count,
                type(_exc).__name__,
                _exc,
            )
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


_LEARNED_WEIGHTS: dict[str, dict[str, float]] = {}  # cached after first load
_LEARNED_WEIGHTS_TTL_DAYS = 7  # P3-7: single definition (duplicate removed)
_LEARNED_WEIGHTS_TTL_WARNED = False  # log-once flag — prevents per-market spam


def load_learned_weights() -> dict[str, dict[str, float]]:
    """
    Load per-city model weights previously saved by save_learned_weights().
    Format: {city: {model: weight, ...}, ...}
    Returns empty dict if file missing, malformed, empty, or has real content older than 7 days.
    An empty file ({}) is silently ignored regardless of age — nothing to go stale.
    Cached for the session.
    """
    global _LEARNED_WEIGHTS
    if _LEARNED_WEIGHTS:
        return _LEARNED_WEIGHTS
    path = Path(__file__).parent / "data" / "learned_weights.json"
    if not path.exists():
        return {}
    mtime = os.path.getmtime(path)
    age_secs = time.time() - mtime
    try:
        import json as _json

        loaded = _json.loads(path.read_text())
    except Exception:
        return {}
    # If the file has no actual city weights, age doesn't matter — there is nothing
    # to go stale. Return {} silently so we don't spam warnings when the file exists
    # but hasn't been populated yet (e.g. before enough per-city tracker data exists).
    if not loaded:
        return {}
    # File has real content: enforce TTL so stale learned weights don't mislead the
    # ensemble. Warn once per session then return {} so the bot uses neutral defaults.
    if age_secs > _LEARNED_WEIGHTS_TTL_DAYS * 86400:
        global _LEARNED_WEIGHTS_TTL_WARNED
        if not _LEARNED_WEIGHTS_TTL_WARNED:
            logging.warning(
                "[ModelWeights] learned_weights.json is %.1f days old (> %d-day TTL) — "
                "falling back to default weights",
                age_secs / 86400,
                _LEARNED_WEIGHTS_TTL_DAYS,
            )
            _LEARNED_WEIGHTS_TTL_WARNED = True
        return {}
    # P1-9: reject corrupt files where city values are floats (win-rates) not dicts
    for city, city_data in loaded.items():
        if not isinstance(city_data, dict):
            logging.warning(
                "[ModelWeights] learned_weights.json corrupt: city %s has %s — deleting",
                city,
                type(city_data).__name__,
            )
            try:
                path.unlink()
            except OSError:
                pass
            return {}
        if any(not isinstance(v, int | float) or v <= 0 for v in city_data.values()):
            logging.warning(
                "[ModelWeights] learned_weights.json corrupt: city %s has a "
                "non-numeric or non-positive weight — deleting",
                city,
            )
            try:
                path.unlink()
            except OSError:
                pass
            return {}
    _LEARNED_WEIGHTS = loaded
    return _LEARNED_WEIGHTS


def save_learned_weights(weights: dict) -> None:
    """
    Persist per-city model weights to data/learned_weights.json atomically.
    Called after a backtest to update city-specific model preferences.
    """
    import json as _json
    import os as _os
    import tempfile as _tmp

    # P1-9: validate before writing — reject win-rate floats masquerading as weights
    for city, city_data in weights.items():
        if not isinstance(city_data, dict):
            logging.error(
                "[ModelWeights] city %s has non-dict weights (%s) — not persisting",
                city,
                type(city_data).__name__,
            )
            return
        if any(not isinstance(v, int | float) or v < 0.001 for v in city_data.values()):
            logging.error(
                "[ModelWeights] city %s has non-numeric or near-zero weights — "
                "not persisting (corruption risk)",
                city,
            )
            return

    path = Path(__file__).parent / "data" / "learned_weights.json"
    path.parent.mkdir(exist_ok=True)
    fd, tmp = _tmp.mkstemp(dir=path.parent, prefix=".lw_", suffix=".json")
    try:
        with _os.fdopen(fd, "w") as f:
            _json.dump(weights, f, indent=2)
        _os.replace(tmp, path)
    except Exception as exc:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        # Log (every other persistence failure in this file does) and skip the
        # in-memory cache update — otherwise this process trades on the new
        # weights while learned_weights.json still holds the old ones, so the
        # next process/cron run silently reverts to different weights than
        # tonight's, with zero trace in the logs to explain why.
        _log.warning(
            "[ModelWeights] save_learned_weights: write failed, keeping prior "
            "on-disk weights (in-memory cache NOT updated): %s",
            exc,
        )
        return
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

        snap_dir = Path(__file__).parent / "data" / "forecast_snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        safe_ticker = ticker.replace("/", "-").replace(":", "-")
        _today_str = datetime.now(UTC).date().isoformat()
        path = snap_dir / f"{safe_ticker}_{_today_str}.json"
        # Don't overwrite existing snapshot for same ticker+day
        if not path.exists():
            snapshot = {
                "ticker": ticker,
                "snapshot_date": _today_str,
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
        city_n_bd = stats.get("city_n_breakdown", {})
        # R25: use per-city observation count (not number of distinct cities) to
        # decide whether city-specific MAE is reliable enough to use.
        city_mae = city_bd.get(city)
        city_n = city_n_bd.get(city, 0)
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
) -> dict[str, float] | None:
    """
    Derive per-model blend weights from tracker softmax-MAE data via
    get_model_weights(). Returns None when city is None or tracker has no rows.
    Falls back to equal weights when any model has < 10 obs. Lower MAE → higher weight.
    """
    if city is None:
        return None
    try:
        from tracker import get_model_weights as _gmw

        w = _gmw(city=city, window_days=30)
        return w if w else None
    except Exception:
        return None


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
    Priority order — tier 1 is all-or-nothing against the seasonal baseline
    (tier 3), NOT merged per-model with tier 2 (unlike _forecast_model_weights,
    which does compose all three tiers per-model):
      1. Per-city inverse-MAE weights derived from tracker data (#25/#118),
         blended 70/30 against the seasonal prior directly — if this tier
         fires, tier 2 is skipped entirely, even for models tier 1 lacks.
      2. Manually learned weights from data/learned_weights.json (from
         backtest), merged per-model onto the seasonal prior for any model
         it omits.
      3. Seasonal ECMWF/GFS priors (original behaviour)
    """
    # 3. Seasonal ECMWF weight: better in winter for mid-latitude US cities —
    # computed first as the baseline/floor
    if month is not None:
        is_winter = month in (10, 11, 12, 1, 2, 3)
        ecmwf_w = 2.0 if is_winter else 1.5
    else:
        ecmwf_w = 1.5  # conservative default

    baseline = {
        "icon_seamless": 1.0,
        "gfs_seamless": 1.0,
        "ecmwf_aifs025_ensemble": ecmwf_w,
    }

    # 1. Dynamic: derive from recent tracker MAE data. Blends against the
    # seasonal baseline directly (not tier 2) — loop over baseline's keys only
    # (not mae_weights' keys) so a stray tracked value (e.g. "blended", the
    # bias-corrected prediction — not a real model) can never leak into the
    # ensemble's model-weight set.
    mae_weights = _weights_from_mae(city)
    if mae_weights:
        return {m: 0.7 * mae_weights.get(m, 1.0) + 0.3 * baseline[m] for m in baseline}

    # 2. Pre-saved learned weights from last backtest run (per-model, only known keys)
    lw = load_learned_weights()
    city_data = lw.get(city)
    if city_data is not None and not isinstance(city_data, dict):
        # Guard: learned_weights.json sometimes gets written with raw win-rates
        # (floats) instead of the expected {model: weight} dict — e.g. when a
        # walk-forward backtest saves city_win_rates directly.  Fall through to
        # seasonal defaults rather than crashing with "float is not iterable".
        _log.debug(
            "[ModelWeights] %s: learned_weights.json has %s (expected dict) — "
            "skipping, using seasonal defaults",
            city,
            type(city_data).__name__,
        )
        city_data = None
    learned = city_data if isinstance(city_data, dict) else {}
    return {model: learned.get(model, default) for model, default in baseline.items()}


def _ensemble_circuit_is_open() -> bool:
    """Return True if the Open-Meteo ensemble circuit breaker is currently OPEN."""
    return _ensemble_cb.is_open()


def check_ensemble_circuit_health() -> None:
    """
    Log a warning if the open_meteo_ensemble circuit has been open for >24 hours.
    Call once at cron startup to surface prolonged outages immediately.
    """
    secs = _ensemble_cb.seconds_open()
    if secs <= 0:
        return
    hours = secs / 3600
    if hours >= 24:
        _log.warning(
            "[DataSource] open_meteo_ensemble circuit has been OPEN for %.1f hours — "
            "NBM + weatherapi are now the primary ensemble sources",
            hours,
        )
    else:
        _log.info(
            "[DataSource] open_meteo_ensemble circuit OPEN (%.0f min) — "
            "using NBM + weatherapi as fallback",
            secs / 60,
        )


_BIMODAL_KELLY_MULTIPLIER = 0.10  # 10% of normal Kelly when ensemble is bimodal


def _detect_bimodal_ensemble(temps: list[float]) -> bool:
    """Return True when ensemble members form two distinct clusters (bimodal distribution).

    Uses a largest-gap split: if both clusters contain at least 20% of members
    AND the gap between cluster means is >= 8 degrees F, the distribution is bimodal.
    Requires at least 10 members; returns False for smaller ensembles.
    """
    if len(temps) < 10:
        return False

    sorted_temps = sorted(temps)
    n = len(sorted_temps)
    gaps = [(sorted_temps[i + 1] - sorted_temps[i], i) for i in range(n - 1)]
    max_gap, split_idx = max(gaps)

    if max_gap < 6.0:
        return False

    cluster_a = sorted_temps[: split_idx + 1]
    cluster_b = sorted_temps[split_idx + 1 :]

    min_cluster_size = max(2, int(n * 0.20))
    if len(cluster_a) < min_cluster_size or len(cluster_b) < min_cluster_size:
        return False

    mean_a = statistics.mean(cluster_a)
    mean_b = statistics.mean(cluster_b)
    return abs(mean_b - mean_a) >= 8.0


def _get_bimodal_kelly_multiplier(temps: list[float]) -> float:
    """Return 0.10 when ensemble is bimodal (two distinct weather scenarios), else 1.0."""
    if _detect_bimodal_ensemble(temps):
        _log.warning(
            "BIMODAL ensemble detected (%d members) — Kelly reduced to 10%%", len(temps)
        )
        return _BIMODAL_KELLY_MULTIPLIER
    return 1.0


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
    cached_data = _ensemble_cache.get(cache_key)
    if cached_data is not None:
        return cached_data

    coords = CITY_COORDS.get(city)
    if not coords:
        return []
    lat, lon, tz = coords

    weights = _model_weights(city, month=target_date.month)

    # We only reach here when building fresh data (stale cache was discarded above,
    # or no cache existed). Always use full model weights for a fresh fetch.
    decay = 1.0

    all_temps: list[float] = []
    ensemble_models_with_ecmwf = [*ENSEMBLE_MODELS, "ecmwf_aifs025_ensemble"]
    for model in ensemble_models_with_ecmwf:
        try:
            temps = _fetch_model_ensemble(lat, lon, tz, target_date, model, hour, var)
            base_w = weights.get(model, 1.0)
            # Decay towards equal weighting (1.0) as cache ages
            w = 1.0 + (base_w - 1.0) * decay
            # Replicate members proportionally to apply weight.
            repeats = max(1, round(w * 2))
            all_temps.extend(temps * repeats)
        except Exception as _ens_exc:
            _log.warning(
                "get_ensemble_temps: model fetch failed for %s: %s", city, _ens_exc
            )

    # L5-A: align TTL to next NWS model cycle, not a flat 4 h window.
    # Don't cache/persist a total-failure empty result (all model fetches
    # raised, e.g. circuit breaker open) — that would freeze the ensemble at
    # zero members for up to the full cycle TTL (dropping ens_prob out of the
    # blend and silently skipping the bimodal-Kelly risk guard, which checks
    # `if temps`) instead of letting the next call retry once the endpoint
    # recovers, which can be within seconds of a transient blip.
    if all_temps:
        _cycle_ttl = _ttl_until_next_cycle()
        _ensemble_cache.set_with_ttl(cache_key, all_temps, _cycle_ttl)
        _save_ensemble_disk_entry(cache_key, all_temps, _cycle_ttl)
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
    _std = statistics.stdev(temps) if len(temps) > 1 else 0.0
    return {
        "n": len(temps),
        "mean": statistics.mean(temps),
        "std": _std,
        "min": min(temps),
        "max": max(temps),
        "p10": sorted(temps)[min(int(len(temps) * 0.10), len(temps) - 1)],
        "p90": sorted(temps)[min(int(len(temps) * 0.90), len(temps) - 1)],
        "degenerate": len(temps) > 5 and _std == 0.0,
    }


def get_ensemble_members(
    lat: float,
    lon: float,
    target_date_str: str,
    var: str = "max",
    tz: str = "UTC",
) -> list[float] | None:
    """
    Fetch all ECMWF AIFS ensemble members for daily high (var='max') or
    low (var='min') temperature on target_date. Returns values in °F.

    Uses _fetch_model_ensemble (daily endpoint) so the 50 per-member daily
    aggregates come directly from Open-Meteo without manual hourly max/min
    computation. Disk-caches to data/ensemble_cache/ for the session TTL.
    """
    import json as _json_em

    cache_dir = Path(__file__).parent / "data" / "ensemble_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{lat:.3f}_{lon:.3f}_{target_date_str}_{var}.json"
    if cache_file.exists():
        try:
            if time.time() - cache_file.stat().st_mtime < _ENSEMBLE_CACHE_TTL:
                return _json_em.loads(cache_file.read_text())
        except Exception:
            pass

    try:
        target_date = date.fromisoformat(target_date_str)
        members = _fetch_model_ensemble(
            lat, lon, tz, target_date, "ecmwf_aifs025_ensemble", None, var
        )
    except Exception as _e:
        _log.debug("get_ensemble_members: fetch failed: %s", _e)
        return None

    if len(members) < 10:
        _log.debug(
            "get_ensemble_members: only %d AIFS ensemble members returned", len(members)
        )
        return None

    try:
        cache_file.write_text(_json_em.dumps(members))
    except Exception:
        pass

    return members


def ensemble_cdf_prob(members: list[float], condition: dict) -> float:
    """
    Compute P(outcome | condition) from raw ensemble members via empirical CDF.
    More accurate than Gaussian approximation for skewed or bimodal distributions.

    Args:
        members: list of forecast values in °F (e.g., 51 ECMWF IFS04 members)
        condition: {"type": "above"/"below"/"between", "threshold"/"lower"/"upper"}
    """
    if not members:
        return 0.5

    n = len(members)
    ctype = condition.get("type", "above")

    if ctype == "above":
        return sum(1 for m in members if m > _prob_threshold(condition)) / n
    if ctype == "below":
        return sum(1 for m in members if m < _prob_threshold(condition)) / n
    if ctype == "between":
        lo, hi = condition["lower"], condition["upper"]
        return sum(1 for m in members if lo <= m <= hi) / n

    return 0.5


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
    # L2-D: use None-check coalesce so a valid 0-valued field (0¢ bid) is not
    # bypassed by the falsy `or` operator.
    def _coalesce(market: dict, *keys: str) -> object:
        """Return first non-None value for any of keys, or 0."""
        for k in keys:
            v = market.get(k)
            if v is not None:
                return v
        return 0

    yes_bid = _coalesce(market, "yes_bid", "yes_bid_dollars")
    yes_ask = _coalesce(market, "yes_ask", "yes_ask_dollars")
    no_bid = _coalesce(market, "no_bid", "no_bid_dollars")

    # Prices may be cents (int) or dollar strings depending on API version
    def to_float(v) -> float:
        if isinstance(v, str):
            v_f = float(v)
            # String prices > 1.0 are in the legacy cents-as-string format
            return v_f / 100.0 if v_f > 1.0 else v_f
        # L2-D: split int vs float so integer 1 (= 1¢) is correctly divided by
        # 100.  The old `v > 1` test returned float(1) = 1.0 for a 1¢ market.
        if isinstance(v, int) and v >= 1:
            return v / 100.0  # integer cents format (e.g. 55 → 0.55)
        if isinstance(v, float) and v > 1.0:
            return v / 100.0  # float >1.0 also indicates cents (some API variants)
        return float(v)

    yes_bid_f = to_float(yes_bid)
    yes_ask_f = to_float(yes_ask)
    no_bid_f = to_float(no_bid)
    mid = (yes_bid_f + yes_ask_f) / 2 if yes_ask_f > 0 else yes_bid_f

    # Skip markets where both bid and ask are zero (no real quote).
    has_quote = mid > 0

    return {
        "yes_bid": yes_bid_f,
        "yes_ask": yes_ask_f,
        "no_bid": no_bid_f,
        "mid": mid,
        "implied_prob": mid,  # mid-price ≈ market probability
        "has_quote": has_quote,
    }


def is_stale(market: dict) -> bool:
    """
    Returns True if a market has no volume AND no open interest AND closes
    within 60 minutes. Stale markets have meaningless edge calculations —
    skip them.
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


# Known weather series tickers, fetched directly via series_ticker= queries.
# A global open-market scan was removed: client.get_markets() does not expose
# the API cursor, making reliable pagination impossible. New Kalshi series
# should be added here. Module-level (not just local to get_weather_markets)
# so check_series_drift() can compare it against Kalshi's live series list.
KNOWN_WEATHER_SERIES = [
    "KXHIGHNY",
    "KXHIGHCHI",
    "KXHIGHLAX",  # was KXHIGHLA — Kalshi retired that ticker, 0 open markets
    "KXHIGHTBOS",  # was KXHIGHBOS — retired
    "KXHIGHMIA",
    "KXHIGHTDAL",
    "KXHIGHTPHX",
    "KXHIGHTSEA",
    "KXHIGHDEN",
    "KXHIGHTATL",
    "KXHIGHAUS",
    "KXHIGHTDC",
    "KXHIGHPHIL",  # was KXHIGHTPHIL — retired
    "KXHIGHTOKC",
    "KXHIGHTSFO",
    "KXHIGHTMIN",
    "KXHIGHTHOU",
    "KXHIGHTSATX",
    "KXHIGHTLV",  # Las Vegas — not previously tracked
    "KXHIGHTNOLA",  # New Orleans — not previously tracked
    "KXLOWTNYC",  # was KXLOWNY — retired
    "KXLOWTCHI",  # was KXLOWCHI — retired
    "KXLOWTLAX",  # was KXLOWLA, then KXLOWLAX — both retired; confirmed live 2026-07-05
    "KXLOWTBOS",  # was KXLOWBOS — retired
    "KXLOWTMIA",  # was KXLOWMIA — retired
    "KXLOWTDAL",
    "KXLOWTPHX",
    "KXLOWTSEA",
    "KXLOWTDEN",  # was KXLOWDEN — retired
    "KXLOWTATL",
    "KXLOWTAUS",  # was KXLOWAUS — retired
    "KXLOWTDC",
    "KXLOWTPHIL",
    "KXLOWTOKC",
    "KXLOWTSFO",
    "KXLOWTMIN",
    "KXLOWTHOU",
    "KXLOWTSATX",
    "KXLOWTLV",  # Las Vegas — not previously tracked
    "KXLOWTNOLA",  # New Orleans — not previously tracked
    "KXRAIN",
    "KXSNOW",
]

# Legacy/placeholder KXHIGH/KXLOW series Kalshi's /series endpoint still lists
# but which have zero open markets, ever (confirmed live 2026-07-05, re-verified
# 2026-07-08) — either retired ticker names already superseded above (e.g.
# KXLOWNY -> KXLOWTNYC) or series Kalshi lists but never activated. Suppressed
# here so check_series_drift() doesn't re-warn about the same dead entries
# every day forever; a real new/renamed series won't be in this set.
KNOWN_DEAD_WEATHER_SERIES = {
    "KXHIGHHOU",
    "KXHIGHNYD",
    "KXHIGHOU",
    "KXHIGHTEMPDEN",
    "KXHIGHUS",
    "KXLOWAUS",
    "KXLOWCHI",
    "KXLOWDEN",
    "KXLOWLAX",
    "KXLOWMIA",
    "KXLOWNY",
    "KXLOWNYC",
    "KXLOWPHIL",
}


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

    def _fetch_series(series: str) -> list[dict] | None:
        # None (not []) distinguishes "this series' API call failed" from "this
        # series genuinely has zero open markets right now" — the caller needs
        # that distinction to decide whether the aggregate result is degraded.
        try:
            return client.get_markets(series_ticker=series, status="open", limit=limit)
        except Exception as exc:
            _log.debug(
                "get_weather_markets: series %s fetch failed: %s: %s",
                series,
                type(exc).__name__,
                exc,
            )
            return None

    degraded = False
    _mkt_pool = ThreadPoolExecutor(max_workers=6)
    try:
        futures = {_mkt_pool.submit(_fetch_series, s): s for s in KNOWN_WEATHER_SERIES}
        try:
            for fut in as_completed(futures, timeout=40):
                try:
                    _series_markets = fut.result()
                    if _series_markets is None:
                        # _fetch_series already caught and logged its own
                        # exception — this call itself cannot raise, but a
                        # failed series must still mark the aggregate result
                        # as degraded so it isn't cached as if it were healthy.
                        degraded = True
                        continue
                    for m in _series_markets:
                        t = m.get("ticker")
                        # A market missing 'ticker' must not abort the rest of
                        # this series' batch — skip just that one record.
                        if t and t not in seen:
                            results.append(m)
                            seen.add(t)
                except Exception as exc:
                    degraded = True
                    _log.debug(
                        "get_weather_markets: a series batch was dropped: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
        except TimeoutError:
            degraded = True
            _log.warning(
                "get_weather_markets: Kalshi API timed out after 40s — using %d partial results",
                len(results),
            )
    finally:
        _mkt_pool.shutdown(wait=False)

    # Don't cache a degraded (timed-out or partially-failed) result — a
    # follow-up call within the same scan would otherwise silently see the
    # incomplete list for the full 60s TTL with no way to know it's degraded.
    # Leaving _MARKETS_CACHE untouched (rather than overwriting with a bad
    # result) means the next call just refetches fully.
    if not degraded:
        _MARKETS_CACHE = (results, now)
    return results


def check_series_drift(client: KalshiClient) -> None:
    """Once per day: compare KNOWN_WEATHER_SERIES against Kalshi's live
    Climate and Weather series list, and warn (never raise, never block
    trading) if either side has drifted from the other.

    This is the exact manual investigation that found KNOWN_WEATHER_SERIES
    had 10 renamed tickers and was missing 2 new cities (Las Vegas, New
    Orleans) — client.get_series_list() already existed for this but had
    zero production callers before this function.

    A ticker must be missing 3 consecutive days before it's warned about,
    to avoid a false alarm from a one-off API hiccup.
    """
    try:
        today = datetime.now(UTC).date().isoformat()
        missing_days: dict = {}
        if SERIES_DRIFT_PATH.exists():
            existing = json.loads(SERIES_DRIFT_PATH.read_text())
            if existing.get("date") == today:
                return  # already ran today
            missing_days = existing.get("missing_days", {})

        live = client.get_series_list(category="Climate and Weather")
        live_tickers = {s.get("ticker", "") for s in live}
        live_weather = {t for t in live_tickers if t.startswith(("KXHIGH", "KXLOW"))}

        # Only KXHIGH/KXLOW entries are checked against live_weather — KXRAIN/
        # KXSNOW are known-dead placeholders (confirmed 0 open markets, ever)
        # that never match the KXHIGH/KXLOW filter, so tracking them here
        # would produce a permanent, un-actionable "missing" warning forever.
        for ticker in KNOWN_WEATHER_SERIES:
            if not ticker.startswith(("KXHIGH", "KXLOW")):
                continue
            if ticker in live_weather:
                missing_days.pop(ticker, None)
            else:
                missing_days[ticker] = missing_days.get(ticker, 0) + 1
                if missing_days[ticker] >= 3:
                    _log.warning(
                        "check_series_drift: %s missing from Kalshi's live series "
                        "list for %d consecutive days — likely renamed/retired",
                        ticker,
                        missing_days[ticker],
                    )

        unknown = live_weather - set(KNOWN_WEATHER_SERIES) - KNOWN_DEAD_WEATHER_SERIES
        if unknown:
            _log.warning(
                "check_series_drift: live KXHIGH/KXLOW series not in "
                "KNOWN_WEATHER_SERIES: %s",
                sorted(unknown),
            )

        _safe_io.atomic_write_json(
            {"date": today, "missing_days": missing_days}, SERIES_DRIFT_PATH
        )
    except Exception as _exc:
        _log.debug("check_series_drift failed (non-fatal): %s", _exc)


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


def _parse_city_from_ticker(ticker: str, title: str = "") -> str | None:
    """
    R24: Single source of truth for city detection from a market ticker + title.
    Called by parse_city_date and enrich_with_forecast to avoid duplicate logic.
    Returns the canonical city name string, or None for unrecognised markets.
    """
    ticker_up = ticker.upper()
    title_lo = title.lower()
    if "NY" in ticker_up or "new york" in title_lo:
        return "NYC"
    if "CHI" in ticker_up or "chicago" in title_lo:
        return "Chicago"
    if (
        # L5-B: "LA" is a substring of DALLAS, PHILADELPHIA, ATLANTA — use
        # specific series-prefix patterns or an exact hyphen-delimited segment
        # instead of bare substring match. "LOWTLA" covers the KXLOWTLAX
        # ticker format (Kalshi added a "T" to the low-temp LA series after
        # KXLOWLAX was retired) alongside the older "LOWLA" pattern.
        "HIGHLA" in ticker_up
        or "LOWLA" in ticker_up
        or "LOWTLA" in ticker_up
        or any(seg == "LA" for seg in ticker_up.split("-"))
        or "los angeles" in title_lo
    ):
        return "LA"
    if "BOS" in ticker_up or "boston" in title_lo:
        return "Boston"
    if "MIA" in ticker_up or "miami" in title_lo:
        return "Miami"
    if "TDAL" in ticker_up or "dallas" in title_lo:
        return "Dallas"
    if "TPHX" in ticker_up or "phoenix" in title_lo:
        return "Phoenix"
    if "TSEA" in ticker_up or "seattle" in title_lo:
        return "Seattle"
    if "DEN" in ticker_up or "denver" in title_lo:
        return "Denver"
    if "TATL" in ticker_up or "atlanta" in title_lo:
        return "Atlanta"
    if "AUS" in ticker_up or "austin" in title_lo:
        return "Austin"
    if "TDC" in ticker_up or "washington" in title_lo:
        return "Washington"
    if "PHIL" in ticker_up or "philadelphia" in title_lo:
        # KXHIGHPHIL dropped the "T" that KXLOWTPHIL still has; "PHIL" alone
        # covers both (it's a superset match, so the old "TPHIL" check was dead).
        return "Philadelphia"
    if "TOKC" in ticker_up or "oklahoma" in title_lo:
        return "OklahomaCity"
    if "TSFO" in ticker_up or "san francisco" in title_lo:
        return "SanFrancisco"
    if "TMIN" in ticker_up or "minneapolis" in title_lo:
        return "Minneapolis"
    if "THOU" in ticker_up or "houston" in title_lo:
        return "Houston"
    if "TSATX" in ticker_up or "san antonio" in title_lo:
        return "SanAntonio"
    if "TLV" in ticker_up or "las vegas" in title_lo:
        return "LasVegas"
    if "NOLA" in ticker_up or "new orleans" in title_lo:
        return "NewOrleans"
    return None


def parse_city_date(market: dict) -> tuple[str | None, date | None]:
    """
    Extract (city, target_date) from a market dict without any network calls.
    Used for bulk collection of city/date pairs before batch pre-warming.
    Returns (None, None) for unrecognised markets.
    """
    ticker = market.get("ticker", "")
    title = market.get("title") or ""
    ticker_up = ticker.upper()

    city = _parse_city_from_ticker(ticker, title)

    target_date = None
    hourly_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(\d{2})", ticker_up)
    daily_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})(?!\d)", ticker_up)
    if hourly_match:
        yy, mon_str, dd, _ = hourly_match.groups()
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                target_date = date(2000 + int(yy), month, int(dd))
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

    return city, target_date


def enrich_with_forecast(market: dict, fetch_forecast: bool = True) -> dict:
    """
    Attach forecast data to a market dict.
    Parses city, date, and (for hourly markets) hour from the ticker.

    fetch_forecast: set False to skip the get_weather_forecast() call and only
    parse city/date/hour. Callers that score against archive/historical data
    (e.g. backtest.py, which computes probability from fetch_archive_temps()
    and never reads _forecast/_forecast_uncertain) don't need it — for a
    historical target_date, Open-Meteo's forecast endpoint, NBM, and
    weatherapi.com all miss, so the call falls all the way through to a slow
    (~5s+) Pirate Weather time-machine request whose result would just be
    discarded. _forecast/_forecast_uncertain are None when skipped.
    """
    ticker = market.get("ticker", "")
    title = market.get("title") or ""
    ticker_up = ticker.upper()

    # R24: city detection delegated to shared helper (eliminates duplication with
    # parse_city_date and keeps both functions in sync automatically).
    city = _parse_city_from_ticker(ticker, title)

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
    if city and target_date and fetch_forecast:
        forecast = get_weather_forecast(city, target_date)

    # Wire Pirate Weather uncertainty signals into _forecast_uncertain.
    # If the forecast came from Pirate Weather and includes a severe alert or
    # a stale model run (HRRR > 6h old), flag the enriched market so that
    # downstream analyze_trade can apply caution (higher sigma / lower edge).
    _forecast_uncertain = False
    if forecast and forecast.get("_source") == "pirate_weather":
        if forecast.get("_has_severe_alert"):
            _forecast_uncertain = True
        if forecast.get("_stale_forecast"):
            _forecast_uncertain = True

    import time as _time_enrich

    # P1-1: use the cache entry's original fetch time, not the current wall clock.
    # Converts the stored monotonic timestamp back to wall-clock via the age offset.
    _data_fetched_at = _time_enrich.time()
    if city and target_date:
        _cache_key = (city, target_date.isoformat())
        _cached_val, _hit, _cache_ts = _forecast_cache.get_with_ts(_cache_key)
        if _hit:
            _data_fetched_at = _cache_ts

    return {
        **market,
        "_city": city,
        "_date": target_date,
        "_hour": hour,
        "_forecast": forecast,
        "_forecast_uncertain": _forecast_uncertain,
        "data_fetched_at": _data_fetched_at,
    }


# ── Trade analysis ────────────────────────────────────────────────────────────


def _forecast_uncertainty(target_date: date) -> float:
    """
    Estimated standard deviation of forecast error in °F.
    Weather forecasts get less accurate further out.
    """
    days_out = (target_date - datetime.now(UTC).date()).days
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
      "MEDIUM" / 0.85 — closes within 36 hours (tomorrow's market)
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
        elif closes_today and local_hour >= 20:
            # "Weather station already read" is only true when the market's
            # target day is TODAY — without the closes_today guard, any market
            # whose close_time simply lands after 8pm local (regardless of
            # being 2, 3, or 4 days out) got this same reduced-uncertainty
            # multiplier, making the MEDIUM/HIGH tiers below unreachable for it.
            return ("LOW", 0.7)
        elif closes_today:
            return ("LOW", 0.8)
        elif hours_to_close <= 36:
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
      {"type": "between", "lower": 66.5, "upper": 68.5}  — B67.5 ticker (2°F wide)
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
        _log.warning(
            "_parse_market_condition[%s]: no T/B suffix match in ticker (title=%r)",
            ticker,
            title[:80],
        )
        return None

    kind, val_str = cond_match.group(1), cond_match.group(2)
    val = float(val_str)

    if kind == "B":
        # Bucket: B67.5 means range [66.5, 68.5] — Kalshi between-buckets are 2°F
        # wide, centered on val.  Adjacent tickers are 2°F apart (e.g. B64.5,
        # B66.5) and must tile without gaps, so the half-width is 1.0°F, not 0.5°F.
        return {"type": "between", "lower": val - 1.0, "upper": val + 1.0}
    else:
        # T: determine above or below from title.  "threshold" stays the raw
        # ticker value (literal Kalshi rule text, e.g. T86 -> 86.0) -- kept
        # unchanged for audit_settlement/METAR-lockout/DB bookkeeping, which
        # compare against Kalshi's literal rule ("greater than 86"). A second
        # key, "prob_threshold", is the continuous decision boundary for
        # probability math: live-verified 2026-07-17 against real
        # rules_primary text across 4 cities, a "T{val} above" ticker's rule
        # is "greater than {val}", i.e. integer settlement must be val+1 or
        # higher, so the boundary that tiles with the adjacent between-bucket
        # (which ends at val+0.5) is val+0.5, not val. Symmetric below:
        # val-0.5. See utils.prob_threshold's docstring for the full reasoning.
        if ">" in title or "above" in title or " be >" in title:
            return {"type": "above", "threshold": val, "prob_threshold": val + 0.5}
        elif "<" in title or "below" in title or " be <" in title:
            return {"type": "below", "threshold": val, "prob_threshold": val - 0.5}
        else:
            # Check subtitle/yes_sub_title — Kalshi puts the bucket text
            # ("53° or below") there when the title itself has been reworded
            # to something generic ("Highest temperature in NYC on Jan 5?").
            subtitle = (
                (market.get("subtitle") or "")
                + " "
                + (market.get("yes_sub_title") or "")
            ).lower()
            if ">" in subtitle or "above" in subtitle or " be >" in subtitle:
                return {"type": "above", "threshold": val, "prob_threshold": val + 0.5}
            elif "<" in subtitle or "below" in subtitle or " be <" in subtitle:
                return {"type": "below", "threshold": val, "prob_threshold": val - 0.5}
            # M-15's old series-ticker-prefix guess (KXHIGH -> "above", KXLOW ->
            # "below") is REMOVED: every daily temperature series has both a top
            # T-bucket and a bottom T-bucket, distinguishable only by
            # title/subtitle text, not by series name — guessing from the
            # series prefix silently inverted the condition for the bottom
            # bucket of a KXHIGH series (and the top bucket of a KXLOW series).
            # Fail closed (skip the market) rather than guess wrong.
            _log.warning(
                "_parse_market_condition[%s]: T-type but no direction keyword in "
                "title=%r or subtitle=%r (has_lt=%s has_gt=%s has_below=%s has_above=%s)",
                ticker,
                title[:80],
                subtitle[:80],
                "<" in title,
                ">" in title,
                "below" in title,
                "above" in title,
            )
            return None


def _forecast_probability(condition: dict, forecast_temp: float, sigma: float) -> float:
    """Estimate probability of the market condition given a forecast temperature."""
    if condition["type"] == "above":
        return 1.0 - normal_cdf(_prob_threshold(condition), forecast_temp, sigma)
    elif condition["type"] == "below":
        return normal_cdf(_prob_threshold(condition), forecast_temp, sigma)
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


def _nws_days_out_scale(
    w_ens: float, w_clim: float, w_nws: float, days_out: int
) -> tuple[float, float, float]:
    """Decay NWS weight at longer horizons; preserve calibrated weights at days_out=1.

    Scale factor: 1.0x at days_out=1 (no change — calibration data is at d=1),
    decaying 10% per day beyond that, floored at 0.6x. NWS capped at 0.85 to
    prevent over-concentration when calibrated nws weight is very high.
    """
    if w_nws == 0.0 or days_out <= 0:
        return w_ens, w_clim, w_nws
    scale = max(0.6, 1.0 - (days_out - 1) * 0.10)
    w_nws_new = min(w_nws * scale, 0.85)
    remaining = 1.0 - w_nws_new
    ec_total = w_ens + w_clim
    if ec_total > 0:
        w_ens_new = remaining * w_ens / ec_total
        w_clim_new = remaining * w_clim / ec_total
    else:
        w_ens_new = remaining
        w_clim_new = 0.0
    return w_ens_new, w_clim_new, w_nws_new


# Per-regime domain-knowledge blend weights (w_ens, w_clim, w_nws).
# Extreme regimes (heat_dome, cold_snap, blocking_high) shift weight toward ensemble
# because NWP ensembles outperform NWS MOS at extremes. Volatile shifts toward NWS.
# "normal" is intentionally absent — falls through to existing condition/seasonal logic.
_REGIME_BLEND_WEIGHTS: dict[str, tuple[float, float, float]] = {
    "heat_dome": (0.70, 0.05, 0.25),
    "cold_snap": (0.70, 0.05, 0.25),
    "blocking_high": (0.65, 0.05, 0.30),
    "volatile": (0.30, 0.10, 0.60),
}

# Mutable state dict so tests can reset between runs by setting ["active"] = None.
# None = unchecked this process, True/False = already determined.
_regime_blend_state: dict = {"active": None}


def _regime_blend_settled_count() -> int:
    """Thin wrapper so tests can monkeypatch the settled-trade count."""
    from tracker import count_settled_predictions_rolling

    return count_settled_predictions_rolling()


def _notify_feature_activation(key: str, message: str, extra: dict) -> None:
    """Write a one-time entry to feature_activations.json and log a WARNING.

    Idempotent — if the key already exists the file is not modified so
    the user can dismiss the alert without it reappearing on restart.
    """
    try:
        existing = (
            json.loads(_FEATURE_ACTIVATIONS_PATH.read_text())
            if _FEATURE_ACTIVATIONS_PATH.exists()
            else {}
        )
    except Exception:
        existing = {}

    if key in existing:
        return  # Already notified; do not overwrite (user may have dismissed it)

    existing[key] = {
        "activated_at": datetime.now(UTC).date().isoformat(),
        "message": message,
        "dismissed": False,
        **extra,
    }
    try:
        _safe_io.atomic_write_json(existing, _FEATURE_ACTIVATIONS_PATH)
    except Exception as exc:
        _log.warning(
            "_notify_feature_activation: could not write %s: %s",
            _FEATURE_ACTIVATIONS_PATH,
            exc,
        )

    _log.warning("AUTO-ACTIVATION: %s. Check the dashboard for details.", message)


def _regime_blend_active() -> bool:
    """Return True when enough settled trades warrant regime-specific blend weights.

    Checks once per process, then caches result in _regime_blend_state["active"].
    Writes a one-time user notification the first time the threshold is crossed.
    """
    if _regime_blend_state["active"] is not None:
        return _regime_blend_state["active"]

    n = _regime_blend_settled_count()
    active = n >= 30
    _regime_blend_state["active"] = active

    if active:
        _notify_feature_activation(
            "a9_regime_blend",
            f"Regime blend weights auto-activated ({n} multi-day settled trades reached)",
            {"n_settled": n},
        )
    return active


# ── PDO / PNA blend state ────────────────────────────────────────────────────
# Mutable state dict so tests can reset between runs by setting ["active"] = None.
# None = unchecked this process, True/False = already determined.
_pdopna_blend_state: dict = {"active": None}

# Minimum settled multi-day trades per west-coast city before PDO/PNA correction activates.
_PDOPNA_WEST_COAST_THRESHOLD = 20


def _pdopna_settled_counts() -> dict[str, int]:
    """Thin wrapper so tests can monkeypatch the west-coast settled-trade counts."""
    from tracker import count_settled_west_coast_multiday

    return count_settled_west_coast_multiday()


def _pdopna_blend_active() -> bool:
    """Return True when PDO/PNA correction is ready to apply.

    Requires BOTH: 20+ settled multi-day trades for each west-coast city (LA,
    SanFrancisco, Seattle) AND the pdo_pna.json index file is present. Checks
    once per process, then caches result in _pdopna_blend_state["active"].
    Writes a one-time user notification the first time the threshold is crossed.
    """
    if _pdopna_blend_state["active"] is not None:
        return _pdopna_blend_state["active"]

    counts = _pdopna_settled_counts()
    west_coast = ["LA", "SanFrancisco", "Seattle"]
    enough_data = all(
        counts.get(c, 0) >= _PDOPNA_WEST_COAST_THRESHOLD for c in west_coast
    )
    indices_available = _ci._PDO_PNA_PATH.exists()
    active = enough_data and indices_available
    _pdopna_blend_state["active"] = active

    if active:
        _notify_feature_activation(
            "a10_pdopna",
            f"PDO/PNA blend auto-activated ({_PDOPNA_WEST_COAST_THRESHOLD}+ west-coast settled trades + index file present)",
            {"counts": counts},
        )
    return active


def _blend_weights(
    days_out: int,
    has_nws: bool,
    has_clim: bool,
    city: str | None = None,
    season: str | None = None,
    condition_type: str | None = None,
    regime: str | None = None,
) -> tuple[float, float, float]:
    """Return (w_ensemble, w_climatology, w_nws).

    Priority: regime override (highest, when active) > city > condition-type > seasonal > schedule.
    Early return from the regime block means it wins over all other tiers when the feature
    is active and the regime is an extreme-weather pattern.
    """
    # 0. Regime override — highest priority when feature is active and regime is extreme.
    # Runs before city/condition/seasonal weights so extreme regimes always win.
    if regime and regime in _REGIME_BLEND_WEIGHTS and _regime_blend_active():
        w_ens, w_clim, w_nws = _REGIME_BLEND_WEIGHTS[regime]
        if not has_nws:
            w_ens += w_nws * 0.6
            w_clim += w_nws * 0.4
            w_nws = 0.0
        if not has_clim:
            w_ens += w_clim
            w_clim = 0.0
        total = w_ens + w_clim + w_nws
        if total > 0.0:
            w_ens, w_clim, w_nws = w_ens / total, w_clim / total, w_nws / total
        return _nws_days_out_scale(w_ens, w_clim, w_nws, days_out)

    # 1. City-specific calibration weights
    if city and city in _CITY_WEIGHTS and not _CITY_WEIGHTS[city].get("_uncalibrated"):
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
            w_ens, w_clim, w_nws = w_ens / total, w_clim / total, w_nws / total
            return _nws_days_out_scale(w_ens, w_clim, w_nws, days_out)
        # Degenerate calibration data; fall through to condition/seasonal/hardcoded

    # 2. Condition-type calibration weights
    _cond_cal = _CONDITION_WEIGHTS.get(condition_type) if condition_type else None
    if isinstance(_cond_cal, dict) and not _cond_cal.get("_uncalibrated"):
        w_ens = _cond_cal["ensemble"]
        w_clim = _cond_cal["climatology"]
        w_nws = _cond_cal["nws"]
        if not has_nws:
            w_ens += w_nws * 0.6
            w_clim += w_nws * 0.4
            w_nws = 0.0
        if not has_clim:
            w_ens += w_clim
            w_clim = 0.0
        total = w_ens + w_clim + w_nws
        if total > 0.0:
            w_ens, w_clim, w_nws = w_ens / total, w_clim / total, w_nws / total
            return _nws_days_out_scale(w_ens, w_clim, w_nws, days_out)
        # Degenerate calibration data; fall through to seasonal/hardcoded

    # 3. Seasonal calibration weights
    if (
        season
        and season in _SEASONAL_WEIGHTS
        and not _SEASONAL_WEIGHTS[season].get("_uncalibrated")
    ):
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
            w_ens, w_clim, w_nws = w_ens / total, w_clim / total, w_nws / total
            return _nws_days_out_scale(w_ens, w_clim, w_nws, days_out)
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
    condition_type: str | None = None,
    regime: str | None = None,
) -> tuple[float, float, float]:
    """#31: _blend_weights scaled by inverse ensemble variance."""
    w_ens, w_clim, w_nws = _blend_weights(
        days_out,
        has_nws,
        has_clim,
        city=city,
        season=season,
        condition_type=condition_type,
        regime=regime,
    )
    if ens_std is None or ens_std <= 0:
        return w_ens, w_clim, w_nws
    scale = max(0.5, min(1.5, _ENS_STD_REF / ens_std))
    # Clamp w_ens_scaled so it cannot exceed the available weight budget (w_ens stays ≤ 1.0)
    w_ens_scaled = min(w_ens * scale, 1.0)
    delta = w_ens - w_ens_scaled
    total_others = w_clim + w_nws
    if total_others > 0:
        w_clim_new = max(0.0, w_clim + delta * (w_clim / total_others))
        w_nws_new = max(0.0, w_nws + delta * (w_nws / total_others))
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
    # Check "trivially wide" against the RAW inputs, before clamping — clamping
    # (0.0, 1.0) to (0.01, 0.99) shrinks the width to 0.98, which would slip
    # past a >= 0.99 check performed after the clamp and let a genuinely
    # no-information (0, 1) posterior get integrated as if it were meaningful.
    if ci_high - ci_low >= 0.99:
        return 0.0  # no information — don't bet
    ci_low = max(0.01, ci_low)
    ci_high = min(0.99, ci_high)
    if ci_high <= ci_low:
        return kelly_fraction(ci_low, price, fee_rate)

    step = (ci_high - ci_low) / n_steps
    total = 0.0
    for i in range(n_steps + 1):
        p = ci_low + i * step
        total += kelly_fraction(p, price, fee_rate)
    return round(total / (n_steps + 1), 6)


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
            return sum(1 for t in sample if t > _prob_threshold(condition)) / len(
                sample
            )
        elif condition["type"] == "below":
            return sum(1 for t in sample if t < _prob_threshold(condition)) / len(
                sample
            )
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


_CONSENSUS_CACHE: dict[tuple, tuple] = {}
_CONSENSUS_CACHE_TTL = 4 * 60 * 60  # 4 hours
# Short TTL for a total-miss result (both models returned None — a transient
# blip, not a real "models agree" or "models disagree" answer). Caching that
# for the full 4h would freeze model_consensus's fail-open default (True) long
# after the underlying circuit breaker itself would have recovered, defeating
# the ICON-vs-GFS divergence safety gate for every market sharing that key.
_CONSENSUS_MISS_TTL = 120


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
    _cons_key = (
        city,
        target_date.isoformat(),
        condition.get("type"),
        condition.get("threshold"),
        # Include bucket bounds so distinct between-markets (e.g. B64.5 vs
        # B66.5 for the same city/date) don't share a cache slot.  Both are
        # None for above/below conditions, so those keys are unaffected.
        condition.get("lower"),
        condition.get("upper"),
        var,
        hour,
    )
    _cached = _CONSENSUS_CACHE.get(_cons_key)
    if _cached is not None:
        _result, _ts, _ttl = _cached
        if time.monotonic() - _ts < _ttl:
            return _result

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
            temps = _ensemble_cache.get(cache_key)

            if temps is None:
                if _ensemble_cb.is_open():
                    _log.debug(
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
                }
                try:
                    resp = _om_request(
                        "GET", ENSEMBLE_BASE, params=params, timeout=12
                    )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
                    if not resp:
                        return None, None
                    resp.raise_for_status()
                    data = resp.json()
                    daily = data.get("daily", {})
                    raw_member_values = [
                        v[0] for k, v in daily.items() if k.startswith(var_field) and v
                    ]
                    if is_all_null(raw_member_values):
                        raise ValueError(
                            f"model {model_name} returned all-null ensemble members (dead model?)"
                        )
                    _ensemble_cb.record_success()
                except Exception as _exc:
                    _ensemble_cb.record_failure()
                    _log.info(
                        "open_meteo_ensemble: failure #%d (consensus) — %s: %s",
                        _ensemble_cb.failure_count,
                        type(_exc).__name__,
                        _exc,
                    )
                    return None, None
                members = [
                    float(v[0])
                    for k, v in daily.items()
                    if k.startswith(var_field) and v and v[0] is not None
                ]
                temps = members
                # L5-A: align TTL to next NWS model cycle
                _consensus_cycle_ttl = _ttl_until_next_cycle()
                _ensemble_cache.set_with_ttl(cache_key, temps, _consensus_cycle_ttl)
                _save_ensemble_disk_entry(cache_key, temps, _consensus_cycle_ttl)

            if len(temps) < 5:
                return None, None

            mean_temp = round(sum(temps) / len(temps), 2)
            thresh = _prob_threshold(condition)
            ctype = condition.get("type", "")
            if ctype == "above" and thresh is not None:
                return sum(1 for t in temps if t > thresh) / len(temps), mean_temp
            elif ctype == "below" and thresh is not None:
                return sum(1 for t in temps if t < thresh) / len(temps), mean_temp
            elif ctype in ("between", "range"):
                lo = condition.get("lower", 0)
                hi = condition.get("upper", 999)
                return sum(1 for t in temps if lo <= t <= hi) / len(temps), mean_temp
            return None, mean_temp
        except Exception:
            return None, None

    icon_prob, icon_mean = _model_prob_and_mean("icon_seamless")
    gfs_prob, gfs_mean = _model_prob_and_mean("gfs_seamless")
    _cons_result = (icon_prob, gfs_prob, icon_mean, gfs_mean)
    _cons_ttl = (
        _CONSENSUS_CACHE_TTL
        if (icon_prob is not None or gfs_prob is not None)
        else _CONSENSUS_MISS_TTL
    )
    _CONSENSUS_CACHE[_cons_key] = (_cons_result, time.monotonic(), _cons_ttl)
    return _cons_result


def kelly_fraction(
    our_prob: float, price: float, fee_rate: float = KALSHI_FEE_RATE
) -> float:
    """
    Quarter-Kelly criterion for a binary prediction market.
    price    = cost per contract in dollars (e.g. 0.30 means you pay $0.30, win $0.70)
    fee_rate = fraction of winnings charged as fee (e.g. 0.07 for Kalshi's 7% fee)
    Returns recommended fraction of bankroll to bet (0–1).

    Kelly formula: f* = (b*p - q) / b  where b = net odds (win per $1 risked)
    For Kalshi: you pay `price`, win `(1-price)*(1-fee_rate)` net of fee.
    Net odds b = (1-price)*(1-fee_rate) / price
    Quarter-Kelly (full/4) matches calibrated competitors and reduces variance
    during the bias-correction phase while we accumulate settlement data.
    """
    if our_prob <= 0 or our_prob >= 1 or price <= 0 or price >= 1:
        return 0.0
    winnings = (1 - price) * (1 - fee_rate)  # net winnings per contract after fee
    b = winnings / price  # net odds: win $b for every $1 staked
    q = 1 - our_prob
    full_kelly = (b * our_prob - q) / b
    quarter_kelly = max(
        0.0, full_kelly / 4
    )  # quarter-Kelly: matches calibrated competitors, reduces downside during bias-correction phase
    return min(quarter_kelly, KELLY_CAP)


def _price_and_size(
    blended_prob: float,
    prices: dict,
    condition: dict,
    rec_side: str,
    *,
    ci: tuple[float, float],
    consensus: bool = False,
    extra_kelly_scales: tuple[float, ...] = (),
    time_decay: float = 1.0,
    yes_side_ask_fallback: bool = False,
) -> dict:
    """
    Shared entry-price / EV / Kelly tail for precip, snow, and temperature
    trade analysis (backlog.txt "ANALYZE-TRADE PRICING/EV/KELLY TAIL
    TRIPLICATED ACROSS TEMP/PRECIP/SNOW PATHS").

    `consensus` gates the ×1.25 ci_adjusted_kelly bonus and raises its cap
    from KELLY_CAP to KELLY_CAP * KELLY_CAP_CONSENSUS_MULT — pass the
    caller's own consensus signal (temperature's 3-source agreement, and
    precip's/snow's ensemble/climatology/blend agreement, are different
    computations that happen to share a name and both get the same
    multiply+cap-raise treatment here).
    `extra_kelly_scales` lets the temperature path fold in its
    quality/anomaly/spread/time/regime scales that precip and snow don't have.
    `yes_side_ask_fallback` restores temperature's original empty-ask-book
    fallback (entry_side_edge reference price falls back to market_prob when
    yes_ask==0 on a YES-side signal) — precip/snow never had this guard and
    must be called with the default False to preserve their exact behavior.
    """
    market_prob = prices["implied_prob"]
    # NO entry is at no_ask = 1 - yes_bid (what we pay to buy NO),
    # NOT no_bid = 1 - yes_ask (what market makers pay us to sell NO back).
    entry_price = (
        prices["yes_ask"]
        if rec_side == "yes"
        else (1.0 - prices["yes_bid"] if prices["yes_bid"] > 0 else 0.0)
    )
    if entry_price == 0:
        entry_price = 1 - market_prob if rec_side == "no" else market_prob

    payout = 1 - entry_price
    p_win = blended_prob if rec_side == "yes" else 1 - blended_prob
    # Maker fee (not taker): live/paper entries are always resting midpoint GTC
    # limit orders, which pay $0 on this bot's markets (see KALSHI_MAKER_FEE_RATE).
    net_ev = p_win * payout * (1 - KALSHI_MAKER_FEE_RATE) - (1 - p_win) * entry_price
    net_edge = min((net_ev / entry_price if entry_price > 0 else 0.0) * time_decay, 3.0)
    edge = (blended_prob - market_prob) * time_decay

    # entry_side_edge vs actual fill price (ask), not mid. NO-side fallback
    # (empty bid book): the cost of NO is 1 - market_prob, not market_prob.
    # YES-side fallback (empty ask book) only applies for the temperature
    # path (yes_side_ask_fallback=True) — precip/snow never had this guard,
    # preserved as-is; see backlog.txt divergence notes.
    _esmp_yes = prices["yes_ask"]
    if _esmp_yes <= 0 and yes_side_ask_fallback:
        _esmp_yes = market_prob
    _esmp = (
        _esmp_yes
        if rec_side == "yes"
        else (1.0 - prices["yes_bid"] if prices["yes_bid"] > 0 else 1.0 - market_prob)
    )
    if rec_side == "yes":
        entry_side_edge = (blended_prob - _esmp) * time_decay
    else:
        entry_side_edge = ((1.0 - blended_prob) - _esmp) * time_decay

    # Always pass fee_rate so Kelly is fee-adjusted; fee-free Kelly overstates size.
    fee_kel = kelly_fraction(p_win, entry_price, fee_rate=KALSHI_MAKER_FEE_RATE)

    # Bayesian Kelly — integrate over uniform posterior on CI range. For NO
    # bets, flip CI to P(NO wins) space so kelly_fraction uses the right side.
    ci_low, ci_high = ci
    if rec_side == "no":
        ci_adj_kelly = bayesian_kelly(
            1.0 - ci_high, 1.0 - ci_low, entry_price, fee_rate=KALSHI_MAKER_FEE_RATE
        )
    else:
        ci_adj_kelly = bayesian_kelly(
            ci_low, ci_high, entry_price, fee_rate=KALSHI_MAKER_FEE_RATE
        )
    # Discount Kelly proportionally to CI width (wider CI = more uncertainty)
    ci_scale = max(0.25, 1.0 - (ci_high - ci_low) * 2.0)
    ci_adj_kelly = ci_adj_kelly * ci_scale
    for _scale in extra_kelly_scales:
        ci_adj_kelly = ci_adj_kelly * _scale
    condition_type_scale = _CONDITION_CONFIDENCE.get(condition["type"], 1.0)
    ci_adj_kelly = ci_adj_kelly * condition_type_scale
    if consensus:
        ci_adj_kelly = ci_adj_kelly * 1.25
        cap = KELLY_CAP * KELLY_CAP_CONSENSUS_MULT
    else:
        cap = KELLY_CAP
    ci_adj_kelly = round(min(ci_adj_kelly, cap), 6)

    return {
        "market_prob": market_prob,
        "entry_price": entry_price,
        "payout": payout,
        "net_ev": net_ev,
        "net_edge": net_edge,
        "edge": edge,
        "entry_side_edge": entry_side_edge,
        "fee_kel": fee_kel,
        "ci_scale": ci_scale,
        "ci_adjusted_kelly": ci_adj_kelly,
    }


def time_decay_edge(
    raw_edge: float,
    close_time: datetime,
    reference_hours: float = 8.0,
) -> float:
    """
    #63: Scale edge linearly to zero as the market approaches close.

    At reference_hours or more before close: full edge returned.
    At close_time or past: 0.0 returned.

    hours_left = (close_time - now).total_seconds() / 3600
    decay      = min(1.0, hours_left / reference_hours)   clamped at [0, 1]
    returns    raw_edge * decay

    Changed from 48h to 8h (2026-04-18): METAR lock-in makes near-close signals
    more reliable — a genuine 30% edge at 2h before close should not be collapsed
    to ~1.3% (2/48). With 8h reference, 2h remaining retains 7.5% of the edge.
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
    _precip_cache_key = (lat, lon, target_date.isoformat())
    _cached_precip = _PRECIP_ENSEMBLE_CACHE.get(_precip_cache_key)
    if _cached_precip is not None:
        _vals, _ts = _cached_precip
        if time.monotonic() - _ts < _MODEL_CACHE_TTL:
            return _vals

    results = []
    target_str = target_date.isoformat()
    prefix = "precipitation_sum_member"
    date_in_range = False  # #35: track whether any model covered this date

    def _fetch_model(model: str) -> list[float]:
        nonlocal date_in_range
        if _ensemble_cb.is_open():
            _log.debug(
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
            resp = _om_request(
                "GET", ENSEMBLE_BASE, params=params, timeout=12
            )  # was 20 — Retry(1)×20=40s/call; 12 caps at 24.5s
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            times = daily.get("time", [])
            if target_str not in times:
                _ensemble_cb.record_success()
                return []
            idx = times.index(target_str)
            raw_member_values = [
                vals[idx]
                for k, vals in daily.items()
                if k.startswith(prefix) and idx < len(vals)
            ]
            if is_all_null(raw_member_values):
                raise ValueError(
                    f"model {model} returned all-null precip members for target date (dead model?)"
                )
            _ensemble_cb.record_success()
            date_in_range = True  # at least one model has this date
            return [v for v in raw_member_values if v is not None]
        except Exception as _exc:
            _ensemble_cb.record_failure()
            _log.info(
                "open_meteo_ensemble: failure #%d (model=%s) — %s: %s",
                _ensemble_cb.failure_count,
                model,
                type(_exc).__name__,
                _exc,
            )
            return []

    for model in ENSEMBLE_MODELS:
        results.extend(_fetch_model(model))

    # ECMWF weighted 3× in winter, 2× in summer (seasonal accuracy advantage)
    ecmwf_members = _fetch_model("ecmwf_ifs025")
    ecmwf_mult = 3 if target_date.month in (10, 11, 12, 1, 2, 3) else 2
    results.extend(ecmwf_members * ecmwf_mult)

    # #70: return None instead of [] when no members fetched (caller can distinguish)
    if not results and not date_in_range:
        return None  # type: ignore[return-value]  # date outside forecast range
    _PRECIP_ENSEMBLE_CACHE[_precip_cache_key] = (results, time.monotonic())
    return results


def _analyze_precip_trade(
    enriched: dict, forecast: dict, condition: dict, target_date: date, coords: tuple
) -> dict | None:
    """
    Probability analysis for precipitation markets (rain/snow).
    Uses ensemble precipitation members + climatological rain frequency.
    """
    lat, lon, tz = coords
    # Compare against the market's LOCAL calendar date, not UTC — from 00:00 UTC
    # until local midnight (a 4-8h window every evening for US cities),
    # datetime.now(UTC).date() is already local-tomorrow, which would silently
    # treat a tomorrow-local market as days_out=0 (triggering the same-day
    # live-observation override below on a day that hasn't started yet).
    from zoneinfo import ZoneInfo as _ZoneInfo

    local_today = datetime.now(_ZoneInfo(tz)).date()
    days_out = max(0, (target_date - local_today).days)

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

    # ── Climatological prior (computed early: used both in the blend below
    # and to bound the dry-forecast floor, since forecast.get("precip_in", 0.0)
    # can't distinguish a genuinely-reported-dry forecast from a missing-data
    # placeholder — get_weather_forecast's fallback paths all default the key
    # to 0.0 when no precip model actually returned data) ────────────────────
    city = enriched.get("_city", "")
    try:
        clim_prior = climatological_prob(city, coords, target_date, condition) or 0.30
    except Exception:
        clim_prior = 0.30

    # ── Forecast precip as fallback ───────────────────────────────────────────
    forecast_precip = forecast.get("precip_in", 0.0) or 0.0
    if ens_prob is None:
        # Only apply the dry-forecast floor for small thresholds (precip_any,
        # or any condition threshold close to it) — a Normal centered at ~0
        # puts roughly half its mass above a threshold that near, which would
        # price a bone-dry forecast (0.00 in) at ~48% instead of near-zero.
        # For materially larger thresholds (e.g. "more than 1 inch"), the
        # symmetric-Normal CDF below already gives a good near-zero estimate
        # (e.g. ~0.0003% at 1.0in) — flooring those to the same small-threshold
        # value would OVERSTATE them by orders of magnitude.
        _small_threshold = (
            condition["type"] == "precip_any" or condition.get("threshold", 0.0) <= 0.05
        )
        if forecast_precip <= 0.01 and _small_threshold:
            # forecast_precip==0.0 can mean "genuinely dry" or "no precip model
            # actually ran" (both collapse to the same placeholder upstream) —
            # bound the floor to a fraction of climatology rather than
            # asserting a fixed near-zero value we can't actually back with
            # real ensemble data either way.
            ens_prob = min(0.03, clim_prior * 0.2)
        else:
            # Normal distribution around forecast precip
            sigma = max(0.2, forecast_precip * 0.5)
            if condition["type"] == "precip_any":
                ens_prob = 1.0 - normal_cdf(0.01, forecast_precip, sigma)
            else:
                ens_prob = 1.0 - normal_cdf(
                    condition["threshold"], forecast_precip, sigma
                )

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
    blended_prob = ens_prob * w_ens + clim_prior * w_clim

    # Same-day override: a positive observation means precip has definitely
    # occurred today, so lock the probability toward 1.0. get_live_precip_obs
    # returns precipitationLastHour (or a 6h-average fallback) — a short-window
    # rate, not the day's cumulative total — so a zero/dry reading does NOT mean
    # the day will settle dry (rain may have already fallen earlier, or may
    # still fall later). Only the positive-observation side is safe to trust;
    # never push toward 0 from a dry last-hour reading.
    if obs_precip_val is not None:
        obs_threshold = (
            0.01
            if condition["type"] == "precip_any"
            else condition.get("threshold", 0.0)
        )
        if obs_precip_val > obs_threshold:
            blended_prob = 0.90 * 1.0 + 0.10 * blended_prob

    # ── Bias correction from tracker (same as temperature path) ──────────────
    bias = 0.0
    try:
        from tracker import get_quintile_bias

        city = enriched.get("_city")
        bias = get_quintile_bias(
            city, target_date.month, blended_prob, condition_type=condition["type"]
        )
        blended_prob = blended_prob - bias
    except Exception as _exc:
        _log.debug(
            "Bias correction skipped for %s: %s", enriched.get("ticker", "?"), _exc
        )

    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

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

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=precip_consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

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
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "time_risk": "HIGH",
        "consensus": precip_consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "city": city,  # needed by detect_hedge_opportunity's same-city+date match
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
        "entry_side_edge": round(entry_side_edge, 4),  # L8-A/L7-C: vs ask price
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
    # See _analyze_precip_trade's identical fix: compare against the market's
    # LOCAL calendar date, not UTC, to avoid treating a tomorrow-local market
    # as days_out=0 during the evening UTC-date-rollover window.
    from zoneinfo import ZoneInfo as _ZoneInfo

    local_today = datetime.now(_ZoneInfo(tz)).date()
    days_out = max(0, (target_date - local_today).days)

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
    _snow_default = 0.20 if is_winter_month else 0.05
    try:
        clim_prior = (
            climatological_prob(
                enriched.get("_city", ""), coords, target_date, condition
            )
            or _snow_default
        )
    except Exception:
        clim_prior = _snow_default

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

    # R23: wire bias correction for snow markets (same pattern as precip/temp paths)
    bias = 0.0
    try:
        from tracker import get_quintile_bias

        bias = get_quintile_bias(
            enriched.get("_city"),
            target_date.month,
            blended_prob,
            condition_type=condition["type"],
        )
        blended_prob = blended_prob - bias
    except Exception as _exc:
        _log.debug(
            "Snow bias correction skipped for %s: %s", enriched.get("ticker", "?"), _exc
        )

    blended_prob = max(0.01, min(0.99, blended_prob))

    prices = parse_market_price(enriched)
    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    ci_low, ci_high = blended_prob, blended_prob
    if len(precip_members) >= 5:
        # Match the ens_prob branching above: precip_members are liquid-equivalent,
        # so the bootstrap must compare against the same liquid_thresh, not the raw
        # snow-inches threshold — otherwise the CI is computed on the wrong units
        # (e.g. counting members > 2.0" liquid for a 2.0" *snow* threshold, which
        # at a typical 10:1 SLR is ~0.2" liquid, nearly never true) and comes back
        # falsely narrow/near-0 or near-1 regardless of the real probability.
        if threshold <= 0.0:
            ci_low, ci_high = _bootstrap_ci_precip(precip_members, condition)
        elif _slr == 0:
            # No snow accumulates above freezing — same as the ens_prob=0.01
            # special case above; there's no meaningful liquid threshold to
            # bootstrap against, so don't fabricate a falsely-narrow CI.
            ci_low, ci_high = 0.0, 1.0
        else:
            _liquid_condition = {
                **condition,
                "threshold": liquid_equiv_of_snow_threshold(threshold, _slr),
            }
            ci_low, ci_high = _bootstrap_ci_precip(precip_members, _liquid_condition)

    # ── Consensus signal for snow: ensemble and clim_prior agree with blend ──
    # Same formula as precip's precip_consensus (see _analyze_precip_trade).
    snow_consensus = (
        (
            (ens_prob > 0.5 and clim_prior > 0.5 and blended_prob > 0.5)
            or (ens_prob < 0.5 and clim_prior < 0.5 and blended_prob < 0.5)
        )
        if ens_prob is not None
        else False
    )

    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=snow_consensus,
    )
    net_edge = _priced["net_edge"]
    edge = _priced["edge"]
    entry_side_edge = _priced["entry_side_edge"]
    fee_kel = _priced["fee_kel"]
    ci_adj_kelly = _priced["ci_adjusted_kelly"]

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
        "bias_correction": bias,
        "blend_sources": {"ensemble": w_ens, "climatology": w_clim},
        "method": "snow_ensemble" if len(precip_members) >= 10 else "snow_clim",
        "ensemble_stats": None,
        "n_members": len(precip_members),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": round(ci_high - ci_low, 4),
        "kelly": fee_kel,
        "fee_adjusted_kelly": fee_kel,
        "ci_adjusted_kelly": ci_adj_kelly,
        "time_risk": "HIGH",
        "consensus": snow_consensus,
        "model_consensus": True,
        "near_threshold": False,
        "days_out": days_out,
        "city": enriched.get(
            "_city", ""
        ),  # needed by detect_hedge_opportunity's same-city+date match
        "target_date": target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date),
        "entry_side_edge": round(entry_side_edge, 4),  # L8-A/L7-C: vs ask price
    }


def _metar_lock_in(
    city: str,
    target_date: date,
    condition: dict,
    ticker: str = "?",
) -> tuple[bool, float, dict]:
    """
    Check METAR same-day lock-in for a temperature market.

    Fetches the latest METAR observation for the city's station and determines
    whether the current observed temperature is conclusive enough to skip the
    slow ensemble probability pipeline.  Only fires for today's markets after
    14:00 local time.

    Returns:
        (locked, blended_prob, lockout_details)

        locked        – True when the observation is conclusive.
        blended_prob  – Ready-to-use probability in [0.01, 0.99].
                        Meaningful only when locked=True.
        lockout_details – Raw dict from check_metar_lockout / bucket logic.
                          Empty dict when not applicable or on error.
    """
    try:
        import metar as _metar

        _metar_sta = _metar_station_for_city(city)
        _city_tz_str = _CITY_TZ.get(city, "America/New_York")
        try:
            from zoneinfo import ZoneInfo as _ZI

            _local_today = datetime.now(_ZI(_city_tz_str)).date()
        except Exception:
            _log.warning(
                "_metar_lock_in: ZoneInfo(%r) unavailable — falling back to UTC date",
                _city_tz_str,
            )
            _local_today = datetime.now(UTC).date()
        if not (_metar_sta and target_date == _local_today):
            return False, 0.0, {}

        _metar_obs = _metar.fetch_metar(_metar_sta)
        if not _metar_obs:
            return False, 0.0, {}

        _cond_type = condition.get("type")

        if _cond_type in ("above", "below") and condition.get("threshold") is not None:
            # Use the observed daily extreme rather than the instantaneous reading.
            # Current temp at 8 PM is not the day's low — the minimum typically
            # occurred at 6 AM. Key off ticker (KXLOW... vs KXHIGH...) because
            # _cond_type describes the bet direction, not whether it's a min/max market.
            _is_low_mkt = "LOW" in ticker.upper()
            if _is_low_mkt:
                _daily_ext = _metar_obs.get("min_temp_f")
            else:
                _daily_ext = _metar_obs.get("max_temp_f")
            _comp_temp = (
                _daily_ext if _daily_ext is not None else _metar_obs["current_temp_f"]
            )
            _lockout = _metar.check_metar_lockout(
                current_temp_f=_comp_temp,
                threshold_f=float(condition["threshold"]),
                direction=_cond_type,
                obs_time=_metar_obs["obs_time"],
                city_tz=_CITY_TZ.get(city, "America/New_York"),
            )
            if _is_low_mkt and _lockout.get("locked"):
                # A running daily-min-so-far can only DECREASE as the day
                # progresses (radiational cooling / cold fronts routinely set
                # a new low well after the 2pm gate check_metar_lockout uses).
                # "min already fell below threshold - margin" is monotone-safe
                # (it can only stay there or go lower); "min has stayed above
                # threshold + margin" is NOT safe — evening cooling can still
                # reverse it. Reject the unsafe direction regardless of which
                # branch check_metar_lockout took to reach "locked".
                _margin = 3.0  # matches check_metar_lockout's own default
                if _comp_temp > float(condition["threshold"]) - _margin:
                    _lockout = {
                        "locked": False,
                        "outcome": None,
                        "confidence": 0.0,
                        "reason": (
                            f"LOW market: running min {_comp_temp:.1f}F not yet "
                            "confirmed below threshold-margin — day not over"
                        ),
                    }

        elif _cond_type == "between":
            # Between lock-in is DELIBERATELY disabled — not a stale TODO. This
            # permanently skips analyze_trade's between-bucket gate (which
            # requires metar_locked=True to trade any between market at all),
            # fail-closed and by design: no money is lost, but it silently
            # retires the entire between-bucket market class (Kalshi's most
            # numerous temperature-market type) until real design+test work
            # goes into a between-market lock-in scheme (check_metar_lockout
            # only supports "above"/"below" directions; a correct between
            # implementation needs its own confidence/margin/clearance logic,
            # not a quick reuse of the above/below branch). See analyze_trade's
            # "between_no_metar" gate counter, now logged at info level so this
            # retirement stays visible rather than silent.
            return False, 0.0, {}

        else:
            _lockout = {"locked": False}

        # Always surface the observed temp so callers don't need the raw obs object.
        _lockout.setdefault("current_temp_f", _metar_obs["current_temp_f"])

        if _lockout.get("locked"):
            _metar_p = (
                _lockout["confidence"]
                if _lockout["outcome"] == "yes"
                else (1.0 - _lockout["confidence"])
            )
            _log.info(
                "METAR lock-in %s: %s (conf=%.0f%%) — %s",
                ticker,
                _lockout["outcome"],
                _lockout["confidence"] * 100,
                _lockout["reason"],
            )
            return True, max(0.01, min(0.99, _metar_p)), _lockout

        return False, 0.0, _lockout

    except Exception as _metar_exc:
        _log.debug("METAR lock-in check failed for %s: %s", ticker, _metar_exc)
        return False, 0.0, {}


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
    if not isinstance(enriched, dict):
        raise ValueError(
            f"analyze_trade: enriched must be a dict, got {type(enriched)}"
        )
    forecast = enriched.get("_forecast")
    target_date = enriched.get("_date")
    city = enriched.get("_city")
    hour = enriched.get("_hour")

    _tkr = enriched.get("ticker", "?")
    # Initialize early so blend weight calls can read regime even before detection runs.
    # Overwritten by the actual regime detection block further below.
    _regime_info: dict = {}
    if not forecast:
        _log.warning(
            "analyze_trade[%s]: gate=no_forecast city=%s date=%s",
            _tkr,
            city,
            target_date,
        )
        _count_gate("no_forecast")
        return None  # no forecast data available for this market
    if not target_date:
        _log.warning("analyze_trade[%s]: gate=no_date city=%s", _tkr, city)
        _count_gate("no_date")
        return None  # could not parse target date from ticker
    if not city:
        _log.warning("analyze_trade[%s]: gate=no_city date=%s", _tkr, target_date)
        _count_gate("no_city")
        return None  # unrecognized city in ticker
    if target_date < datetime.now(UTC).date():
        _log.debug(
            "analyze_trade[%s]: gate=past_date target=%s today=%s",
            _tkr,
            target_date,
            datetime.now(UTC).date(),
        )
        _count_gate("past_date")
        return None  # market target date already passed — Kalshi hasn't settled yet but no edge

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
            _count_gate("stale_data")
            return None

    condition = _parse_market_condition(enriched)
    if not condition:
        _log.warning(
            "analyze_trade[%s]: gate=condition_parse_failed title=%r ticker=%s",
            _tkr,
            enriched.get("title", "")[:80],
            _tkr,
        )
        _count_gate("condition_parse")
        return None

    coords = CITY_COORDS.get(city)
    if not coords:
        _log.warning("analyze_trade[%s]: gate=no_coords city=%s", _tkr, city)
        _count_gate("no_coords")
        return None

    # ── Days-out gate: only trade markets expiring within MAX_DAYS_OUT days ──
    _days_out_check = max(0, (target_date - datetime.now(UTC).date()).days)
    if _days_out_check > MAX_DAYS_OUT:
        _log.debug(
            "analyze_trade[%s]: gate=days_out days=%d max=%d",
            _tkr,
            _days_out_check,
            MAX_DAYS_OUT,
        )
        _count_gate("days_out")
        return None

    # ── Liquidity gate: skip markets with no real open interest ──────────────
    # Accept both legacy (volume/open_interest) and current API names (volume_fp/open_interest_fp)
    _vol = float(enriched.get("volume_fp") or enriched.get("volume") or 0) + float(
        enriched.get("open_interest_fp") or enriched.get("open_interest") or 0
    )
    if _vol < MIN_LIQUIDITY:
        _log.debug(
            "analyze_trade[%s]: gate=liquidity vol=%.0f oi=%.0f combined=%.0f min=%d "
            "(volume_fp=%s volume=%s oi_fp=%s oi=%s)",
            _tkr,
            float(enriched.get("volume_fp") or enriched.get("volume") or 0),
            float(
                enriched.get("open_interest_fp") or enriched.get("open_interest") or 0
            ),
            _vol,
            MIN_LIQUIDITY,
            enriched.get("volume_fp"),
            enriched.get("volume"),
            enriched.get("open_interest_fp"),
            enriched.get("open_interest"),
        )
        _count_gate("liquidity")
        return None

    # ── Volume gate: price is unreliable when trade count is tiny ────────────
    _raw_vol = float(enriched.get("volume_fp") or enriched.get("volume") or 0)
    if _raw_vol < MIN_SIGNAL_VOLUME:
        _log.debug(
            "analyze_trade[%s]: gate=min_signal_volume raw_vol=%.0f min=%d",
            _tkr,
            _raw_vol,
            MIN_SIGNAL_VOLUME,
        )
        _count_gate("min_volume")
        return None

    # ── Spread gate: skip illiquid markets with wide bid-ask spreads ─────────
    _prices = parse_market_price(enriched)
    # Skip markets where both bid and ask are zero (no real quote).
    # R28: default False — a missing has_quote key means no real quote, not a valid one.
    if not _prices.get("has_quote", False):
        _log.debug(
            "analyze_trade[%s]: gate=no_quote bid=%.3f ask=%.3f",
            _tkr,
            _prices.get("yes_bid", 0),
            _prices.get("yes_ask", 0),
        )
        _count_gate("no_quote")
        return None
    # Market divergence gate: when the market is highly confident (>70%) and
    # our model strongly disagrees (<25%), the market almost certainly has
    # information we don't (same-day obs, late-breaking data). Skip to avoid
    # systematically betting against a well-informed crowd.
    _mkt_p = _prices.get("implied_prob", 0.5)
    if _mkt_p > 0.70 or _mkt_p < 0.30:
        # We'll check our blended_prob later — store market_prob for gate
        # (gate is applied after blended_prob is computed, below)
        pass
    _divergence_gate_market_prob = _mkt_p
    _yes_ask = _prices.get("yes_ask", 0) or 0
    _yes_bid = _prices.get("yes_bid", 0) or 0
    if _yes_ask > 0 and _yes_bid > 0:
        _mid = (_yes_ask + _yes_bid) / 2
        if _mid > 0 and (_yes_ask - _yes_bid) / _mid > 0.30:
            _log.debug(
                "analyze_trade[%s]: gate=spread bid=%.3f ask=%.3f spread_pct=%.1f%%",
                _tkr,
                _yes_bid,
                _yes_ask,
                (_yes_ask - _yes_bid) / _mid * 100,
            )
            _count_gate("spread")
            return None  # spread > 30% of mid — not tradeable

    # ── Extreme-price gate: skip near-certain markets ────────────────────────
    # When yes_ask < MIN_MARKET_PRICE the market prices the outcome as near-
    # impossible.  Our blended model almost certainly lacks whatever information
    # (live obs, settlement status, crowd wisdom) drove the price that low.
    # Dividing net_ev by a tiny entry_price also inflates edge_pct by 100-200×,
    # producing spurious "2900% edge" signals.  Same logic in reverse above 0.95.
    if _yes_ask > 0 and (
        _yes_ask < MIN_MARKET_PRICE or _yes_ask > 1 - MIN_MARKET_PRICE
    ):
        _log.debug(
            "analyze_trade[%s]: gate=extreme_price yes_ask=%.3f gate=%.2f",
            _tkr,
            _yes_ask,
            MIN_MARKET_PRICE,
        )
        _count_gate("extreme_price")
        return None

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
    metar_locked, _metar_blended_prob, metar_lockout = _metar_lock_in(
        city, target_date, condition, ticker=enriched.get("ticker", "?")
    )

    # ── Between-bucket gate ───────────────────────────────────────────────────
    # Between markets (B86.5 = ±1°F band) are only tradeable when two conditions
    # are met:
    #   1. METAR lock-in fired — without it, our ensemble sigma (3–5.5°F) assigns
    #      probabilities well below market-maker METAR pricing, so no edge is
    #      recoverable regardless of drift.
    #   2. For YES bets: the observed temp is ≥1.5°F inside the band.  Kalshi's
    #      official settlement station is typically 1–3°F away from our METAR
    #      station; a reading near the band edge can be flipped by that gap.
    #      NO bets already require >3°F clearance (enforced in _metar_lock_in),
    #      so they are inherently safe from station-gap reversals.
    if condition.get("type") == "between":
        if not metar_locked:
            # Between lock-in is unconditionally disabled in _metar_lock_in (see
            # its docstring/comment there) — this branch therefore fires for
            # EVERY between market, permanently. Logged at info (not debug) so
            # this whole retired market class stays visible rather than silent.
            _log.info(
                "analyze_trade: skipping %s — between market, no METAR lock-in "
                "(ensemble sigma too wide for 2°F band; between lock-in is "
                "deliberately disabled pending dedicated design work)",
                enriched.get("ticker", "?"),
            )
            _count_gate("between_no_metar")
            return None
        if metar_lockout.get("outcome") == "yes":
            _lo = float(condition.get("lower", 0.0))
            _hi = float(condition.get("upper", 0.0))
            _ct = float(metar_lockout.get("current_temp_f", 0.0))
            _yes_clearance = min(_ct - _lo, _hi - _ct)
            if _yes_clearance < 1.5:
                _log.debug(
                    "analyze_trade: skipping %s — between market YES, clearance "
                    "%.1f°F < 1.5°F station-gap buffer (METAR %.1f°F in [%.1f, %.1f])",
                    enriched.get("ticker", "?"),
                    _yes_clearance,
                    _ct,
                    _lo,
                    _hi,
                )
                _count_gate("between_edge")
                return None

    if metar_locked:
        blended_prob = _metar_blended_prob

    # Initialize here so the return dict can reference it regardless of which path runs.
    disagree_f = None

    if not metar_locked:
        series = (enriched.get("series_ticker") or enriched.get("ticker", "")).upper()
        var = "min" if "LOW" in series else "max"
        condition["var"] = var

        forecast_temp = forecast["low_f"] if var == "min" else forecast["high_f"]
        if forecast_temp is None:
            _count_gate("no_temp")
            return None

        # ── Model-spread gate: suppress when multi-model spread is too wide ───
        # Check low_range for LOW markets (var=="min"), high_range otherwise
        _spread_range_key = "low_range" if var == "min" else "high_range"
        _spread_range = forecast.get(_spread_range_key)
        if _spread_range and len(_spread_range) == 2:
            _spread_f = _spread_range[1] - _spread_range[0]
            if _spread_f > MAX_MODEL_SPREAD_F:
                _log.debug(
                    "Skipping %s — model spread %.1f°F exceeds MAX_MODEL_SPREAD_F %.1f°F",
                    enriched.get("ticker", "?"),
                    _spread_f,
                    MAX_MODEL_SPREAD_F,
                )
                _count_gate("model_spread")
                return None

        # Apply per-city bias correction before probability calculation (B4: pass var).
        # _get_combined_station_bias() blends the static hand-coded table with a
        # dynamic correction learned from real METAR observations — the dynamic weight
        # grows as sample count increases (10 samples: 20%, 50+ samples: 100%).
        forecast_temp_raw = forecast_temp
        forecast_temp = forecast_temp - _get_combined_station_bias(city, var=var)

        # A6: dew point coastal correction — on humid days airport stations read
        # cooler than model forecasts due to sea breeze / evaporative cooling.
        # Only applies to _DEW_POINT_SENSITIVE_CITIES and only when dew_point_f is
        # available from a fresh METAR observation; skipped silently otherwise.
        _dp_station = _metar_station_for_city(city)
        if _dp_station and city in _DEW_POINT_SENSITIVE_CITIES:
            _dp_obs = _metar.fetch_metar(_dp_station)
            if _dp_obs and _dp_obs.get("dew_point_f") is not None:
                _dp_correction = _dew_point_temp_correction(
                    city, _dp_obs["dew_point_f"], forecast_temp
                )
                if _dp_correction != 0.0:
                    _log.debug(
                        "dew point correction for %s: %.2f°F (dew=%.1f forecast=%.1f)",
                        city,
                        _dp_correction,
                        _dp_obs["dew_point_f"],
                        forecast_temp,
                    )
                    forecast_temp += _dp_correction

        # ── PDO/PNA second-order correction (dormant until threshold met) ────────
        # Applies only for cities in the PDO or PNA coefficient tables once both
        # 20+ settled multi-day trades per west-coast city AND pdo_pna.json exist.
        if _pdopna_blend_active():
            from climate_indices import apply_pdo_pna_correction

            _pdopna_adj = apply_pdo_pna_correction(
                city, forecast_temp, target_date.month
            )
            if _pdopna_adj != 0.0:
                _log.debug(
                    "PDO/PNA correction for %s: %.2f°F (month=%d)",
                    city,
                    _pdopna_adj,
                    target_date.month,
                )
                forecast_temp += _pdopna_adj

        days_out = max(0, (target_date - datetime.now(UTC).date()).days)

    if not metar_locked:
        # ── 1. Ensemble probability ──────────────────────────────────────────────
        temps = get_ensemble_temps(city, target_date, hour=hour, var=var)

        # For hourly markets, use ensemble mean of the hourly temps as forecast_temp
        # (daily high is misleading for e.g. "temp at 9am" markets)
        if hour is not None and len(temps) >= 5:
            forecast_temp = statistics.mean(temps)
        elif hour is not None:
            # Degraded ensemble (circuit open / partial response) for an hourly
            # market: forecast_temp is still the DAILY extreme from the earlier
            # daily-forecast path, which structurally differs from an hourly
            # value by 10-20°F. Evaluating the hourly threshold against it
            # (both the raw-fraction blend below and the Gaussian source)
            # would manufacture a large phantom edge on exactly the days the
            # bot should be most conservative. Skip rather than guess.
            _log.debug(
                "analyze_trade: skipping %s — hourly market with only %d ensemble "
                "members (need >=5), daily-extreme forecast_temp is not a valid "
                "substitute for an hourly value",
                enriched.get("ticker", "?"),
                len(temps),
            )
            _count_gate("hourly_thin_ensemble")
            return None
        ens_stats = ensemble_stats(temps) if len(temps) >= 10 else None
        if ens_stats and ens_stats.get("degenerate"):
            _log.warning(
                "analyze_trade: skipping %s — degenerate ensemble (all %d members identical)",
                enriched.get("ticker", "?"),
                ens_stats["n"],
            )
            _count_gate("degenerate_ens")
            return None
        # NWS vs ensemble disagreement — only valid for daily high/low markets where
        # forecast_temp_raw (NWS daily high) and ens_stats["mean"] (ensemble daily high) are
        # the same quantity; hourly markets compare NWS daily high vs hourly ensemble mean,
        # which structurally differ by 15-20°F and would always fire the flag spuriously.
        if ens_stats is not None and hour is None:
            disagree_f = round(abs(forecast_temp_raw - ens_stats["mean"]), 1)

        method = "normal_dist"
        ens_prob: float | None = None
        gauss_prob: float | None = None  # Gaussian as separate named source

        if len(temps) >= 10:
            method = "ensemble"
            # EMOS path: use fitted Gaussian distribution if params are available.
            # Falls back to raw exceedance fraction when EMOS not yet trained.
            # CRITICAL: pass ens_var = std**2 (must square std, NOT pass std directly).
            from ml_bias import (
                _load_emos_params,
                emos_exceedance_prob,
                emos_interval_prob,
            )

            _emos_params = _load_emos_params()
            _use_emos = (
                _emos_params is not None
                and ens_stats is not None
                and ens_stats.get("std") is not None
            )
            if _use_emos:
                assert _emos_params is not None  # guaranteed by _use_emos check above
                assert ens_stats is not None  # guaranteed by _use_emos check above
                _ens_var_live = ens_stats["std"] ** 2  # variance, not std
                if condition["type"] == "above":
                    ens_prob = emos_exceedance_prob(
                        _emos_params,
                        ens_stats["mean"],
                        _ens_var_live,
                        _prob_threshold(condition),
                    )
                elif condition["type"] == "below":
                    ens_prob = 1.0 - emos_exceedance_prob(
                        _emos_params,
                        ens_stats["mean"],
                        _ens_var_live,
                        _prob_threshold(condition),
                    )
                else:
                    lo, hi = condition["lower"], condition["upper"]
                    ens_prob = emos_interval_prob(
                        _emos_params, ens_stats["mean"], _ens_var_live, lo, hi
                    )
                method = "emos"
            else:
                # Fallback: raw exceedance fraction
                if condition["type"] == "above":
                    ens_prob = sum(
                        1 for t in temps if t > _prob_threshold(condition)
                    ) / len(temps)
                elif condition["type"] == "below":
                    ens_prob = sum(
                        1 for t in temps if t < _prob_threshold(condition)
                    ) / len(temps)
                else:
                    lo, hi = condition["lower"], condition["upper"]
                    ens_prob = sum(1 for t in temps if lo <= t <= hi) / len(temps)
        else:
            # Prefer ens_stats["std"] when available — actual model disagreement
            # is more informative than the generic days-out lookup table.
            _ens_std = ens_stats.get("std") if ens_stats else None
            _raw_sigma = (
                _ens_std
                if _ens_std and _ens_std > 0
                else _forecast_uncertainty(target_date)
            )
            # Cap raw sigma before applying sigma_mult so the time-of-day
            # reduction from _time_risk() still applies proportionally.
            # "between" markets use a tighter cap — their 2°F bracket width means
            # larger sigma collapses probability (σ=3 → max 26.6%; σ=1.8 → max 44.3%).
            # above/below markets use the looser cap since sigma affects the tail
            # probability differently for direction bets.
            _is_between = condition.get("type") == "between"
            _prob_sigma_cap = (
                (_BETWEEN_SIGMA_1DAY_CAP if _is_between else _SIGMA_1DAY_CAP)
                if days_out <= 1
                else (_BETWEEN_SIGMA_2DAY_CAP if _is_between else _SIGMA_2DAY_CAP)
                if days_out <= 2
                else _raw_sigma
            )
            if _raw_sigma > _prob_sigma_cap:
                _log.debug(
                    "analyze_trade: capping ensemble sigma %.2f→%.2f "
                    "(city=%s days_out=%d)",
                    _raw_sigma,
                    _prob_sigma_cap,
                    city,
                    days_out,
                )
            sigma = min(_raw_sigma, _prob_sigma_cap) * sigma_mult
            # Below markets: ensemble members share physics so their spread underestimates
            # true forecast error — empirical MAE is ~2x the ensemble std.  Widen sigma
            # so extreme outputs (0%/99%) are suppressed before the blend.
            if condition.get("type") == "below":
                sigma *= 1.5
            ens_prob = _forecast_probability(condition, forecast_temp, sigma)
            if condition.get("type") == "between":
                _log.info(
                    "analyze_trade between sigma: raw=%.2f cap=%.2f "
                    "final=%.2f → ens_prob=%.3f forecast=%.1f bracket=[%.1f,%.1f] (city=%s)",
                    _raw_sigma,
                    _prob_sigma_cap,
                    sigma,
                    ens_prob,
                    forecast_temp,
                    condition.get("lower", 0.0),
                    condition.get("upper", 0.0),
                    city,
                )

        # ── Phase C: extended ensemble members (NBM + ECMWF AIFS) ───────────────
        model_temps: dict[str, float | None] = {}
        try:
            # H-13: pass var so LOW markets get daily min, not max
            model_temps["nbm"] = fetch_temperature_nbm(city, target_date, var=var)
            model_temps["ecmwf"] = fetch_temperature_ecmwf(city, target_date, var=var)
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
        # Apply sigma_mult (time-of-day horizon discount) so near-term
        # markets get tighter Gaussian uncertainty — same discount applied to
        # the ensemble sigma at line 3401.
        sigma_gauss = get_historical_sigma(city, target_month, var=var) * sigma_mult
        cond_type = condition.get("type", "above")
        if cond_type in ("above", "below"):
            p_win_gaussian = gaussian_probability(
                forecast_mean=forecast_temp,
                threshold=_prob_threshold(condition),
                sigma=sigma_gauss,
                direction=cond_type,
            )
        elif cond_type == "between":
            # "between" markets also get a Gaussian estimate.
            # P(lower ≤ T ≤ upper) = CDF(upper; mean, σ) − CDF(lower; mean, σ).
            # Previously p_win_gaussian was always None here, so the blend had no
            # smoothing for range markets — just noisy ensemble member counting.
            p_win_gaussian = _forecast_probability(
                condition, forecast_temp, sigma_gauss
            )
        else:
            p_win_gaussian = None

        # Blend Gaussian with ensemble fraction (fall back to ens_prob if temps available)
        # D1 hardcoded prior (ECMWF 2× NBM). Note: _dynamic_model_weights() is NOT
        # applicable here — it derives MAE from tracker's ensemble_member_scores,
        # which only ever logs "icon_seamless"/"gfs_seamless"/"blended" (see
        # paper._score_ensemble_members), never the "nbm" (best_match) / "ecmwf"
        # (ecmwf_ifs025) models used in model_temps above. A prior version looked
        # up _dynamic_model_weights() here anyway; since its keys never match
        # "nbm"/"ecmwf", every lookup silently fell through to a flat 1.0 default
        # for both, quietly discarding this D1 prior whenever tracker had any data.
        _active_weights: dict[str, float] = {"nbm": 1.0, "ecmwf": 2.0}
        _weighted_valid = sum(
            _active_weights.get(m, 1.0) for m, t in model_temps.items() if t is not None
        )
        n_valid = len([t for t in model_temps.values() if t is not None])
        _prob_thresh_val = _prob_threshold(condition)
        raw_fraction = sum(
            _active_weights.get(m, 1.0)
            for m, t in model_temps.items()
            if t is not None
            and (
                t > _prob_thresh_val
                if condition.get("type") == "above"
                else t < _prob_thresh_val
            )
        ) / max(1.0, _weighted_valid)

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
            # Keep ens_prob as the raw member-count fraction; expose
            # Gaussian as a separate named source so blend_sources labels it
            # correctly.  The final blend still allocates 30% of the ensemble
            # slot to Gaussian (same numeric result), but the accounting is
            # now honest: blend_sources shows "gaussian: X%" independently.
            gauss_prob = gaussian_blend
        elif cond_type == "between" and p_win_gaussian is not None:
            # Use Gaussian directly for "between" conditions.  raw_fraction
            # is too coarse here — with only 2-3 models each is either inside or
            # outside the 2°F bucket, giving steps of 0 / 0.5 / 1.0.  The Gaussian
            # CDF difference gives a continuous, calibrated estimate instead.
            gauss_prob = p_win_gaussian

        # ── Model consensus check ────────────────────────────────────────────────
        model_consensus = True
        icon_forecast_mean: float | None = None
        gfs_forecast_mean: float | None = None
        if ens_prob is not None and len(temps) >= 2:
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
        threshold_val = _prob_threshold(condition)
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
                if "prob_threshold" in condition:
                    adj_condition["prob_threshold"] = (
                        condition["prob_threshold"] - index_adj
                    )
            elif condition["type"] == "between":
                adj_condition["lower"] = condition["lower"] - index_adj
                adj_condition["upper"] = condition["upper"] - index_adj
            clim_prob = climatological_prob(city, coords, target_date, adj_condition)
            if clim_prob is None:
                clim_prob = clim_prob_raw

        # ── 5. Live observation override (same-day markets) ──────────────────────
        live_obs: dict | None = None
        obs_override: float | None = None
        # Skip obs for "between" markets — current temperature tells us where the
        # reading is NOW, not where the daily high will peak; even a 2°F band is
        # too narrow for an intra-day obs to be reliable.  Without this guard the
        # obs gets 85-90% blend weight after 2 PM and produces wildly miscalibrated
        # probabilities (Brier 0.40 observed in 29 settled "between" predictions).
        if days_out == 0 and condition.get("type") != "between":
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
                # For HIGH markets at days_out=0 the instantaneous current temp
                # is misleading after noon (the high has already occurred and is higher).
                # Prefer today's observed max when the observation includes it.
                if var == "max" and days_out == 0 and _live:
                    _live_temp = (
                        _live.get("max_temp_f")
                        or _live.get("high_f")
                        or _live.get("temp_f")
                    )
                else:
                    _live_temp = _live.get("temp_f") if _live else None
                # Persistence ("today's observation persists into the target
                # day") only means something when a REAL observation exists.
                # The old fallback to forecast_temp_raw when no observation was
                # available (always true at days_out==2, since _live is never
                # even fetched there; also whenever get_live_observation fails
                # or lacks a temp field) just re-blended the raw NWS forecast a
                # second time at a fixed 15% weight — and did so using the
                # UNCORRECTED forecast, bypassing the station-bias correction
                # applied to forecast_temp/blended_prob elsewhere in the
                # pipeline, re-injecting exactly the bias that correction exists
                # to remove.
                if _live_temp is None:
                    persistence_p = None
                else:
                    _current_temp: float = float(_live_temp)
                    _tlo = condition.get(
                        "prob_threshold",
                        condition.get(
                            "threshold", condition.get("lower", forecast_temp)
                        ),
                    )
                    _thi = condition.get("upper")
                    persistence_p = _persistence_prob(
                        condition["type"], _tlo, _thi, _current_temp
                    )
            except Exception:
                pass

        # ── 6a. Regime detection — must run before blend weights so the regime
        # override in _blend_weights/_confidence_scaled_blend_weights fires.
        # _regime_info is initialized to {} at the top of analyze_trade; this block
        # overwrites it now that ens_stats and days_out are both available.
        try:
            from regime import detect_regime as _detect_regime

            _regime_info = _detect_regime(city, ens_stats or {}, days_out)
        except Exception:
            pass

        # ── 6. Weighted blend ────────────────────────────────────────────────────
        if obs_override is not None:
            # Scale obs weight by local hour — early morning obs is a floor,
            # not the final outcome; ramp from 0.55 at midnight to 0.95 by 18:00.
            try:
                import zoneinfo

                _local_hour = datetime.now(zoneinfo.ZoneInfo(_tz)).hour
            except Exception:
                _local_hour = datetime.now(UTC).hour
            _obs_w = min(0.95, 0.55 + _local_hour / 24.0 * 0.40)
            _ens_w = 1.0 - _obs_w
            blended_prob = _obs_w * obs_override + _ens_w * (
                ens_prob if ens_prob is not None else 0.5
            )
            blend_sources = {"obs": round(_obs_w, 4), "ensemble": round(_ens_w, 4)}
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
                condition_type=condition.get("type"),
                regime=_regime_info.get("regime"),
            )
            if persistence_p is not None and days_out <= 2:
                w_persist = 0.15
                scale = 1.0 - w_persist
                w_ens = w_ens * scale
                w_clim = w_clim * scale
                w_nws = w_nws * scale
            else:
                w_persist = 0.0
                persistence_p = None

            # Reduce NWS weight when it diverges from ensemble by > 0.20.
            # Skip trimming for below markets only when BELOW_GATE_ENABLED=1 AND >= 30
            # settled — NWS wins 5/7 disagreements but that's too few to act on yet.
            _skip_nws_trim = condition.get("type") == "below" and _below_gates_active()
            if (
                _nws_prob is not None
                and ens_prob is not None
                and abs(_nws_prob - ens_prob) > 0.20
                and not _skip_nws_trim
            ):
                w_nws_trimmed = w_nws * 0.5
                w_ens += w_nws - w_nws_trimmed
                w_nws = w_nws_trimmed

            # Split ensemble weight so Gaussian appears as its own source
            # instead of being silently embedded in the "ensemble" bucket.
            # Preserves the same 70/30 split that was previously baked in-place.
            _w_gauss = w_ens * 0.30 if gauss_prob is not None else 0.0
            _w_ens_final = w_ens * (0.70 if gauss_prob is not None else 1.0)

            # Phase 1: Empirical CDF from 51 ECMWF IFS04 ensemble members.
            # Splits _w_ens_final 50/50 between raw member-count fraction and the
            # empirical CDF when members are available, preserving total weight.
            _ensemble_cdf_prob: float | None = None
            try:
                _cdf_members = get_ensemble_members(
                    coords[0], coords[1], target_date.isoformat(), var=var, tz=_tz
                )
                if _cdf_members:
                    _ensemble_cdf_prob = ensemble_cdf_prob(_cdf_members, condition)
            except Exception:
                pass
            _w_ens_raw = _w_ens_final * (0.5 if _ensemble_cdf_prob is not None else 1.0)
            _w_cdf = _w_ens_final * (0.5 if _ensemble_cdf_prob is not None else 0.0)

            # Circuit breaker gate: if ensemble is OPEN, treat ens_prob as missing so the
            # renormalization in _active excludes it from the blend automatically.
            if _ensemble_circuit_is_open() and ens_prob is not None:
                _log.warning(
                    "analyze_trade: ensemble circuit OPEN for %s — excluding ens_prob from blend",
                    enriched.get("ticker", "?"),
                )
                ens_prob = None

            # Renormalize weights when sources are unavailable.
            # Previously missing sources were substituted with 0.5 (meaningless
            # fallback that skews the blend and doesn't sum to 1.0 correctly).
            # Now: zero out missing source weights and renormalize remaining ones.
            _src_probs = [
                (_w_ens_raw, ens_prob),
                (_w_cdf, _ensemble_cdf_prob),
                (_w_gauss, gauss_prob),
                (w_clim, clim_prob),
                (w_nws, _nws_prob),
                (w_persist, persistence_p),
            ]
            _active = [(w, p) for w, p in _src_probs if p is not None and w > 0]
            if not _active:
                # No sources at all — returning None so the caller skips this
                # market entirely rather than trading on a meaningless 0.5 prior.
                # A market priced at 0.05 would show 0.45 edge against a 0.5 model
                # prob, producing a confident trade with zero forecast basis.
                _log.warning(
                    "analyze_trade: all forecast sources unavailable for %s — skipping market",
                    enriched.get("ticker", "?"),
                )
                return None
            else:
                _total_w = sum(w for w, _ in _active)
                blended_prob = sum((w / _total_w) * p for w, p in _active)
                # Reconstruct normalized weights for blend_sources
                _norm = {
                    "ensemble": _w_ens_raw / _total_w if ens_prob is not None else 0.0,
                    "ensemble_cdf": _w_cdf / _total_w
                    if _ensemble_cdf_prob is not None
                    else 0.0,
                    "gaussian": _w_gauss / _total_w if gauss_prob is not None else 0.0,
                    "climatology": w_clim / _total_w if clim_prob is not None else 0.0,
                    "nws": w_nws / _total_w if _nws_prob is not None else 0.0,
                }
                if persistence_p is not None and w_persist > 0:
                    _norm["persistence"] = w_persist / _total_w
                blend_sources = {k: round(v, 4) for k, v in _norm.items() if v > 0}
                if ens_prob is None:
                    _log.debug(
                        "analyze_trade: ensemble missing for %s — renormalized blend",
                        enriched.get("ticker", "?"),
                    )
                if clim_prob is None:
                    _log.debug(
                        "analyze_trade: climatology missing for %s — renormalized blend",
                        enriched.get("ticker", "?"),
                    )

        # ── 6b. MOS blend (B1/B2/B6) — applied BEFORE bias correction ───────────
        # MOS is moved here so the full blended value (ensemble+NWS+clim+MOS)
        # is bias-corrected together instead of reintroducing an uncalibrated signal.
        # Use fetch_mos_best() which prefers NAM for days_out<=1 (tighter RMSE).
        # Use MOS-specific sigma instead of generic _forecast_uncertainty().
        _mos_data_pre: dict | None = None
        try:
            import mos as _mos_mod

            _mos_sta = _mos_mod.get_mos_station(city)
            if _mos_sta:
                # Only fetch MOS if pre-warm already cached it — prevents slow
                # per-market network calls from causing the 360s analysis timeout.
                # The pre-warm pool covers all city/date pairs; if a pair wasn't
                # warmed (pool timed out), skip MOS rather than block the worker.
                if _mos_mod.is_mos_cached(_mos_sta, target_date):
                    _mos_data_pre = _mos_mod.fetch_mos_best(
                        _mos_sta, target_date=target_date
                    )
                else:
                    _log.debug(
                        "analyze_trade: MOS not pre-warmed for %s/%s — skipping to avoid scan stall",
                        city,
                        target_date,
                    )
        except Exception:
            pass

        if _mos_data_pre is not None:
            # Pick high vs low temp from MOS based on market type (B4 complement).
            # Do NOT fall back across variables — mos.py documents min_temp_f as
            # float | None, so a LOW market (var="min") with no MOS minimum would
            # otherwise silently substitute the daily MAXIMUM, computing
            # P(condition | daily-high-centered distribution) for a market about
            # the daily low. Skip the MOS blend entirely when the var-appropriate
            # temperature is absent rather than guess wrong.
            _mos_temp_field = "min_temp_f" if var == "min" else "max_temp_f"
            _mos_temp_val = _mos_data_pre.get(_mos_temp_field)
            if _mos_temp_val is not None:
                try:
                    _mos_sigma_val = _mos_data_pre.get(
                        "sigma"
                    ) or _forecast_uncertainty(target_date)
                    _mos_p_pre = _forecast_probability(
                        condition, _mos_temp_val, _mos_sigma_val
                    )
                    if _mos_p_pre is not None:
                        # Incorporate MOS as a weighted source while preserving
                        # the normalisation of the existing blend.  The prior
                        # blend (ensemble + NWS + clim + persistence) is scaled
                        # down by (1 - w) so that sum(blend_sources) stays 1.0.
                        _w = _MOS_BLEND_WEIGHT
                        blended_prob = (1.0 - _w) * blended_prob + _w * _mos_p_pre
                        blended_prob = max(0.01, min(0.99, blended_prob))
                        blend_sources = {
                            k: round(v * (1.0 - _w), 4)
                            for k, v in blend_sources.items()
                        }
                        blend_sources["mos"] = round(_w, 4)
                        # Renormalise so floating-point rounding never
                        # lets weights drift above 1.0 after MOS injection.
                        _bs_total = sum(blend_sources.values())
                        if _bs_total > 0:
                            blend_sources = {
                                k: v / _bs_total for k, v in blend_sources.items()
                            }
                        else:
                            _n = len(blend_sources)
                            blend_sources = {k: 1.0 / _n for k in blend_sources}
                except Exception as _mos_pre_exc:
                    _log.debug(
                        "MOS pre-bias blend failed for %s: %s", city, _mos_pre_exc
                    )

        # ── 7. Bias correction from tracker ─────────────────────────────────────
        bias = 0.0
        try:
            from tracker import get_quintile_bias

            bias = get_quintile_bias(
                city, target_date.month, blended_prob, condition_type=condition["type"]
            )
            blended_prob = max(0.01, min(0.99, blended_prob - bias))
        except Exception as _exc:
            _log.debug(
                "Bias correction skipped for %s (%s): %s",
                enriched.get("ticker", "?"),
                city,
                _exc,
            )

        # ── 7b. Per-condition temperature scaling ────────────────────────────────
        # Corrects systematic probability bias (e.g. NWF cold bias pushing all
        # predictions low).  Uses a condition-specific T when available (between
        # markets have a much larger calibration gap than above/below) and falls
        # back to the global T.  Trained by cmd_calibrate once enough settled
        # trades exist per condition type.  No-op when no model is trained.
        #
        # Track whether scaling actually moved blended_prob so the Platt fallback
        # in section 9 can skip itself when temperature scaling already ran.
        # Platt and temperature scaling are both logit-space compression operations
        # (Platt: A·logit + B; temp scale: logit / T) — stacking both would
        # over-compress toward 0.5. GBM in section 9a is a different correction
        # (city-level systematic bias) and is fine to stack with temp scaling.
        _prob_before_temp_scale = blended_prob
        try:
            from ml_bias import apply_temperature_scaling as _apply_temp_scale

            blended_prob = max(
                0.01,
                min(
                    0.99,
                    _apply_temp_scale(
                        blended_prob,
                        condition_type=condition.get("type"),
                        days_out=days_out,
                    ),
                ),
            )
        except Exception as _exc:
            _log.error(
                "analyze_trade: temperature scaling failed for %s: %s",
                enriched.get("ticker", "?"),
                _exc,
            )
            # blended_prob remains unscaled — degraded but tradeable
        _temp_scaling_applied = abs(blended_prob - _prob_before_temp_scale) > 1e-6

        # ── 7c. Market price credibility anchor ──────────────────────────────────
        # For condition types where our model has known calibration gaps, blend a
        # fraction of blended_prob toward the market mid-price.  The market
        # aggregates live observations and professional traders we cannot replicate.
        # Guard: only anchor when the market has a real quote (mid not at extremes).
        # The anchor adjusts the magnitude of our confidence, not its direction —
        # we still bet whichever side our model favours; Kelly sizing just becomes
        # more realistic.
        #
        # Save the raw model probability BEFORE anchoring.  Section 7d uses this
        # to measure the true model-market disagreement — after anchoring the gap
        # is artificially compressed toward zero and would mask genuine conflicts.
        _prob_before_anchor = blended_prob
        _anchor_weights: dict[str, float] = {
            "between": _MARKET_ANCHOR_BETWEEN,
            "above": _MARKET_ANCHOR_ABOVE,
            "below": _MARKET_ANCHOR_BELOW,
        }
        _anchor_w = _anchor_weights.get(condition.get("type", ""), 0.0)
        _mkt_mid = _divergence_gate_market_prob  # set earlier from parse_market_price
        if _anchor_w > 0 and 0.05 < _mkt_mid < 0.95:
            _pre_anchor = blended_prob
            blended_prob = (1.0 - _anchor_w) * blended_prob + _anchor_w * _mkt_mid
            blended_prob = max(0.01, min(0.99, blended_prob))
            _log.debug(
                "analyze_trade[%s]: market_anchor type=%s w=%.2f model=%.3f market=%.3f → %.3f",
                enriched.get("ticker", "?"),
                condition.get("type"),
                _anchor_w,
                _pre_anchor,
                _mkt_mid,
                blended_prob,
            )

        # ── 7d. Model-market gap gate ─────────────────────────────────────────────
        # When the raw model disagrees with the market by >25%, the market is
        # right far more often than our model.  Empirical result across 51 settled
        # trades: 74% win rate at 10-20% gap, 50% at 20-30%, 20% at 30%+.
        # The market aggregates real-time intraday observations (hourly station
        # readings, same-day temperature trends) that overnight NWS/ensemble
        # forecasts cannot replicate.  At >25% disagreement the market's
        # informational advantage consistently outweighs our model's edge.
        # Gate on the pre-anchor gap so blending doesn't hide the disagreement.
        _model_mkt_gap = abs(_prob_before_anchor - _divergence_gate_market_prob)
        if _model_mkt_gap > 0.25 and 0.05 < _divergence_gate_market_prob < 0.95:
            _log.debug(
                "analyze_trade[%s]: model-market gap %.2f > 0.25 — skipping "
                "(market has real-time observational advantage at this gap size)",
                enriched.get("ticker", "?"),
                _model_mkt_gap,
            )
            _count_gate("model_mkt_gap")
            return None

        # Gate: below markets with extreme ensemble confidence (3/3 wrong historically).
        # Only active when BELOW_GATE_ENABLED=1 AND >= 30 settled below predictions —
        # based on only 3 data points so gated until evidence is stronger.
        if (
            _below_gates_active()
            and condition.get("type") == "below"
            and ens_prob is not None
            and (ens_prob < 0.10 or ens_prob > 0.90)
        ):
            _log.debug(
                "analyze_trade[%s]: below market extreme ensemble %.0f%% — skipping (3/3 wrong historically)",
                enriched.get("ticker", "?"),
                ens_prob * 100,
            )
            _count_gate("below_extreme_ens")
            return None

        # ── Consensus signal: all available sources agree on direction ───────────
        # Require all 3 independent sources (ensemble, NWS, climatology) to agree.
        # 2-of-2 (e.g. NWS + ensemble) share GFS heritage and is not true independence.
        sources_with_data = [
            p for p in [ens_prob, _nws_prob, clim_prob] if p is not None
        ]
        consensus = len(sources_with_data) >= 3 and (
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
        days_out = max(0, (target_date - datetime.now(UTC).date()).days)
        _fallback_temp = forecast["low_f"] if var == "min" else forecast["high_f"]
        # Explicit None-check — a legitimate 0.0°F METAR observation (routine
        # deep-winter reading) is falsy and would otherwise be replaced by the
        # model forecast. blended_prob itself is unaffected (it comes from the
        # lockout confidence, not forecast_temp), but forecast_temp is
        # persisted in the result/tracker and would corrupt downstream
        # calibration data keyed on it.
        _metar_ct = metar_lockout.get("current_temp_f")
        forecast_temp = _metar_ct if _metar_ct is not None else (_fallback_temp or 0.0)
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
        ci_low = blended_prob
        ci_high = blended_prob
        data_quality = 1.0
        anomalous = False
        model_temps = {}
        ensemble_spread_f = 0.0
        ensemble_spread_prob = 0.0
        p_win_gaussian = None
        sigma_gauss = None
        gauss_prob = None  # No Gaussian in METAR-locked path
        # Temperature scaling runs only in the non-METAR path (section 7b above).
        # Initialise False here so the Platt-skip guard at line ~5397 still works
        # correctly — METAR-locked trades never need temperature scaling because
        # blended_prob is derived directly from the observation lock, not a model blend.
        _temp_scaling_applied = False

        # Belt-and-suspenders: dampen ci_scale when we're in the pre-extreme window.
        # Layer 1 (daily min/max from ASOS) handles the root cause; this handles
        # pre-dawn uncertainty when the ASOS extreme field isn't yet populated.
        # Not applied to between markets (already excluded from the metar_locked path).
        if condition.get("type") != "between":
            try:
                import zoneinfo as _zi

                _tz_b = _CITY_TZ.get(city, "America/New_York")
                _local_hour_b = datetime.now(_zi.ZoneInfo(_tz_b)).hour
                _low_cut = int(os.environ.get("METAR_LOW_CUTOFF_HOUR", "7"))
                _high_cut = int(os.environ.get("METAR_HIGH_CUTOFF_HOUR", "14"))
                _hw = float(os.environ.get("METAR_DAMPEN_HALF_WIDTH", "0.10"))
                _dampen = (var == "min" and _local_hour_b < _low_cut) or (
                    var == "max" and _local_hour_b < _high_cut
                )
                if _dampen:
                    ci_low = max(0.0, blended_prob - _hw)
                    ci_high = min(1.0, blended_prob + _hw)
                    _log.debug(
                        "METAR ci_scale dampened: %s var=%s local_hour=%d ci=[%.2f,%.2f]",
                        enriched.get("ticker", "?"),
                        var,
                        _local_hour_b,
                        ci_low,
                        ci_high,
                    )
            except Exception:
                pass

    # _regime_info was populated earlier (section 6a) before blend weights ran.
    # Read confidence_boost from the already-detected regime dict.
    _confidence_boost = _regime_info.get("confidence_boost", 1.0)

    # Hard-skip when atmosphere is in "volatile" regime (ensemble std > 12°F).
    # A 20% Kelly reduction is not enough protection when models disagree by 12+°F —
    # the probability estimate could be off by ±0.50. Return None to skip entirely.
    if _regime_info.get("regime") == "volatile" and not metar_locked:
        _log.debug(
            "analyze_trade: skipping %s — volatile regime (std>12°F), ensemble too uncertain",
            enriched.get("ticker", "?"),
        )
        _count_gate("volatile_regime")
        return None

    # Apply exactly one city-level ML correction (GBM > Platt).
    # Gate: skip all correction tiers until enough live trades have settled.
    # Per-tier guards gate training; this gate prevents inference from models
    # trained on backtesting data being applied to live paper trades.
    _city_correction_applied = False
    if metar_locked:
        # blended_prob is observation-locked, not a model blend. GBM and Platt
        # were trained on model-blend outputs and must not run on METAR-derived
        # probabilities. Without this guard, Platt fires at 50+ settled trades
        # because _temp_scaling_applied=False in the METAR path, opening the gate.
        _city_correction_applied = True
    _pre_correction_prob = blended_prob  # captured for logging / sanity guard
    _ML_CORRECTION_LIMIT = (
        0.30  # skip any correction that shifts prob by more than this
    )
    try:
        from tracker import count_settled_predictions as _count_settled

        _n_settled = _count_settled()
    except Exception:
        _n_settled = 0
    if _n_settled < _MIN_BIAS_CORRECTION_TRADES:
        _log.debug(
            "analyze_trade: bias correction inactive (%d/%d settled trades) "
            "— models on disk: %s",
            _n_settled,
            _MIN_BIAS_CORRECTION_TRADES,
            [
                f
                for f in (
                    "bias_models.pkl",
                    "platt_models.json",
                    "temperature_scale.json",
                )
                if (Path(__file__).parent / "data" / f).exists()
            ],
        )
        _city_correction_applied = (
            True  # skip all three tiers via the guard flags below
        )
    if not _city_correction_applied and days_out > 0:
        # Skip GBM correction for same-day trades — the model is trained on
        # multi-day ensemble probabilities and would corrupt METAR-derived probs.
        try:
            from ml_bias import apply_ml_prob_correction, has_ml_model

            if has_ml_model(city):
                _corrected = apply_ml_prob_correction(
                    city, blended_prob, target_date.month, days_out
                )
                _delta = abs(_corrected - blended_prob)
                _log.info(
                    "analyze_trade: GBM correction %s %.3f → %.3f (Δ%.3f)",
                    city,
                    blended_prob,
                    _corrected,
                    _delta,
                )
                if _delta > _ML_CORRECTION_LIMIT:
                    _log.warning(
                        "analyze_trade: GBM correction for %s exceeds ±%.2f (Δ=%.3f) — skipping",
                        city,
                        _ML_CORRECTION_LIMIT,
                        _delta,
                    )
                else:
                    blended_prob = max(0.01, min(0.99, _corrected))
                    _city_correction_applied = True
        except Exception as _gbm_exc:
            _log.warning(
                "analyze_trade: GBM correction failed for %s: %s",
                enriched.get("ticker", "?"),
                _gbm_exc,
            )

    # Platt scaling is only applied when no GBM model exists for this city AND
    # temperature scaling (section 7b) has not already corrected calibration.
    # Both are logit-space compression operations — applying both would over-compress
    # probabilities toward 0.5. GBM (above) is a different correction and can stack.
    if not _city_correction_applied and not _temp_scaling_applied and days_out > 0:
        # Skip Platt correction for same-day trades — trained on multi-day
        # ensemble probs; applying to METAR-derived probs would miscalibrate.
        try:
            _platt = _load_platt_models()
            if _platt:
                from ml_bias import apply_platt_per_city as _apply_platt

                _new_prob = _apply_platt(city, blended_prob, _platt)
                if _new_prob != blended_prob:
                    _delta = abs(_new_prob - blended_prob)
                    _log.info(
                        "analyze_trade: Platt correction %s %.3f → %.3f (Δ%.3f)",
                        city,
                        blended_prob,
                        _new_prob,
                        _delta,
                    )
                    if _delta > _ML_CORRECTION_LIMIT:
                        _log.warning(
                            "analyze_trade: Platt correction for %s exceeds ±%.2f (Δ=%.3f) — skipping",
                            city,
                            _ML_CORRECTION_LIMIT,
                            _delta,
                        )
                    else:
                        blended_prob = max(0.01, min(0.99, _new_prob))
                        _city_correction_applied = True
        except Exception as _platt_exc:
            _log.warning(
                "analyze_trade: Platt scaling failed for %s: %s",
                enriched.get("ticker", "?"),
                _platt_exc,
            )

    # Realign CI to the bias/ML-corrected forecast.  The bootstrap CI is anchored
    # to the raw ensemble distribution; GBM/Platt/temperature-scaling corrections
    # may shift blended_prob well outside that range, leaving the entire CI below
    # the Kelly breakeven and causing bayesian_kelly to return 0 despite real edge.
    # Preserve CI width (ensemble spread = uncertainty magnitude) but center on
    # blended_prob so the integration sees the corrected estimate.
    # Skip this when the CI is _bootstrap_ci's own "too few members, maximally
    # uncertain" sentinel (0.0, 1.0) — re-centering it (e.g. to (0.30, 0.99) for
    # blended_prob=0.80) would convert a deliberate no-information signal into a
    # plausible-looking narrow interval that bayesian_kelly would then happily
    # integrate over, defeating the exact guard #114 was written to provide.
    if temps and (ci_high - ci_low) < 0.98:
        _ci_half = (ci_high - ci_low) / 2.0
        ci_low = max(0.01, blended_prob - _ci_half)
        ci_high = min(0.99, blended_prob + _ci_half)

    # Log source availability for per-city reliability tracking
    try:
        from tracker import log_source_attempt as _log_src

        _log_src(city, "ensemble", ens_prob is not None)
        _log_src(city, "nws", _nws_prob is not None)
        _log_src(city, "climatology", clim_prob is not None)
    except Exception:
        pass

    # Retired strategy gate — skip markets whose forecast method has been flagged as underperforming.
    try:
        from tracker import get_retired_strategies as _get_retired

        _retired = _get_retired()
        if method in _retired:
            _log.info(
                "analyze_trade: skipping %s — method '%s' is retired (Brier %.4f)",
                enriched.get("ticker", "?"),
                method,
                _retired[method].get("brier", 0),
            )
            _count_gate("retired_method")
            return None
    except Exception as _ret_exc:
        _log.debug("analyze_trade: retired-strategy check failed: %s", _ret_exc)

    # ── 9b. Between-contract low-confidence YES guard ────────────────────────
    # Block only when our low model probability would still lead to a YES bet
    # (blended_prob > market_prob).  A low between probability where we'd bet
    # NO is genuine edge — the ensemble is saying the temperature is outside
    # the bracket — and we have a 16/26 (61.5%) win rate on such NO bets.
    # The old condition (market > 0.30) was wrong: it only ever fired when
    # blended_prob < market_prob (always a NO signal), so it blocked profitable
    # NO trades while never catching the suspicious YES case it was meant for.
    if (
        condition.get("type") == "between"
        and blended_prob < BETWEEN_FLOOR_MODEL_MAX
        and blended_prob > _divergence_gate_market_prob
    ):
        _log.warning(
            "analyze_trade: skipping %s — low-confidence YES bet on between market "
            "(our=%.3f > market=%.3f but model below %.0f%% threshold)",
            enriched.get("ticker", "?"),
            blended_prob,
            _divergence_gate_market_prob,
            BETWEEN_FLOOR_MODEL_MAX * 100,
        )
        _count_gate("between_floor")
        return None

    # ── 10. Kelly fraction ───────────────────────────────────────────────────
    prices = parse_market_price(enriched)

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

    # mos_data alias for return dict compatibility
    mos_data = _mos_data_pre if not metar_locked else None

    market_prob = prices["implied_prob"]
    rec_side = "yes" if blended_prob > market_prob else "no"

    # Market divergence gate: if the market is highly confident (>70%) AND our
    # model is on the opposite side (<25%), the crowd has information we lack.
    # Skip rather than bet against a confident, well-informed market.
    if not metar_locked:
        _mkt_conf = _divergence_gate_market_prob
        _our_conf = blended_prob
        if (_mkt_conf > 0.70 and _our_conf < 0.25) or (
            _mkt_conf < 0.30 and _our_conf > 0.75
        ):
            _log.debug(
                "analyze_trade: divergence gate skip %s — market=%.2f our=%.2f",
                enriched.get("ticker", "?"),
                _mkt_conf,
                _our_conf,
            )
            _count_gate("analysis_diverge")
            return None

    # #63 / L7-D: Time-decay edge — scale linearly to zero as market approaches close.
    # Applied (via _price_and_size's time_decay) to edge, entry_side_edge, and
    # net_edge so the gate (adjusted_edge) and sort key reflect intra-day time
    # risk — not only the display 'edge'.
    _time_decay_factor = 1.0
    _close_str = enriched.get("close_time", "")
    if _close_str:
        try:
            _close_dt = datetime.fromisoformat(_close_str.replace("Z", "+00:00"))
            _time_decay_factor = time_decay_edge(1.0, _close_dt, reference_hours=8.0)
        except (ValueError, TypeError):
            pass

    # #62: explicit illiquid flag (spread > 5%)
    illiquid = spread_cost > 0.05

    # Scale Kelly down for low data quality and anomalous forecasts
    quality_scale = 0.5 + 0.5 * data_quality  # 0.5 at quality=0, 1.0 at quality=1
    anomaly_scale = 0.70 if anomalous else 1.0

    # Time-value Kelly: reduce bet size for far-out markets (more uncertainty).
    # Scale: 1.0 at 0-1 days → 0.5 at ≥14 days. Intermediate values are linear.
    time_kelly_scale = max(0.35, 1.0 - (days_out / 14.0) * 0.50)

    # F2: consensus bonus applied BEFORE the cap so it actually takes effect —
    # consensus trades get a higher ceiling (KELLY_CAP * KELLY_CAP_CONSENSUS_MULT,
    # 0.33 at defaults) to reward highest-conviction signals.
    _priced = _price_and_size(
        blended_prob,
        prices,
        condition,
        rec_side,
        ci=(ci_low, ci_high),
        consensus=consensus,
        extra_kelly_scales=(
            quality_scale,
            anomaly_scale,
            spread_scale,
            time_kelly_scale,
            _confidence_boost,
        ),
        time_decay=_time_decay_factor,
        yes_side_ask_fallback=True,
    )
    entry_price = _priced["entry_price"]
    edge = _priced["edge"]
    signal = _edge_label(edge)
    entry_side_edge = _priced["entry_side_edge"]
    net_edge = _priced["net_edge"]
    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
    adjusted_edge = net_edge * _edge_conf
    net_signal = _edge_label(adjusted_edge)
    kelly = _priced["fee_kel"]
    fee_adjusted_kelly = _priced["fee_kel"]
    ci_adjusted_kelly = _priced["ci_adjusted_kelly"]
    _ci_scale = _priced["ci_scale"]

    # Near-threshold penalty: forecast is within ±3°F of threshold → high flip risk
    if near_threshold:
        ci_adjusted_kelly = round(ci_adjusted_kelly * 0.75, 6)

    # Bimodal ensemble guard: two distinct weather scenarios -> sharp Kelly reduction
    _bimodal_mult = _get_bimodal_kelly_multiplier(temps) if temps else 1.0
    if _bimodal_mult < 1.0:
        ci_adjusted_kelly = round(ci_adjusted_kelly * _bimodal_mult, 6)

    # Forecast run-to-run trend signal (backlog.txt "FORECAST RUN-TO-RUN TREND
    # SIGNAL") is deliberately NOT computed here. An independent review
    # (2026-07-16) found that fetching it inline in analyze_trade -- up to 3
    # sequential HTTP calls, up to ~60s worst case on a cache miss -- sits on
    # the live order-placement critical path: analyze_trade's caller places
    # the order only after this function returns, so a slow fetch delays an
    # already-fully-decided trade's submission even though the fetch itself
    # never touches blended_prob/kelly/edge. Moved to
    # tracker.get_forecast_run_trend_from_analysis(), called only at
    # log_prediction time (which for real trades already happens AFTER order
    # placement -- see order_executor._auto_place_trades) so it can never
    # affect fill timing. See order_executor._prediction_kwargs_from_analysis
    # and main.py's two direct log_prediction call sites.

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
        "bimodal": _bimodal_mult < 1.0,
        # Confidence + sizing
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_width": ci_high - ci_low,
        "ci_scale": _ci_scale,
        "entry_price": entry_price,
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
        "city": city,  # needed by detect_hedge_opportunity's same-city+date match
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
        "gaussian_prob": gauss_prob,  # Raw Gaussian blend (separate from ens_prob)
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
        # Phase 6.0: obs-weight learning fields (None when no obs override)
        "obs_weight_used": _obs_w if obs_override is not None else None,
        "local_hour": _local_hour if obs_override is not None else None,
        # NWS/ensemble temperature gap — None when metar-locked (no ensemble run)
        "model_disagreement_f": disagree_f if ens_stats else None,
        "model_disagreement_flag": bool(
            ens_stats and disagree_f is not None and disagree_f > 8.0
        ),
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
    target_date = analysis.get("target_date")
    rec_side = analysis.get("recommended_side", "yes")
    opposite = "no" if rec_side == "yes" else "yes"
    return any(
        t.get("city") == city
        and t.get("target_date") == target_date
        and t.get("side") == opposite
        for t in open_trades
        if not t.get("settled")
    )
