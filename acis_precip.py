"""
NOAA ACIS StnData (month-to-date actual + historical daily precipitation) and
Open-Meteo Seasonal API (ECMWF SEAS5 monthly-mean tilt) for the monthly
rain-total ladder model (backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step
2). Mirrors climatology.py's fetch/cache/probability module shape.

ACIS StnData is unauthenticated, public, and was never touched by this bot
before this feature. Open-Meteo Seasonal is a different endpoint/host than
the ensemble/archive APIs weather_markets.py already uses (mean-only, no
per-member spread -- can only tilt a distribution built some other way, not
supply one itself).
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path

import requests

import safe_io
from circuit_breaker import CircuitBreaker

_log = logging.getLogger(__name__)

_acis_cb = CircuitBreaker(
    name="acis_stndata", failure_threshold=5, recovery_timeout=600
)
_om_seasonal_cb = CircuitBreaker(
    name="open_meteo_seasonal", failure_threshold=5, recovery_timeout=600
)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

_session = requests.Session()

ACIS_STNDATA_URL = "http://data.rcc-acis.org/StnData"
OPEN_METEO_SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"

HISTORY_YEARS = 30
CACHE_MAX_AGE = 30 * 24 * 3600  # 30 days -- shorter than climatology.py's 365d:
# a public, little-used-by-this-bot endpoint's failure mode is worth checking
# more often; the fetch itself is trivial cost either way.

# ACIS non-numeric daily-value sentinels (per ACIS docs):
#   "T" = trace (measurable but below the gauge's reporting resolution)
#   "M" = missing
#   "S" = accumulated/subsequent -- a multi-day total folded into one date
#         (e.g. a broken gauge catches up days later); not empirically hit
#         in this session's live testing but defensively handled.


def _station_sid_for_city(city: str) -> str | None:
    """Derive an ACIS StnData `sid` from metar.MARKET_STATION_MAP[city] by
    stripping the leading 'K' (KDEN -> DEN, KNYC -> NYC, KSEA -> SEA, ...).
    Confirmed live this session: ACIS accepts these stripped codes directly
    for all 10 rain cities, zero exceptions -- including NYC, which fits the
    same rule because ACIS's sid="NYC" happens to resolve to "NY CITY
    CENTRAL PARK", matching Kalshi's own settlement text for that city."""
    from metar import MARKET_STATION_MAP

    icao = MARKET_STATION_MAP.get(city)
    if not icao:
        return None
    return icao[1:] if icao.startswith("K") else icao


