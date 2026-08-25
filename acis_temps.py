"""
NOAA ACIS StnData historical daily MAXIMUM TEMPERATURE (`maxt`) fetch, plus
the day-of-year anomaly and pairwise city-correlation math built on top of it
(batch-69 item 2 / panel A5).

Mirrors acis_precip.py's fetch/cache/circuit-breaker/fail-open module shape
exactly -- same endpoint, same 30-year `HISTORY_YEARS` convention, same
`{year: {mmdd: value}}` return shape, same "an empty `data` array is a fetch
failure, not an empty result to cache" guard. Only the element name
(`maxt` instead of `pcpn`), the sentinel handling, the cache filename, and
the `emergency_copy=False` on the cache write differ; see `_parse_maxt_value`
for why the sentinel rules are NOT shared. The emergency-copy choice is
deliberate too (opus-review-noted, L-12): this is a rebuildable 30-day cache,
and the default True would leave a file in data/.emergency/ that cron's
check_emergency_copies() re-alerts on every cycle until an operator deletes
it by hand.

WHY AN OFFLINE TABLE AT ALL. tracker.get_recent_city_correlations() already
computes pairwise city correlations, but from our OWN settled traded markets
only. Measured against the live database on 2026-08-25 it returns **zero
pairs** at every lookback tried (60d, 365d, 3650d): 71 joined multi-day HIGH
rows spread across 20 cities, at most 9 distinct settlement dates for any one
city, and no city PAIR sharing the >=5 common dates its own `min_pairs` floor
requires. It is not thin, it is empty, and monte_carlo.py -- its only
consumer -- has been silently falling back for its entire life. Traded
settlements will not become dense enough to fix that on any useful horizon,
so the correlation input has to come from station history instead.

It also correlates RAW temperatures inside a 60-day window rather than
anomalies, which folds the shared seasonal trend into the coefficient and
biases every pair upward. This module correlates day-of-year ANOMALIES
instead -- matching what paper.py's hardcoded `_CITY_PAIR_CORR` table already
claims to be ("approximate correlations of daily high-temperature
anomalies"), so the empirical and hardcoded numbers are directly comparable.

**Nothing here feeds sizing.** paper.covariance_kelly_scale/corr_kelly_scale
and their `_CITY_PAIR_CORR` input are untouched by batch-69; this module and
its table are measurement and display only, so a later swap can be argued
from a number instead of a guess (confirmed via AskUserQuestion, 2026-08-25).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date
from pathlib import Path

import requests

import safe_io
from circuit_breaker import CircuitBreaker
from paths import DATA_DIR

_log = logging.getLogger(__name__)

# Distinct breaker name from acis_precip's "acis_stndata": both talk to the
# same host, but a `maxt` recompute is a rare manual operation while pcpn is
# fetched inside the live scan cycle. Sharing one breaker would let a
# 21-city recompute against a flaky ACIS trip the breaker that the rain
# model depends on mid-cycle, for a job nothing time-sensitive is waiting on.
_acis_cb = CircuitBreaker(
    name="acis_stndata_maxt", failure_threshold=5, recovery_timeout=600
)

_session = requests.Session()

ACIS_STNDATA_URL = "http://data.rcc-acis.org/StnData"

HISTORY_YEARS = 30  # matches acis_precip.HISTORY_YEARS / acis_snow.HISTORY_YEARS
CACHE_MAX_AGE = 30 * 24 * 3600  # 30 days, same as acis_precip's CACHE_MAX_AGE

# Half-width of the seasonal window, in days, used by compute_city_correlations.
# +/-45 days around a month's midpoint -- wide enough for a usable sample per
# pair (~30 years x ~91 days), narrow enough that a July window is not being
# told about January by a January-vs-July co-movement.
SEASONAL_WINDOW_DAYS = 45

# Minimum paired observations before a (pair, window) correlation is stored at
# all. opus-review-corrected (L-13): the reason is NOT that consumers cannot
# tell a thin coefficient from a thick one -- `n_obs` is a stored column,
# returned by every query and surfaced in the panel's pair rows. The real
# reason is that a correlation built from a handful of overlapping days is
# dominated by sampling noise: even its SIGN is unreliable, so storing it
# invites a reader to act on a number that means nothing. Omitting it says
# "unmeasured", which is true.
MIN_PAIRED_OBS = 30

_MEM_CACHE: dict[str, dict[int, dict[int, float | None]]] = {}

# Cities the most recent compute_city_correlations() call could not measure.
# Module-level rather than part of the return value so compute_city_correlations
# keeps its "list of storable rows" signature; recompute_city_correlations reads
# it to report cities_measured/cities_skipped (opus-review-caught, M-7).
_last_skipped_cities: list[str] = []


def _parse_maxt_value(raw: str | float | None) -> float | None:
    """Parse one ACIS `maxt` daily value (degrees F). Returns None for
    missing/unparseable.

    Deliberately NOT shared with acis_precip._parse_pcpn_value, whose "T"
    (trace) branch returns **0.0**. For precipitation 0.0 is the right
    reading of a trace. For a temperature, 0.0 is a real and perfectly
    plausible daily high, so mapping any sentinel onto it would inject a
    fabricated -- and in winter, entirely believable -- observation into the
    anomaly series rather than a gap the correlation math skips. Every
    non-numeric sentinel is missing here, no exceptions.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    s = str(raw).strip()
    if s in ("M", "T", "S", "A", ""):
        return None
    try:
        return float(s)
    except ValueError:
        _log.warning("_parse_maxt_value: unparseable ACIS maxt value %r", raw)
        return None


