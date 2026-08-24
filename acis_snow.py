"""
NOAA ACIS StnData (month-to-date actual + historical daily snowfall) and
Open-Meteo Seasonal API (ECMWF SEAS5 monthly-mean tilt) for the monthly
snow-total ladder model (backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step
2). Mirrors acis_precip.py's fetch/cache shape for the "snow" ACIS element
and the "snowfall_mean" Open-Meteo Seasonal variable -- NOT a copy of the
bootstrap/tilt math itself, which is already substance-agnostic and is
imported directly from acis_precip.py rather than duplicated (user-confirmed
design decision, 2026-07-30): historical_remaining_and_full_month_sums,
bootstrap_ci_month_total, and apply_seasonal_tilt all operate on generic
float lists + a threshold, with no precip-specific logic.

Deliberately a separate module rather than genericizing acis_precip.py's
fetch functions in place: acis_precip.py backs rain's live shadow-trading
path today, while snow has no live market at all (Denver's only-ever snow
market, Dec 2025, had zero volume/open-interest on all 7 brackets and never
reached status="finalized" -- confirmed live 2026-07-30). Keeping the fetch
layer separate means this module's real, unvalidated-against-live-data risk
never touches rain's working code.

Own CircuitBreaker/ForecastCache instances (not shared with acis_precip.py)
so a snow-specific fetch failure/cache entry can never cross-contaminate
rain's breaker counts or collide on a (lat, lon, tz, year, month) cache key
that would otherwise be ambiguous between "precip mean" and "snow mean".
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

import safe_io
from acis_precip import (
    _station_sid_for_city,
    apply_seasonal_tilt,
    bootstrap_ci_month_total,
    historical_remaining_and_full_month_sums,
)
from circuit_breaker import CircuitBreaker
from forecast_cache import ForecastCache
from paths import DATA_DIR

__all__ = [
    "fetch_month_to_date_actual_snow",
    "fetch_historical_daily_snow",
    "fetch_seasonal_snow_mean_cm",
    "_station_sid_for_city",
    "historical_remaining_and_full_month_sums",
    "bootstrap_ci_month_total",
    "apply_seasonal_tilt",
]

_log = logging.getLogger(__name__)

_acis_snow_cb = CircuitBreaker(
    name="acis_stndata_snow", failure_threshold=5, recovery_timeout=600
)
_om_seasonal_snow_cb = CircuitBreaker(
    name="open_meteo_seasonal_snow", failure_threshold=5, recovery_timeout=600
)

_SEASONAL_CACHE_TTL = 4 * 3600
_seasonal_cache: ForecastCache[float | None] = ForecastCache(
    ttl_secs=_SEASONAL_CACHE_TTL
)

_session = requests.Session()

ACIS_STNDATA_URL = "http://data.rcc-acis.org/StnData"
OPEN_METEO_SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"

HISTORY_YEARS = 30
CACHE_MAX_AGE = 30 * 24 * 3600

# ACIS StnData's "snow" element (like "pcpn") is in inches -- confirmed live
# 2026-07-30 (Denver Dec 2025 ACIS "snow" values e.g. 4.3, 0.0, "T", matching
# NWS CLI-report inch convention). Open-Meteo Seasonal's "snowfall_mean" is
# in CENTIMETERS, not millimeters (confirmed live: Denver Nov 2026 returned
# 15.82, only plausible as cm) -- unlike acis_precip.py's mm-denominated
# precipitation_mean. apply_seasonal_tilt() (imported from acis_precip.py,
# reused as-is) expects its seasonal_mean_mm argument in millimeters and
# handles the historical inches->mm conversion internally (a universal unit
# conversion, not precip-specific) -- so callers here must convert this
# function's cm return value to mm (x10) before passing it in, NOT pass cm
# directly. See _analyze_monthly_snow_trade's call site.

# ACIS non-numeric daily-value sentinels -- same convention as acis_precip.py
# ("T" = trace, "M" = missing, "S" = accumulated/subsequent).


def _parse_snow_value(raw: str | float | None) -> float | None:
    """Parse one ACIS 'snow' daily value. Returns None for missing/
    unparseable (never silently propagates a bad string into arithmetic)."""
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    s = str(raw).strip()
    if s == "T":
        return 0.0
    if s in ("M", ""):
        return None
    if s == "S":
        _log.debug(
            "_parse_snow_value: 'S' (accumulated/subsequent) sentinel — treating as missing"
        )
        return None
    try:
        return float(s)
    except ValueError:
        _log.warning("_parse_snow_value: unparseable ACIS snow value %r", raw)
        return None


def fetch_month_to_date_actual_snow(
    sid: str, year: int, month: int, through_day: int
) -> tuple[float | None, int]:
    """POST to ACIS StnData for sdate=YYYY-MM-01 through through_day (always
    "yesterday" in the target city's local time, never "today"). Mirrors
    acis_precip.fetch_month_to_date_actual exactly, elem="snow" instead of
    "pcpn". Returns (sum_or_None, n_missing_days). Returns (None, 0) if
    through_day < 1."""
    if through_day < 1:
        return (None, 0)
    sdate = f"{year}-{month:02d}-01"
    edate = f"{year}-{month:02d}-{through_day:02d}"
    if _acis_snow_cb.is_open():
        _log.info(
            "[CircuitBreaker] acis_stndata_snow circuit open — skipping month-to-date fetch"
        )
        return (None, 0)
    payload = {
        "sid": sid,
        "sdate": sdate,
        "edate": edate,
        "elems": [{"name": "snow", "interval": "dly", "duration": "dly"}],
    }
    try:
        resp = _session.post(ACIS_STNDATA_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        _acis_snow_cb.record_success()
    except Exception as exc:
        _acis_snow_cb.record_failure()
        _log.warning(
            "fetch_month_to_date_actual_snow: ACIS fetch failed for sid=%s: %s",
            sid,
            exc,
        )
        return (None, 0)

    total = 0.0
    n_missing = 0
    for _date_str, raw_val in data:
        val = _parse_snow_value(raw_val)
        if val is None:
            n_missing += 1
        else:
            total += val
    # Opus-review-caught gap (round 2): ACIS can return HTTP 200 with an
    # empty "data" array (confirmed live: an unresolvable sid returns
    # {"data": [], "error": "no data available"}) -- raise_for_status()
    # doesn't catch this, and a loop over zero rows silently reports
    # n_missing=0, not through_day. Count any days ACIS didn't return a
    # row for at all as missing too, mirroring acis_precip.py's identical
    # fix, so the caller's own missing-data guard can actually see a
    # fully/partially empty response instead of treating it as a
    # legitimate 0.0 total.
    n_missing += max(0, through_day - len(data))
    return (total, n_missing)


def _cache_path(sid: str) -> Path:
    return DATA_DIR / f"acis_snow_{sid}.json"


def _cache_is_stale(cache: Path) -> bool:
    """Own copy, not imported from acis_precip: that module's version reads
    acis_precip.CACHE_MAX_AGE directly (no parameter), so importing it would
    silently check the wrong module's constant if the two ever diverge."""
    if not cache.exists():
        return True
    return (time.time() - cache.stat().st_mtime) > CACHE_MAX_AGE


_MEM_CACHE: dict[str, dict] = {}


def fetch_historical_daily_snow(
    sid: str, years: int = HISTORY_YEARS, force: bool = False
) -> dict[int, dict[int, float | None]] | None:
    """One POST call covering the full `years`-year daily snowfall history,
    disk-cached. Mirrors acis_precip.fetch_historical_daily exactly,
    elem="snow" instead of "pcpn" and its own cache file/mem-cache namespace.
    Returns {year: {ordinal_day_of_year: value_or_None}}, or None on total
    fetch failure with no usable cache."""
    if not force and sid in _MEM_CACHE:
        return _MEM_CACHE[sid]

    cache = _cache_path(sid)
    if cache.exists() and not force and not _cache_is_stale(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                raw = json.load(f)
            parsed = {
                int(y): {int(d): v for d, v in days.items()} for y, days in raw.items()
            }
            _MEM_CACHE[sid] = parsed
            return parsed
        except Exception as exc:
            _log.warning(
                "fetch_historical_daily_snow: cache read failed for sid=%s: %s",
                sid,
                exc,
            )

    from utils import utc_today as _utc_today

    end_year = _utc_today().year - 1
    start_year = end_year - years + 1

    if _acis_snow_cb.is_open():
        _log.info(
            "[CircuitBreaker] acis_stndata_snow circuit open — skipping historical fetch"
        )
        return _load_stale_cache_or_none(cache, sid)

    payload = {
        "sid": sid,
        "sdate": f"{start_year}-01-01",
        "edate": f"{end_year}-12-31",
        "elems": [{"name": "snow", "interval": "dly", "duration": "dly"}],
    }
    try:
        resp = _session.post(ACIS_STNDATA_URL, json=payload, timeout=30)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        _acis_snow_cb.record_success()
    except Exception as exc:
        _acis_snow_cb.record_failure()
        _log.warning(
            "fetch_historical_daily_snow: ACIS fetch failed for sid=%s: %s", sid, exc
        )
        return _load_stale_cache_or_none(cache, sid)

    result: dict[int, dict[int, float | None]] = {}
    for date_str, raw_val in rows:
        try:
            y, m, d = (int(x) for x in date_str.split("-"))
        except (ValueError, AttributeError):
            continue
        result.setdefault(y, {})[m * 100 + d] = _parse_snow_value(raw_val)

    # Opus-review-caught gap (round 2, identical to acis_precip.py's
    # cloned bug): ACIS returning HTTP 200 with an empty "data" array
    # parses to result={} here -- not None, so the fail-open
    # `_load_stale_cache_or_none` path above is bypassed entirely, and an
    # empty dict gets written to disk as the 30-day cache AND the
    # process-lifetime mem-cache, poisoning both from one transient
    # response. Treat an empty result the same as a fetch failure.
    if not result:
        _log.warning(
            "fetch_historical_daily_snow: ACIS returned no usable rows for "
            "sid=%s -- falling back to stale cache instead of caching an "
            "empty result",
            sid,
        )
        return _load_stale_cache_or_none(cache, sid)

    try:
        serializable = {
            str(y): {str(k): v for k, v in days.items()} for y, days in result.items()
        }
        safe_io.atomic_write_json(serializable, cache)
    except Exception as exc:
        _log.warning(
            "fetch_historical_daily_snow: cache write failed for sid=%s: %s", sid, exc
        )

    _MEM_CACHE[sid] = result
    return result


def _load_stale_cache_or_none(
    cache: Path, sid: str
) -> dict[int, dict[int, float | None]] | None:
    """L-1: deliberately does NOT write into _MEM_CACHE -- see
    acis_precip._load_stale_cache_or_none's identical fix/docstring for the
    full rationale (this is the cloned copy). _MEM_CACHE is a plain dict
    with no TTL; caching a stale-fallback result here would pin it for the
    rest of the process's lifetime instead of letting the next call retry
    the circuit breaker/network path once ACIS recovers.
    """
    if not cache.exists():
        _log.warning(
            "fetch_historical_daily_snow: API failed for sid=%s and no cache exists",
            sid,
        )
        return None
    try:
        with open(cache, encoding="utf-8") as f:
            raw = json.load(f)
        return {int(y): {int(d): v for d, v in days.items()} for y, days in raw.items()}
    except Exception as exc:
        _log.warning(
            "fetch_historical_daily_snow: stale cache read failed for sid=%s: %s",
            sid,
            exc,
        )
        return None


def fetch_seasonal_snow_mean_cm(
    lat: float, lon: float, tz: str, year: int, month: int
) -> float | None:
    """GET Open-Meteo Seasonal (monthly=snowfall_mean -- confirmed live
    2026-07-30 as a real, working monthly variable returning cm; unlike
    precipitation_mean, "snowfall_sum" 400s, and "snowfall_mean" is the one
    that works). Returns the ECMWF SEAS5 monthly-mean snowfall in cm for
    (year, month), or None on any failure or if the target month is outside
    the API's ~6-month forecast window. Mirrors acis_precip.
    fetch_seasonal_precip_mean_mm's exact caching shape (own _seasonal_cache
    instance, so a None result is cached too, not just a success)."""
    cache_key = (lat, lon, tz, year, month)
    cached, hit, _ = _seasonal_cache.get_with_ts(cache_key)
    if hit:
        return cached

    if _om_seasonal_snow_cb.is_open():
        _log.info(
            "[CircuitBreaker] open_meteo_seasonal_snow circuit open — skipping seasonal fetch"
        )
        return None
    params = {
        "latitude": str(lat),
        "longitude": str(lon),
        "monthly": "snowfall_mean",
        "timezone": tz,
    }
    try:
        resp = _session.get(OPEN_METEO_SEASONAL_URL, params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        monthly = body.get("monthly", {})
        _om_seasonal_snow_cb.record_success()
    except Exception as exc:
        _om_seasonal_snow_cb.record_failure()
        _log.info("fetch_seasonal_snow_mean_cm: fetch failed: %s", exc)
        _seasonal_cache.set(cache_key, None)
        return None

    # Opus-review-caught gap: the "cm, not mm" claim (this module's own
    # header comment) was inferred from one value being merely plausible
    # as cm rather than validated against what the API actually reports.
    # monthly_units is returned alongside "monthly" on every real response
    # (confirmed live 2026-07-30: {"snowfall_mean": "cm"}) -- check it
    # directly so a future Open-Meteo unit change fails loudly instead of
    # silently mis-tilting the bootstrap by 10x (this value feeds a x10
    # cm-to-mm conversion at the _analyze_monthly_snow_trade call site).
    # L-1: fail CLOSED (missing OR wrong unit refused), not open -- see
    # acis_precip.fetch_seasonal_precip_mean_mm's identical fix for the
    # rationale. `is not None and !=` used to treat an absent monthly_units
    # key the same as a confirmed "cm", defeating this guard's own purpose.
    _unit = body.get("monthly_units", {}).get("snowfall_mean")
    if _unit is None or _unit != "cm":
        _log.warning(
            "fetch_seasonal_snow_mean_cm: expected unit 'cm', API reported %r "
            "-- refusing to use this value (would mis-tilt the bootstrap)",
            _unit,
        )
        _seasonal_cache.set(cache_key, None)
        return None

    times = monthly.get("time", [])
    values = monthly.get("snowfall_mean", [])
    result: float | None = None
    for t, v in zip(times, values):
        if not (isinstance(t, str) and v is not None):
            continue
        try:
            t_year, t_month = int(t[:4]), int(t[5:7])
        except (ValueError, IndexError):
            continue
        entry_val = float(v)
        _seasonal_cache.set((lat, lon, tz, t_year, t_month), entry_val)
        if t_year == year and t_month == month:
            result = entry_val
    if result is None:
        _seasonal_cache.set(cache_key, None)
    return result
