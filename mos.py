"""
NOAA MOS (Model Output Statistics) via Iowa Environmental Mesonet API.
Station-specific post-processed forecasts — same ASOS stations Kalshi settles on.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta

import requests
from requests.adapters import HTTPAdapter, Retry

from forecast_cache import ForecastCache
from metar import MARKET_STATION_MAP as _MARKET_STATION_MAP
from utils import utc_today as _utc_today

_log = logging.getLogger(__name__)

# IEM MOS API endpoint
_MOS_URL = "https://mesonet.agron.iastate.edu/api/1/mos.json"

# Cities with NOAA MOS coverage wired up (a deliberate subset — not all 20
# traded cities; MOS post-processing adds the most value for these, Denver's
# mountain terrain in particular). Station codes are derived from
# metar.MARKET_STATION_MAP (single source of truth) instead of a second
# hand-typed copy — that copy previously used short-code keys ("CHI", "LAX")
# that never matched real callers' full city names, silently zeroing out MOS
# signal for every city but NYC until fixed.
_MOS_CITIES: list[str] = ["NYC", "Miami", "Chicago", "LA", "Dallas", "Denver"]
_CITY_STATION: dict[str, str] = {
    city: _MARKET_STATION_MAP[city] for city in _MOS_CITIES
}

# MOS verified RMSE by days_out (°F). Used as sigma in probability calculations
# instead of the generic _forecast_uncertainty() table. Source: NOAA MOS verification.
MOS_SIGMA: dict[str, dict[int, float]] = {
    "GFS": {0: 2.0, 1: 2.5, 2: 3.2, 3: 4.0, 4: 5.0, 5: 5.5},
    "NAM": {0: 1.8, 1: 2.3, 2: 3.0},  # NAM only reliable out to ~60h
}

# Shared session with retry
_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=1,  # was 3 — Retry(total=3) + timeout=10 → 43 s/call; total=1 caps at ~21 s
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
        )
    ),
)


# In-process cache: (station, date_iso, model) → result (negative-cached as
# None on fetch failure). MOS updates every ~6 h; 1-hour TTL prevents
# redundant HTTP calls when cmd_cron / analyze_trade loop over many markets
# for the same cities. Migrated to the shared ForecastCache 2026-07-19
# (backlog.txt "ForecastCache EXISTS, BUT ~14 HAND-ROLLED TTL DICTS..."). A
# real (negative-cached) None value is indistinguishable from "no entry" via
# plain .get() alone, so both read sites below use get_with_ts()'s explicit
# hit flag instead.
_MOS_CACHE_TTL = 3600  # 1 hour
_MOS_CACHE: ForecastCache[dict | None] = ForecastCache(ttl_secs=_MOS_CACHE_TTL)


def get_mos_station(city: str) -> str | None:
    """Return the ASOS station code for a city, or None if unknown."""
    return _CITY_STATION.get(city)


def is_mos_cached(station: str, target_date: date | None) -> bool:
    """Return True if a fresh MOS cache entry exists for this station/date (no network call).

    Used by analyze_trade to skip the MOS fetch entirely when the pre-warm didn't
    cover this city/date, avoiding slow per-market network calls during the analysis
    phase.  Returns False if the cache entry is missing or has expired.
    """
    if not station or not target_date:
        return False
    date_str = (
        target_date.isoformat()
        if hasattr(target_date, "isoformat")
        else str(target_date)
    )
    for model in ("NAM", "GFS"):
        key = (station.upper(), date_str, model)
        _, hit, _ = _MOS_CACHE.get_with_ts(key)
        if hit:
            return True
    return False


_MOS_SPECIAL_CODES = frozenset(("M", "m", "T", "t", "", "N/A"))


def _parse_temp(value) -> float | None:
    """Parse MOS temperature field, handling ASOS special codes."""
    if value is None:
        return None
    s = str(value).strip()
    if s in _MOS_SPECIAL_CODES:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        _log.debug("Unparseable MOS temp value: %r", value)
        return None


def fetch_mos(
    station: str,
    target_date: date | None = None,
    model: str = "GFS",
) -> dict | None:
    """
    Fetch MOS forecast for a station from the IEM API.

    Args:
        station: ASOS station code (e.g. "KNYC")
        target_date: Date to get forecast for (default: tomorrow)
        model: MOS model ("GFS" or "NAM")

    Returns:
        dict with keys:
          - max_temp_f: float, highest temperature for the target date
          - min_temp_f: float | None, lowest temperature for the target date
          - n_hours: int, number of hourly rows found for that date
          - station: str
          - model: str
          - sigma: float, MOS-specific RMSE for this days_out (B1)
        or None on any failure.
    """
    if target_date is None:
        target_date = datetime.now(UTC).date() + timedelta(days=1)

    date_str = target_date.isoformat()

    # Check cache before hitting the network.
    _cache_key = (station.upper(), date_str, model.upper())
    _cached_result, _cache_hit, _ = _MOS_CACHE.get_with_ts(_cache_key)
    if _cache_hit:
        return _cached_result

    try:
        resp = _session.get(
            _MOS_URL,
            params={"station": station.upper(), "model": model},
            timeout=(5, 10),  # (connect, read) — 5s cap on SSL handshake
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        _log.debug("fetch_mos(%s): %s", station, exc)
        _MOS_CACHE.set(_cache_key, None)
        return None

    rows = payload.get("data", [])
    if not rows:
        _MOS_CACHE.set(_cache_key, None)
        return None

    # Filter to rows on the target date (ftime starts with date_str)
    day_rows = [r for r in rows if str(r.get("ftime", "")).startswith(date_str)]
    if not day_rows:
        _MOS_CACHE.set(_cache_key, None)
        return None

    temps: list[float] = [
        t for r in day_rows if (t := _parse_temp(r.get("tmp"))) is not None
    ]
    if not temps:
        _MOS_CACHE.set(_cache_key, None)
        return None

    # B1: compute days_out and look up MOS-specific RMSE as sigma
    days_out = max(0, (target_date - _utc_today()).days)
    sigma_table = MOS_SIGMA.get(model.upper(), MOS_SIGMA["GFS"])
    max_key = max(sigma_table.keys())
    sigma = sigma_table.get(days_out, sigma_table[max_key])

    result = {
        "max_temp_f": float(max(temps)),
        "min_temp_f": float(min(temps)),
        "n_hours": len(day_rows),
        "station": station.upper(),
        "model": model,
        "sigma": sigma,
    }
    _MOS_CACHE.set(_cache_key, result)
    return result


def fetch_mos_best(
    station: str,
    target_date: date | None = None,
) -> dict | None:
    """
    B2: Fetch MOS using the best available model for the given days_out.
    For days_out <= 1: try NAM first (higher resolution), fall back to GFS.
    For days_out >= 2: use GFS only (NAM is unreliable beyond ~60h).

    Returns the result dict from fetch_mos(), or None if all models fail.
    """
    if target_date is None:
        target_date = datetime.now(UTC).date() + timedelta(days=1)

    days_out = max(0, (target_date - _utc_today()).days)

    if days_out <= 1:
        # Try NAM first — tighter RMSE for same-day and next-day markets
        result = fetch_mos(station, target_date, model="NAM")
        if result is not None:
            return result

    # GFS fallback (or primary for days_out >= 2)
    return fetch_mos(station, target_date, model="GFS")


# ── NBS (National Blend of Models MOS-style bulletin) ───────────────────────
# Covers every ASOS station (unlike GFS/NAM MOS's 6-city _MOS_CITIES subset),
# so this deliberately does NOT go through _MARKET_STATION_MAP/_MOS_CITIES --
# callers pass any station code directly (see weather_markets.fetch_temperature_nbm,
# which resolves it via _metar_station_for_city for all 20 traded cities).
#
# NBS's raw feed does not carry a per-hour running daily max/min the way
# fetch_mos()'s naive scan-all-hourly-tmp approach assumes. The field that
# once seemed like the right one (Open-Meteo/IEM's renamed "n_x", the old
# raw-text "x_n" column) is empty on every live-checked NBS row. The field
# that actually carries the daily extreme is "txn", and it is populated only
# on rows whose forecast-valid time (ftime) lands exactly on a 00Z or 12Z
# boundary -- a single alternating "X/N" column matching the raw NWS MOS
# bulletin convention, not a dedicated always-present field.
#
# Live-verified 2026-07-17 across all four CONUS timezones (KNYC/Eastern,
# KMDW/Central, KDEN/Mountain, KLAX/Pacific): the 00Z-ending 12h period is
# ALWAYS the higher (daytime max) value and the 12Z-ending period is ALWAYS
# the lower (nighttime min) value, station-timezone-independent. This isn't
# a coincidence -- CONUS UTC offsets are always whole hours, so a station's
# ~12h local daytime window (roughly 6am-6pm) always falls entirely inside
# either the 00Z-ending or the 12Z-ending UTC period, never split across
# both, for every mainland US timezone.
_NBS_CACHE: dict[tuple, tuple[dict | None, float]] = {}
_NBS_CACHE_TTL = 3600  # 1 hour, matches _MOS_CACHE_TTL


def _fetch_nbs_daily_extremes(station: str, city_tz: str) -> dict[tuple, float] | None:
    """Fetch and parse every available NBS txn value for a station into
    {(local_date, "max"|"min"): temp_f}. One API call returns the station's
    full available NBS horizon (~3 days), so this is cached per (station,
    city_tz) rather than per target date.

    Returns None on any fetch failure or if the station has zero txn rows
    (some stations/cycles have none -- see fetch_nbm_iem's docstring).
    """
    from zoneinfo import ZoneInfo

    cache_key = (station.upper(), city_tz)
    cached = _NBS_CACHE.get(cache_key)
    if cached is not None:
        result, ts = cached
        if time.monotonic() - ts < _NBS_CACHE_TTL:
            return result

    try:
        resp = _session.get(
            _MOS_URL,
            params={"station": station.upper(), "model": "NBS"},
            timeout=(5, 10),
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        _log.debug("_fetch_nbs_daily_extremes(%s): %s", station, exc)
        _NBS_CACHE[cache_key] = (None, time.monotonic())
        return None

    try:
        tz = ZoneInfo(city_tz)
    except Exception:
        _log.warning("_fetch_nbs_daily_extremes: bad tz %r for %s", city_tz, station)
        _NBS_CACHE[cache_key] = (None, time.monotonic())
        return None

    rows = payload.get("data", [])
    extremes: dict[tuple, float] = {}
    _txn_rows_seen = 0
    _ftime_parse_failures = 0
    for r in rows:
        txn = _parse_temp(r.get("txn"))
        if txn is None:
            continue
        _txn_rows_seen += 1
        ftime_raw = r.get("ftime")
        if not ftime_raw:
            continue
        try:
            # Live-verified 2026-07-17 against real IEM payloads: "%Y-%m-%d
            # %H:%M", no seconds, space separator (e.g. "2026-07-18 00:00").
            ftime_utc = datetime.strptime(str(ftime_raw), "%Y-%m-%d %H:%M").replace(
                tzinfo=UTC
            )
        except ValueError:
            _ftime_parse_failures += 1
            continue
        if ftime_utc.hour == 0:
            extreme_kind = "max"
        elif ftime_utc.hour == 12:
            extreme_kind = "min"
        else:
            # Defensive: NBS's own docs only promise txn on 00Z/12Z rows, but
            # don't assume that holds forever -- skip anything else rather
            # than guess which extreme an off-cycle value represents.
            continue
        # The 12h period never crosses local midnight for any CONUS timezone
        # (worst case Pacific-in-winter still lands the window within
        # [~04:00, ~16:00) or its complement), so subtracting a token minute
        # before taking .date() safely lands inside the period's actual local
        # calendar day without needing to special-case the boundary.
        local_date = (ftime_utc.astimezone(tz) - timedelta(minutes=1)).date()
        extremes[(local_date, extreme_kind)] = txn

    if _txn_rows_seen and _ftime_parse_failures == _txn_rows_seen:
        # Every row with a real txn value failed to parse its ftime -- much
        # more likely IEM changed the timestamp format than that this
        # station/cycle genuinely has zero usable rows. Without this, that
        # looks identical to "no coverage" and the feature silently reverts
        # to the Open-Meteo best_match fallback forever. Flagged by
        # independent review 2026-07-17 (backlog.txt: REAL NBM VIA IEM NBS
        # STATION BULLETINS).
        _log.warning(
            "_fetch_nbs_daily_extremes(%s): all %d txn rows failed to parse "
            "ftime %r-style timestamps -- IEM may have changed the format",
            station,
            _ftime_parse_failures,
            rows[0].get("ftime") if rows else None,
        )

    _NBS_CACHE[cache_key] = (extremes if extremes else None, time.monotonic())
    return extremes if extremes else None


def fetch_nbm_iem(
    station: str,
    target_date: date,
    city_tz: str,
    var: str = "max",
) -> float | None:
    """Fetch the real NBM daily max/min for target_date from IEM's NBS
    bulletin -- replaces the old Open-Meteo model="nbm", which Open-Meteo
    removed (see backlog.txt: REAL NBM VIA IEM NBS STATION BULLETINS).

    var: "max" for daily high, "min" for daily low.
    Returns None if the station/date isn't covered -- NBS's own forecast
    horizon is short (~3 days) and same-day markets typically have zero
    same-day rows in the current cycle; callers should fall back to another
    source (e.g. Open-Meteo best_match) rather than treat None as an error.
    """
    extremes = _fetch_nbs_daily_extremes(station, city_tz)
    if extremes is None:
        return None
    return extremes.get((target_date, "max" if var == "max" else "min"))