def _cache_path(sid: str, years: int = HISTORY_YEARS) -> Path:
    """Cache filename, keyed by BOTH station and lookback.

    opus-review-caught (M-6): keyed on `sid` alone, a cached 30-year file was
    returned verbatim for a `years=5` request -- and compute_city_correlations
    then stored `lookback_years=5` alongside an n_obs only 30 years of data
    can produce. The row claimed a provenance it did not have, defeating the
    argument upsert_city_correlations makes for protecting that column.

    The default keeps the historical filename for the 30-year case, so
    existing on-disk caches are still used rather than silently orphaned.
    """
    if years == HISTORY_YEARS:
        return DATA_DIR / f"acis_maxt_{sid}.json"
    return DATA_DIR / f"acis_maxt_{sid}_{years}y.json"


def _cache_is_stale(cache: Path) -> bool:
    import time as _time

    try:
        return (_time.time() - cache.stat().st_mtime) > CACHE_MAX_AGE
    except OSError:
        return True


def _load_stale_cache_or_none(
    cache: Path, sid: str
) -> dict[int, dict[int, float | None]] | None:
    """Fail-open fallback: return whatever is on disk even if stale.

    Deliberately does NOT populate _MEM_CACHE, for exactly the reason
    acis_precip._load_stale_cache_or_none documents at length -- _MEM_CACHE
    has no TTL and is checked before the staleness gate, so caching a
    stale-fallback result here would pin it for the whole process lifetime
    and the next call would never re-attempt the network or re-check the
    circuit breaker.
    """
    if not cache.exists():
        return None
    try:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        return {int(y): {int(d): v for d, v in days.items()} for y, days in raw.items()}
    except Exception as exc:
        _log.warning(
            "_load_stale_cache_or_none: stale cache read failed for sid=%s: %s",
            sid,
            exc,
        )
        return None


