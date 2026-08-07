"""
Historical climatology from Open-Meteo archive API.
Fetches 30 years of daily high/low for each city and caches to disk.
Used as a baseline probability before forecast skill is considered.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from datetime import date
from pathlib import Path

import requests

import safe_io
from circuit_breaker import CircuitBreaker as _CircuitBreaker
from forecast_cache import ForecastCache
from paths import DATA_DIR
from utils import prob_threshold as _prob_threshold

_log = logging.getLogger(__name__)
_clim_cb = _CircuitBreaker("climatology", failure_threshold=5, recovery_timeout=300)

# #125: shared session for connection pooling
_session = requests.Session()

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
# ForecastCache with an infinite TTL, not a plain dict (backlog.txt "ForecastCache
# EXISTS, BUT 2 HAND-ROLLED CACHES..."): once a city's data is cached in memory it
# is trusted for the rest of the process regardless of the disk file's own age --
# that staleness check only ever runs on a cache MISS, below -- so ttl_secs=inf
# preserves this exact "load once per process" behavior while gaining
# ForecastCache's per-call atomicity (a single .get()/.set() can't race another
# thread's .get()/.set() on a DIFFERENT key). This does NOT close a same-city
# race: trade_cycle.py submits per-MARKET (8 workers), so multiple markets for
# the same city routinely call fetch_historical() concurrently, and two threads
# can both miss a cold _MEM_CACHE entry and both independently hit the Open-Meteo
# archive API + atomic_write_json the same climate_{city}.json (the same race
# class _sigma_lock exists to serialize for forecast_sigma.json, just without an
# equivalent lock here). Pre-existing and unchanged by this migration -- a plain
# dict had the identical exposure -- and low-frequency in practice (this only
# fires on a cold/expired disk cache, ~once per city per year; preload_all()
# warms the disk cache single-threaded before cron's scan loop normally runs).
# No whole-dict disk persistence is needed here (unlike nws.py's
# PersistentForecastCache-based _station_cache): each city already round-trips
# to its own climate_{city}.json file via the plain json.load/
# safe_io.atomic_write_json calls below, independent of this in-memory layer.
_MEM_CACHE: ForecastCache[dict] = ForecastCache(ttl_secs=float("inf"))


def fetch_historical(city: str, coords: tuple, force: bool = False) -> dict | None:
    """
    Download 30 years of daily high/low for a city and cache to disk.
    Auto-refreshes if the cache is older than 1 year.
    Returns dict with keys: dates, highs, lows.
    """
    if not force:
        cached = _MEM_CACHE.get(city)
        if cached is not None:
            return cached

    cache = _cache_path(city)
    if cache.exists() and not force and not _cache_is_stale(cache):
        with open(cache) as f:
            data = json.load(f)
        _MEM_CACHE.set(city, data)
        return data

    from utils import utc_today as _utc_today

    lat, lon, tz = coords
    end_year = _utc_today().year - 1
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
        _MEM_CACHE.set(city, data)
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
            _MEM_CACHE.set(city, data)
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
# ForecastCache with an infinite TTL and a single constant key, not a plain dict
# (backlog.txt "ForecastCache EXISTS, BUT 2 HAND-ROLLED CACHES..."): this cache is
# meant to hold exactly one value -- the full all-cities/all-months table -- built
# from a single call passing the COMPLETE city registry, so a constant key matches
# that intent (contrast climate_indices.py's get_indices(), previously bugged by
# sharing one "latest" key across genuinely different (year, month) results).
# preload_all() (main.py's first-run wizard loops one city at a time) can call
# load_all_sigmas() with a PARTIAL city_coords -- it merges into whatever the
# file already contains rather than overwriting under this constant key (see
# load_all_sigmas()'s own docstring for the full mechanism; backlog.txt
# "PRELOAD_ALL CAN PERMANENTLY TRUNCATE forecast_sigma.json TO ONE CITY ON A
# PARTIAL CALL"). The one thing this constant key still assumes: whichever
# call last wrote _sigma_mem_cache reflects the union of every city anyone has
# ever asked for, not necessarily the CURRENT full registry -- a city removed
# from the registry keeps its stale entry around (harmless, nothing reads an
# unknown key) rather than being pruned on the next full rebuild.
# _sigma_lock (below) still wraps the whole check-then-fetch-then-write sequence
# in load_all_sigmas(): ForecastCache's own internal lock only makes a single
# .get()/.set() call atomic, which is NOT sufficient to prevent two threads both
# seeing a cold cache and both recomputing + writing forecast_sigma.json (the
# exact race this lock exists to serialize).
_SIGMA_KEY = "all"
_sigma_mem_cache: ForecastCache[dict] = ForecastCache(ttl_secs=float("inf"))
_sigma_lock = threading.Lock()


def _sigma_entry_has_data(entry: object) -> bool:
    """True if a per-city sigma cache entry has at least one real computed
    month value. A dict-shaped but fully empty entry ({"max": {}, "min": {}})
    happens when compute_sigma_from_climate() came back empty for both vars
    (e.g. fetch_historical() had no data yet, network down, or fresh install
    before the climate archive downloaded) -- treated as "no data" rather
    than "present," so callers keep retrying it instead of treating a failed
    compute as permanently satisfied.
    """
    return isinstance(entry, dict) and bool(entry.get("max") or entry.get("min"))


def _load_sigma_cache_file() -> dict:
    """Read _SIGMA_CACHE_PATH and return its dict content, or {} on any
    read/parse failure or non-dict content (corrupt file, truncated write,
    or an unexpected JSON shape) -- never raises.
    """
    if not _SIGMA_CACHE_PATH.exists():
        return {}
    try:
        with open(_SIGMA_CACHE_PATH) as f:
            loaded = json.load(f)
    except Exception as e:
        _log.warning("Could not read existing forecast_sigma.json: %s", e)
        return {}
    if not isinstance(loaded, dict):
        _log.warning(
            "forecast_sigma.json did not contain a JSON object (got %s) -- ignoring it",
            type(loaded).__name__,
        )
        return {}
    return loaded


def _sigma_cache_missing_cities(city_coords: dict) -> set[str]:
    """Cities in city_coords not yet present -- or present with no real
    computed data, see _sigma_entry_has_data() -- in the on-disk sigma cache.

    A missing/corrupt/non-dict file is treated as "everything missing" (via
    _load_sigma_cache_file() returning {}) so the caller falls through to a
    real recompute rather than silently skipping it.
    """
    existing = _load_sigma_cache_file()
    return {
        city for city in city_coords if not _sigma_entry_has_data(existing.get(city))
    }


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

    Merges into the existing cache file rather than overwriting it wholesale
    (backlog.txt "PRELOAD_ALL CAN PERMANENTLY TRUNCATE forecast_sigma.json TO
    ONE CITY ON A PARTIAL CALL"): a caller that passes a city_coords subset
    (e.g. main.py's setup wizard, which calls preload_all() once per city so
    it can report per-city progress) only recomputes entries for the cities
    it actually passed -- every other city's existing entry in the file is
    preserved rather than being dropped from the table. A city whose compute
    comes back empty for both max and min (no data yet -- see
    _sigma_entry_has_data()) does NOT overwrite a real existing entry for
    that city, so a transient failure can't clobber previously-good data.

    The force=False "fresh cache" fast path also checks whether every
    requested city actually has real data in the cached file (opus-review-
    caught 2026-08-07): without this, a caller that hits load_all_sigmas()
    directly with force=False -- weather_markets._load_dynamic_sigma(), the
    actual live cron/trading path, which never goes through preload_all()'s
    own gate at all -- would silently accept a file that's "fresh" (recently
    written) but missing a city that was just added to the registry, or one
    whose entry is still empty from an earlier failed compute, and serve
    stale/default sigma for that city for up to _SIGMA_CACHE_AGE.

    Residual gap (opus-review-caught 2026-08-07, LOW severity, not fixed):
    staleness is tracked at the whole-FILE level (_SIGMA_CACHE_PATH's mtime),
    not per-city. A partial write for city X bumps the file's mtime, which
    makes city Y's entry look "fresh" to the age check above even if Y's own
    data hasn't actually been recomputed in >_SIGMA_CACHE_AGE. Fixing this
    properly would mean per-city computed-at timestamps in the cache
    structure -- deferred as a real scope increase on top of this fix, not a
    one-line change, and today's only partial caller (the setup wizard) runs
    once per install, so the exposure window is small in practice.

    Thread-safe WITHIN one process (backlog.txt "FORECAST_SIGMA.JSON ATOMIC
    WRITE CONTENTION"): cron.py's ThreadPoolExecutor scan can call this via
    weather_markets._load_dynamic_sigma() from multiple worker threads at
    once. Without a lock, concurrent threads hitting a cold _sigma_mem_cache
    each independently recompute the full per-city table and race to
    atomic_write_json() the same forecast_sigma.json, colliding on the
    rename step (observed WinError 32/5/2, self-recovering via
    atomic_write_json's emergency-copy fallback but recurring). Matches
    climate_indices.py's _indices_lock convention for the same
    check-then-fetch-then-cache shape. This _sigma_lock gives NO protection
    across processes -- web_app.py's Flask dashboard (a separate process,
    threaded=True) reaches this same function via the same call chain, so a
    cron.py write racing a web_app.py read of forecast_sigma.json is a
    real, still-open (lower-severity, retry-recoverable) residual case this
    lock cannot cover; safe_io.atomic_write_json's own pid+thread-keyed temp
    names and retry/backoff are what absorb that one. The merge behavior
    above (opus-review-caught 2026-08-07) changes the SHAPE of the
    cross-process risk from "last writer wins with a benign full table" to
    "last writer wins with a read-modify-write" -- two processes racing a
    partial write (e.g. the setup wizard and a concurrent cron run) can each
    read the same stale base and each write back their own partial view,
    with the second write silently dropping whatever the first added. Still
    unprotected across processes for the same reason as above; bounded in
    practice by every current partial caller (the wizard) being a one-time,
    single-process, foreground-only code path.

    Note (opus-review-caught, 2026-08-07): ForecastCache.get() returns None on
    both "no entry" and "entry present but falsy" -- an empty {} result (e.g.
    city_coords={}) is memoized as a cache hit forever (ttl_secs=inf), where
    the old plain-dict check (`if _sigma_mem_cache and not force`) would have
    re-read disk on every subsequent call instead. Narrow (no real caller
    passes an empty city_coords -- callers pass either the full registry or a
    non-empty subset, see the merge note above) and harmless in that case --
    not fixed, since doing so would mean changing ForecastCache's own
    get()/miss semantics for every other consumer, not just this one.
    """
    with _sigma_lock:
        cached = _sigma_mem_cache.get(_SIGMA_KEY)
        if cached is not None and not force:
            return cached

        if not force and _SIGMA_CACHE_PATH.exists():
            age = time.time() - _SIGMA_CACHE_PATH.stat().st_mtime
            if age < _SIGMA_CACHE_AGE and not _sigma_cache_missing_cities(city_coords):
                loaded = _load_sigma_cache_file()
                _sigma_mem_cache.set(_SIGMA_KEY, loaded)
                return loaded

        result: dict = _load_sigma_cache_file()

        for city, coords in city_coords.items():
            max_sigma = {
                str(k): v
                for k, v in compute_sigma_from_climate(city, coords, var="max").items()
            }
            min_sigma = {
                str(k): v
                for k, v in compute_sigma_from_climate(city, coords, var="min").items()
            }
            if not (max_sigma or min_sigma) and _sigma_entry_has_data(result.get(city)):
                # Compute came back empty (e.g. no climate archive yet, or a
                # transient fetch failure) but the merge base already has
                # real data for this city -- keep it rather than clobbering
                # good data with an empty entry.
                continue
            result[city] = {"max": max_sigma, "min": min_sigma}

        try:
            safe_io.atomic_write_json(result, _SIGMA_CACHE_PATH)
        except Exception as e:
            _log.warning("Could not write forecast_sigma.json: %s", e)

        _sigma_mem_cache.set(_SIGMA_KEY, result)
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

    # Recompute sigma cache if missing, stale, or if any city in THIS call
    # isn't in it yet (backlog.txt "PRELOAD_ALL CAN PERMANENTLY TRUNCATE
    # forecast_sigma.json TO ONE CITY ON A PARTIAL CALL"): a per-city caller
    # like main.py's setup wizard writes the file on city 1, which then
    # looks "fresh" to a plain existence/staleness gate -- silently blocking
    # any refresh for cities 2..N until the file goes stale a month later.
    # Checking for missing cities (not a hardcoded total city count, which
    # would go stale as cities are added/removed, and can't safely import
    # weather_markets.CITY_COORDS here -- weather_markets already imports
    # this module) closes that gap without needing to know the "real"
    # registry size. Paired with load_all_sigmas()'s merge-not-overwrite fix
    # above so each partial call adds to the table instead of erasing it.
    # NOTE: this gate only protects preload_all()'s own (always force=True)
    # call -- load_all_sigmas() has its own, independent missing-cities check
    # on its force=False fast path for callers that reach it directly without
    # going through preload_all() at all (weather_markets._load_dynamic_sigma,
    # the live cron/trading path -- see that function's docstring).
    cache_exists = _SIGMA_CACHE_PATH.exists()
    stale = cache_exists and (
        time.time() - _SIGMA_CACHE_PATH.stat().st_mtime > _SIGMA_CACHE_AGE
    )
    if not cache_exists or stale or _sigma_cache_missing_cities(city_coords):
        print("  Computing per-city forecast sigma from climate archive...", flush=True)
        load_all_sigmas(city_coords, force=True)