def _parse_pcpn_value(raw: str | float | None) -> float | None:
    """Parse one ACIS 'pcpn' daily value. Returns None for missing/
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
            "_parse_pcpn_value: 'S' (accumulated/subsequent) sentinel — treating as missing"
        )
        return None
    try:
        return float(s)
    except ValueError:
        _log.warning("_parse_pcpn_value: unparseable ACIS pcpn value %r", raw)
        return None


def fetch_month_to_date_actual(
    sid: str, year: int, month: int, through_day: int
) -> tuple[float | None, int]:
    """POST to ACIS StnData for sdate=YYYY-MM-01 through through_day (always
    "yesterday" in the target city's local time, never "today", to avoid
    counting a partial/incomplete same-day station report).

    Returns (sum_or_None, n_missing_days). Returns (None, 0) if through_day
    < 1 (nothing accrued yet this month)."""
    if through_day < 1:
        return (None, 0)
    sdate = f"{year}-{month:02d}-01"
    edate = f"{year}-{month:02d}-{through_day:02d}"
    if _acis_cb.is_open():
        _log.info(
            "[CircuitBreaker] acis_stndata circuit open — skipping month-to-date fetch"
        )
        return (None, 0)
    payload = {
        "sid": sid,
        "sdate": sdate,
        "edate": edate,
        "elems": [{"name": "pcpn", "interval": "dly", "duration": "dly"}],
    }
    try:
        resp = _session.post(ACIS_STNDATA_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        _acis_cb.record_success()
    except Exception as exc:
        _acis_cb.record_failure()
        _log.warning(
            "fetch_month_to_date_actual: ACIS fetch failed for sid=%s: %s", sid, exc
        )
        return (None, 0)

    total = 0.0
    n_missing = 0
    for _date_str, raw_val in data:
        val = _parse_pcpn_value(raw_val)
        if val is None:
            n_missing += 1
        else:
            total += val
    return (total, n_missing)


def _cache_path(sid: str) -> Path:
    return DATA_DIR / f"acis_pcpn_{sid}.json"


def _cache_is_stale(cache: Path) -> bool:
    if not cache.exists():
        return True
    return (time.time() - cache.stat().st_mtime) > CACHE_MAX_AGE


_MEM_CACHE: dict[str, dict] = {}


def fetch_historical_daily(
    sid: str, years: int = HISTORY_YEARS, force: bool = False
) -> dict[int, dict[int, float | None]] | None:
    """One POST call covering the full `years`-year daily history, disk-
    cached so one fetch serves every (month, city) query for that station,
    not just the one currently being analyzed. Returns
    {year: {ordinal_day_of_year: value_or_None}}, or None on total fetch
    failure with no usable cache."""
    if not force and sid in _MEM_CACHE:
        return _MEM_CACHE[sid]

    cache = _cache_path(sid)
    if cache.exists() and not force and not _cache_is_stale(cache):
        try:
            with open(cache) as f:
                raw = json.load(f)
            parsed = {
                int(y): {int(d): v for d, v in days.items()} for y, days in raw.items()
            }
            _MEM_CACHE[sid] = parsed
            return parsed
        except Exception as exc:
            _log.warning(
                "fetch_historical_daily: cache read failed for sid=%s: %s", sid, exc
            )

    from utils import utc_today as _utc_today

    end_year = _utc_today().year - 1
    start_year = end_year - years + 1

    if _acis_cb.is_open():
        _log.info(
            "[CircuitBreaker] acis_stndata circuit open — skipping historical fetch"
        )
        return _load_stale_cache_or_none(cache, sid)

    payload = {
        "sid": sid,
        "sdate": f"{start_year}-01-01",
        "edate": f"{end_year}-12-31",
        "elems": [{"name": "pcpn", "interval": "dly", "duration": "dly"}],
    }
    try:
        resp = _session.post(ACIS_STNDATA_URL, json=payload, timeout=30)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        _acis_cb.record_success()
    except Exception as exc:
        _acis_cb.record_failure()
        _log.warning(
            "fetch_historical_daily: ACIS fetch failed for sid=%s: %s", sid, exc
        )
        return _load_stale_cache_or_none(cache, sid)

    result: dict[int, dict[int, float | None]] = {}
    for date_str, raw_val in rows:
        try:
            y, m, d = (int(x) for x in date_str.split("-"))
        except (ValueError, AttributeError):
            continue
        result.setdefault(y, {})[m * 100 + d] = _parse_pcpn_value(raw_val)

    try:
        serializable = {
            str(y): {str(k): v for k, v in days.items()} for y, days in result.items()
        }
        safe_io.atomic_write_json(serializable, cache)
    except Exception as exc:
        _log.warning(
            "fetch_historical_daily: cache write failed for sid=%s: %s", sid, exc
        )

    _MEM_CACHE[sid] = result
    return result


def _load_stale_cache_or_none(
    cache: Path, sid: str
) -> dict[int, dict[int, float | None]] | None:
    if not cache.exists():
        _log.warning(
            "fetch_historical_daily: API failed for sid=%s and no cache exists", sid
        )
        return None
    try:
        with open(cache) as f:
            raw = json.load(f)
        parsed = {
            int(y): {int(d): v for d, v in days.items()} for y, days in raw.items()
        }
        _MEM_CACHE[sid] = parsed
        return parsed
    except Exception as exc:
        _log.warning(
            "fetch_historical_daily: stale cache read failed for sid=%s: %s", sid, exc
        )
        return None


def fetch_seasonal_precip_mean_mm(
    lat: float, lon: float, tz: str, year: int, month: int
) -> float | None:
    """GET Open-Meteo Seasonal (monthly=precipitation_mean -- NOT
    precipitation_sum, which 400s, confirmed live). Returns the ECMWF SEAS5
    monthly-mean precip in mm for (year, month), or None on any failure or
    if the target month is outside the API's ~6-month forecast window.
    Best-effort: never fatal to the caller if unavailable."""
    if _om_seasonal_cb.is_open():
        _log.info(
            "[CircuitBreaker] open_meteo_seasonal circuit open — skipping seasonal fetch"
        )
        return None
    params = {
        "latitude": str(lat),
        "longitude": str(lon),
        "monthly": "precipitation_mean",
        "timezone": tz,
    }
    try:
        resp = _session.get(OPEN_METEO_SEASONAL_URL, params=params, timeout=10)
        resp.raise_for_status()
        monthly = resp.json().get("monthly", {})
        _om_seasonal_cb.record_success()
    except Exception as exc:
        _om_seasonal_cb.record_failure()
        _log.info("fetch_seasonal_precip_mean_mm: fetch failed: %s", exc)
        return None

    times = monthly.get("time", [])
    values = monthly.get("precipitation_mean", [])
    target = f"{year:04d}-{month:02d}"
    for t, v in zip(times, values):
        if isinstance(t, str) and t.startswith(target) and v is not None:
            return float(v)
    return None


def historical_remaining_and_full_month_sums(
    history: dict[int, dict[int, float | None]],
    month: int,
    remaining_start_day: int,
    days_in_month: int,
    max_missing_frac: float = 0.20,
) -> tuple[list[float], list[float]]:
    """For each historical year present in `history`, sum the
    [remaining_start_day, days_in_month] daily values (the bootstrap's
    "remaining days" analog) AND separately the [1, days_in_month] full-
    month sum (used only for the seasonal-tilt ratio). A year is EXCLUDED
    from both lists if more than max_missing_frac of its days-in-range are
    missing. Returns (remaining_sums, full_month_sums), same length,
    index-aligned per included year."""
    remaining_sums: list[float] = []
    full_month_sums: list[float] = []

    remaining_range = range(remaining_start_day, days_in_month + 1)
    full_range = range(1, days_in_month + 1)

    for _year, days in history.items():
        remaining_vals = [days.get(month * 100 + d) for d in remaining_range]
        full_vals = [days.get(month * 100 + d) for d in full_range]

        if remaining_vals:
            n_missing_remaining = sum(1 for v in remaining_vals if v is None)
            if n_missing_remaining / len(remaining_vals) > max_missing_frac:
                continue
            remaining_sum = sum(v for v in remaining_vals if v is not None)
        else:
            remaining_sum = 0.0

        n_missing_full = sum(1 for v in full_vals if v is None)
        if not full_vals or n_missing_full / len(full_vals) > max_missing_frac:
            continue
        full_sum = sum(v for v in full_vals if v is not None)

        remaining_sums.append(remaining_sum)
        full_month_sums.append(full_sum)

    return remaining_sums, full_month_sums


def bootstrap_ci_month_total(
    remaining_sums: list[float],
    month_to_date_actual: float,
    threshold: float,
    n: int = 500,
) -> tuple[float, float]:
    """Mirrors weather_markets._bootstrap_ci_precip's exact resampling
    shape: n resamples-with-replacement of remaining_sums, each resample's
    exceedance fraction over (month_to_date_actual + resampled remaining),
    sorted, 5th/95th percentile returned. Returns (0.0, 1.0) if fewer than
    15 historical years are available (too few to trust a CI)."""
    if len(remaining_sums) < 15:
        return (0.0, 1.0)

    def prob_from(sample: list[float]) -> float:
        return sum(1 for s in sample if month_to_date_actual + s > threshold) / len(
            sample
        )

    k = len(remaining_sums)
    boot = sorted(prob_from(random.choices(remaining_sums, k=k)) for _ in range(n))
    return (boot[min(int(n * 0.05), n - 1)], boot[min(int(n * 0.95), n - 1)])


def apply_seasonal_tilt(
    remaining_sums: list[float],
    full_month_sums: list[float],
    seasonal_mean_mm: float | None,
    tilt_strength: float = 0.5,
    ratio_clamp: tuple[float, float] = (0.5, 2.0),
) -> tuple[list[float], bool]:
    """Returns (possibly-shifted remaining_sums, tilt_applied). No-ops
    (tilt_applied=False) if seasonal_mean_mm is None, historical data is
    too thin, or the historical full-month mean is non-positive. Otherwise
    an ADDITIVE shift only (preserves the empirical distribution's shape,
    only moves its central tendency), damped by tilt_strength and clamped
    to +/-25% of the mean -- bounds worst-case tilt error since this is a
    mean-only signal with no per-member spread of its own."""
    if seasonal_mean_mm is None or len(full_month_sums) < 15:
        return (remaining_sums, False)

    clim_full_month_mean_in = sum(full_month_sums) / len(full_month_sums)
    if clim_full_month_mean_in <= 0:
        return (remaining_sums, False)

    clim_full_month_mean_mm = clim_full_month_mean_in * 25.4
    if clim_full_month_mean_mm <= 0:
        return (remaining_sums, False)

    raw_ratio = seasonal_mean_mm / clim_full_month_mean_mm
    ratio = max(ratio_clamp[0], min(ratio_clamp[1], raw_ratio))

    mean_remaining = (
        sum(remaining_sums) / len(remaining_sums) if remaining_sums else 0.0
    )
    raw_shift_in = (ratio - 1.0) * mean_remaining
    damped_shift_in = raw_shift_in * tilt_strength
    max_shift = abs(mean_remaining) * 0.25
    damped_shift_in = max(-max_shift, min(max_shift, damped_shift_in))

    shifted = [max(0.0, s + damped_shift_in) for s in remaining_sums]
    return (shifted, True)