def fetch_historical_daily_maxt(
    sid: str, years: int = HISTORY_YEARS, force: bool = False
) -> dict[int, dict[int, float | None]] | None:
    """One POST covering the full `years`-year daily maxt history, disk-cached.

    Returns {year: {mmdd: value_or_None}} where mmdd is the integer
    ``month * 100 + day`` key acis_precip.fetch_historical_daily already
    uses, or None on total fetch failure with no usable cache.
    """
    # Mem-cache key carries the lookback for the same reason the disk key
    # does (M-6) -- otherwise a years=5 call is served a cached 30-year dict.
    mem_key = f"{sid}:{years}"
    if not force and mem_key in _MEM_CACHE:
        return _MEM_CACHE[mem_key]

    cache = _cache_path(sid, years)
    if cache.exists() and not force and not _cache_is_stale(cache):
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            parsed = {
                int(y): {int(d): v for d, v in days.items()} for y, days in raw.items()
            }
            _MEM_CACHE[mem_key] = parsed
            return parsed
        except Exception as exc:
            _log.warning(
                "fetch_historical_daily_maxt: cache read failed for sid=%s: %s",
                sid,
                exc,
            )

    from utils import utc_today as _utc_today

    end_year = _utc_today().year - 1
    start_year = end_year - years + 1

    if _acis_cb.is_open():
        _log.info(
            "[CircuitBreaker] acis_stndata_maxt circuit open — skipping maxt fetch"
        )
        return _load_stale_cache_or_none(cache, sid)

    payload = {
        "sid": sid,
        "sdate": f"{start_year}-01-01",
        "edate": f"{end_year}-12-31",
        "elems": [{"name": "maxt", "interval": "dly", "duration": "dly"}],
    }
    try:
        resp = _session.post(ACIS_STNDATA_URL, json=payload, timeout=30)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        _acis_cb.record_success()
    except Exception as exc:
        _acis_cb.record_failure()
        _log.warning(
            "fetch_historical_daily_maxt: ACIS fetch failed for sid=%s: %s", sid, exc
        )
        return _load_stale_cache_or_none(cache, sid)

    result: dict[int, dict[int, float | None]] = {}
    for row in rows:
        try:
            date_str, raw_val = row[0], row[1]
            y, m, d = (int(x) for x in str(date_str).split("-"))
        except (ValueError, AttributeError, IndexError, TypeError):
            continue
        result.setdefault(y, {})[m * 100 + d] = _parse_maxt_value(raw_val)

    # Same guard acis_precip.fetch_historical_daily carries: ACIS answers HTTP
    # 200 with an empty "data" array for a transient or unresolvable sid.
    # That parses to {} -- truthy-falsy, not None -- so without this it would
    # bypass the fail-open path above and get written to BOTH the 30-day disk
    # cache and the process-lifetime mem cache, poisoning both from one
    # transient response.
    if not result:
        _log.warning(
            "fetch_historical_daily_maxt: ACIS returned no usable rows for sid=%s "
            "-- falling back to stale cache instead of caching an empty result",
            sid,
        )
        return _load_stale_cache_or_none(cache, sid)

    try:
        serializable = {
            str(y): {str(k): v for k, v in days.items()} for y, days in result.items()
        }
        safe_io.atomic_write_json(serializable, cache, emergency_copy=False)
    except Exception as exc:
        _log.warning(
            "fetch_historical_daily_maxt: cache write failed for sid=%s: %s", sid, exc
        )

    _MEM_CACHE[mem_key] = result
    return result


def _mmdd_to_doy(mmdd: int) -> int | None:
    """Map an integer mmdd key to a 1-365 day-of-year using a fixed NON-leap
    reference year, so the same calendar date always gets the same index no
    matter which of the 30 years it came from.

    Feb 29 returns None and is dropped by every caller. Keeping it would
    shift every subsequent day-of-year by one in leap years relative to
    non-leap years, smearing the climatological mean this index exists to
    look up. Losing ~7 observations per city out of ~11,000 is the cheaper
    error by a wide margin.
    """
    m, d = divmod(mmdd, 100)
    if m == 2 and d == 29:
        return None
    try:
        return date(2001, m, d).timetuple().tm_yday  # 2001 is not a leap year
    except ValueError:
        return None


def daily_anomalies(
    history: dict[int, dict[int, float | None]], min_years_per_day: int = 5
) -> dict[tuple[int, int], float]:
    """Convert a raw {year: {mmdd: value}} history into day-of-year anomalies.

    The climatological mean is computed PER CALENDAR DAY across all available
    years, then subtracted from that day's observation. Correlating raw highs
    instead would mostly measure the fact that both cities are warm in July
    and cold in January -- the shared seasonal cycle, not the co-movement of
    departures from it, which is the quantity that actually determines
    whether two open positions are one bet.

    `min_years_per_day` drops calendar days whose climatological mean rests on
    too few years to be meaningful; such a day's "anomaly" is dominated by the
    noise in its own reference value.

    Returns {(year, mmdd): anomaly_degrees_f}.
    """
    by_day: dict[int, list[float]] = {}
    for _year, days in history.items():
        for mmdd, val in days.items():
            if val is None or _mmdd_to_doy(mmdd) is None:
                continue
            by_day.setdefault(mmdd, []).append(float(val))

    climo = {
        mmdd: sum(vals) / len(vals)
        for mmdd, vals in by_day.items()
        if len(vals) >= min_years_per_day
    }

    anomalies: dict[tuple[int, int], float] = {}
    for year, days in history.items():
        for mmdd, val in days.items():
            if val is None or mmdd not in climo:
                continue
            anomalies[(year, mmdd)] = float(val) - climo[mmdd]
    return anomalies


def _in_seasonal_window(doy: int, centre_doy: int, half_width: int) -> bool:
    """Circular day-of-year membership test, so a December window correctly
    includes January and a January window correctly includes December rather
    than being silently truncated at the year boundary."""
    diff = abs(doy - centre_doy)
    return min(diff, 365 - diff) <= half_width


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation. Returns None when either series has zero
    variance, rather than raising or silently emitting 0.0 -- a constant
    series has an undefined correlation, which is a different statement from
    "these two are uncorrelated"."""
    # opus-review-caught (L-4): `my = sum(ys) / n` used len(xs), and zip()
    # truncates -- so mismatched inputs returned a plausible-looking but wrong
    # coefficient instead of failing. Unreachable from
    # compute_city_correlations (which builds both lists in lockstep), but
    # this is a module-level helper with no guard of its own.
    if len(xs) != len(ys):
        return None
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    if dx <= 0 or dy <= 0:
        return None
    return num / (dx * dy)


def month_window_key(month: int) -> str:
    """Window key stored in city_correlations.window_key for a calendar month.

    Correlations move seasonally, not daily, so the table is keyed by month
    (12 windows) and recomputed monthly at most -- there is nothing to gain
    from a finer grid and a full recompute is 21 ACIS round trips.
    """
    return f"m{month:02d}"


def compute_city_correlations(
    cities: list[str],
    lookback_years: int = HISTORY_YEARS,
    half_width: int = SEASONAL_WINDOW_DAYS,
    min_obs: int = MIN_PAIRED_OBS,
    force: bool = False,
) -> list[dict]:
    """Compute every (city pair, month window) anomaly correlation.

    Returns a list of dicts ready for tracker.upsert_city_correlations():
    {"city_a", "city_b", "window_key", "corr", "n_obs", "lookback_years"},
    with city_a < city_b so a pair has exactly one canonical row.

    Cities whose history cannot be fetched at all are skipped with a warning
    rather than aborting the whole recompute -- a partial table is strictly
    more useful than none, and the skipped pairs are simply absent (not
    stored as 0.0, which a consumer would read as "measured, uncorrelated").
    """
    from acis_precip import _station_sid_for_city

    # Cleared UP FRONT as well as at the end: if this function raises midway
    # (an ACIS client error, a corrupt cache), the previous run's skip list
    # would otherwise still be sitting in the module global for
    # recompute_city_correlations to report as if it were this run's. Empty
    # is the honest answer for a run that did not finish.
    #
    # Module state, so this is only correct for one compute at a time. The
    # single exposed caller (POST /api/city-correlations/recompute) holds a
    # lock for exactly that reason; a direct concurrent call from two threads
    # would interleave here, which this project's single-operator model does
    # not do.
    _last_skipped_cities.clear()

    anomalies_by_city: dict[str, dict[tuple[int, int], float]] = {}
    skipped: list[str] = []
    for city in cities:
        sid = _station_sid_for_city(city)
        if not sid:
            _log.warning("compute_city_correlations: no ACIS sid for city %r", city)
            skipped.append(city)
            continue
        history = fetch_historical_daily_maxt(sid, years=lookback_years, force=force)
        if not history:
            _log.warning(
                "compute_city_correlations: no maxt history for city %r (sid=%s)",
                city,
                sid,
            )
            skipped.append(city)
            continue
        anom = daily_anomalies(history)
        if anom:
            anomalies_by_city[city] = anom
        else:
            skipped.append(city)
    if skipped:
        # opus-review-caught (M-7): cities were skipped with a log line only,
        # so a recompute during an ACIS outage -- the circuit breaker opens
        # after 5 consecutive failures, which is the EXPECTED shape of one --
        # returned a result that read as a full success. Surface it.
        _log.warning(
            "compute_city_correlations: %d of %d cities produced no usable "
            "history and were skipped: %s",
            len(skipped),
            len(cities),
            sorted(set(skipped)),
        )
    _last_skipped_cities.clear()
    _last_skipped_cities.extend(sorted(set(skipped)))

    # Precompute each observation's day-of-year once rather than once per
    # (pair, month) -- 12 months x ~210 pairs would otherwise recompute the
    # same ~11,000 lookups per city 2,520 times.
    doy_cache: dict[int, int] = {}
    for anom in anomalies_by_city.values():
        for _year, mmdd in anom:
            if mmdd not in doy_cache:
                doy = _mmdd_to_doy(mmdd)
                if doy is not None:
                    doy_cache[mmdd] = doy

    rows: list[dict] = []
    present = sorted(anomalies_by_city)
    for i, city_a in enumerate(present):
        for city_b in present[i + 1 :]:
            anom_a = anomalies_by_city[city_a]
            anom_b = anomalies_by_city[city_b]
            common = anom_a.keys() & anom_b.keys()
            if not common:
                continue
            for month in range(1, 13):
                centre = date(2001, month, 15).timetuple().tm_yday
                xs: list[float] = []
                ys: list[float] = []
                for key in common:
                    doy = doy_cache.get(key[1])
                    if doy is None or not _in_seasonal_window(doy, centre, half_width):
                        continue
                    xs.append(anom_a[key])
                    ys.append(anom_b[key])
                if len(xs) < min_obs:
                    continue
                corr = _pearson(xs, ys)
                if corr is None:
                    continue
                rows.append(
                    {
                        "city_a": city_a,
                        "city_b": city_b,
                        "window_key": month_window_key(month),
                        "corr": round(corr, 4),
                        "n_obs": len(xs),
                        "lookback_years": lookback_years,
                    }
                )
    return rows


def recompute_city_correlations(
    cities: list[str] | None = None,
    lookback_years: int = HISTORY_YEARS,
    force: bool = False,
) -> dict:
    """Fetch, compute, and STORE the full city-correlation table.

    The operator-facing entry point for panel A5's offline table. Correlations
    move seasonally, not daily, so this is meant to run monthly at most --
    there is deliberately no scheduler entry and no automatic trigger.

    `cities` defaults to weather_markets.TEMPERATURE_MARKET_CITIES. `force`
    bypasses the 30-day ACIS disk cache.

    Returns {"cities", "pairs", "rows_written", "windows"}.
    """
    if cities is None:
        from weather_markets import TEMPERATURE_MARKET_CITIES

        cities = sorted(TEMPERATURE_MARKET_CITIES)

    rows = compute_city_correlations(cities, lookback_years=lookback_years, force=force)
    from tracker import upsert_city_correlations

    written = upsert_city_correlations(rows)
    skipped = list(_last_skipped_cities)
    # round-2 opus review (L-9): count DISTINCT cities. `skipped` is already
    # de-duplicated, so a caller passing the same city twice would otherwise
    # report cities_measured one too high.
    n_requested = len(set(cities))
    result = {
        # opus-review-caught (M-7): this used to report only len(cities), the
        # REQUESTED count, so a run where 15 of 20 ACIS fetches failed still
        # answered {"cities": 20} with no error field and no way for an
        # operator to learn which cities are missing from the table.
        "cities_requested": n_requested,
        "cities_measured": n_requested - len(skipped),
        "cities_skipped": skipped,
        "partial": bool(skipped),
        "pairs": len({(r["city_a"], r["city_b"]) for r in rows}),
        "windows": len({r["window_key"] for r in rows}),
        "rows_written": written,
        "lookback_years": lookback_years,
    }
    _log.info("recompute_city_correlations: %s", result)
    return result
