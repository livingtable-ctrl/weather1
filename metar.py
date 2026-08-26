"""
METAR same-day lock-in strategy.

After ~2 PM local time, if the daily high/low has clearly already peaked
above/below the Kalshi threshold, the outcome is near-certain. Beyond the
core lock-in check, this module also:
  - Validates raw METAR reads with plausibility (physically-sane temperature
    range) and staleness (observation age) gates before they're trusted.
  - Scales lock-in confidence dynamically from temperature clearance and time
    of day (`_dynamic_lock_in_confidence`) instead of using a fixed constant.

Reported win rate: 85-90%.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import requests
from requests.adapters import HTTPAdapter, Retry

from forecast_cache import ForecastCache

_log = logging.getLogger(__name__)

_METAR_URL = "https://aviationweather.gov/api/data/metar"
_LOCK_IN_HOUR = 14  # 2 PM local — earliest lock-in time


def _parse_iso_utc(raw: str) -> datetime | None:
    """Parse an ISO-8601 METAR timestamp string into an AWARE UTC datetime.

    M-18b(a)/(b): aviationweather.gov's real payload shape for both obsTime
    (as a string, rarely seen live) and reportTime is a bare
    "2026-08-23 14:53:00" -- no "Z", no UTC offset at all. datetime.
    fromisoformat() happily parses that into a NAIVE datetime; the
    `.replace("Z", "+00:00")` guard below only helps when a "Z" is actually
    present. A naive result is dangerous two different ways depending on the
    caller: fetch_metar()'s `datetime.now(UTC) - obs_time` raises TypeError
    (naive - aware) instead of degrading gracefully, and
    _extract_obs_time()'s callers pass the naive result straight into
    `.astimezone(tz)`, which Python interprets as SYSTEM-LOCAL time --
    silently misdating the observation. The API's timestamps are documented
    UTC, so a naive result here always means "this was UTC without the
    marker" -- attach it rather than leaving it ambiguous.
    """
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _dynamic_lock_in_confidence(
    clearance_f: float,
    local_hour: int,
    margin_f: float = 3.0,
) -> float:
    """Compute METAR lock-in confidence from temperature clearance and time of day.

    L6-D fix: replaces the hardcoded ``_LOCK_IN_CONFIDENCE = 0.90`` constant.
    Two factors scale the probability upward from a conservative base:

    * **Clearance factor** – how far the observed temperature is beyond the
      trigger margin.  Saturates at 10 °F extra clearance (i.e. 13 °F total
      when ``margin_f=3``).
    * **Hour factor** – how late in the afternoon the lock-in fires.  Saturates
      at 8 PM local (hour 20).  Later = daily high/low is more settled.

    Resulting confidence ∈ [0.72, 0.97]:
      - 3 °F clearance at 2 PM  → 0.720  (was 0.90 — over-bet near-threshold)
      - 3 °F clearance at 8 PM  → 0.790
      - 10 °F clearance at 5 PM → 0.881
      - 13 °F clearance at 8 PM → 0.970

    **The 0.97 cap has a consumer in another file that nothing here points
    at, so read this before widening it.** weather_markets.analyze_trade
    runs the output of this function through ml_bias.apply_metar_calibration
    (a beta calibration fitted on settled lockout outcomes) BEFORE choosing
    which side to trade, and its section 10b relies on the resulting
    probability range. The beta map is strictly increasing (a = b > 0), so
    the calibrated value for a NO lock is bounded below by whatever this cap
    is: at 0.97 the floor is 0.4046, and it drops with the cap --

        cap 0.97 → 0.405    cap 0.99  → 0.345    cap 0.999 → 0.238
        cap 0.98 → 0.382    cap 0.995 → 0.311    no cap    → 0.062

    -- which widens the band of market prices where a NO lock's calibrated
    probability sits ABOVE the price and the bare `blended_prob >
    market_prob` comparison therefore recommends YES on an outcome the lock
    ruled out. Section 10b corrects that side, so raising the cap is not
    unsafe; it just moves a boundary documented over there in terms of a
    number chosen here. Figures are for the fit live on 2026-08-26
    (data/metar_lockout_calibration.json, a=b=0.2262 c=0.4001, n=33) and
    move with any refit -- recompute rather than trusting them.
    """
    extra_f = max(0.0, clearance_f - margin_f)
    c_factor = min(1.0, extra_f / 10.0)
    h_factor = max(0.0, min(1.0, (local_hour - _LOCK_IN_HOUR) / 6.0))
    conf = 0.72 + 0.18 * c_factor + 0.07 * h_factor
    return round(min(0.97, max(0.72, conf)), 3)


def _between_dynamic_lock_in_confidence(
    clearance_f: float,
    local_hour: int,
    margin_f: float = 3.0,
) -> float:
    """Between-bracket variant of _dynamic_lock_in_confidence() -- deliberate
    fork, not a duplicate to be merged back (batch-40 "Between-bracket
    calibration design", Decision 3: keep between's formula ownership
    separate from above/below's).

    Byte-identical math to _dynamic_lock_in_confidence() today -- this fork
    is purely a code-ownership boundary, not a recalibration (the batch's
    own decision text is explicit: "Don't redesign the above/below side
    here -- its calibration loop exists and batch 37 refits it"). The
    formula's only calibration evidence to date is above/below's own
    METAR-lockout calibration loop (predicted 89.6% vs actual 70.4% on
    YES-locks, n=27; 93.0% vs 50.0% on NO-locks, n=6 -- see backlog.txt's
    HIGH-market non-monotone NO-lock gap entry, which this evidence was
    appended to), and that evidence does NOT directly transfer to between:
    a between-YES lock carries a hazard above/below lacks (an in-band
    extreme can still rise/fall OUT of the band, not just fail to confirm
    an above/below threshold), and margin_f differs structurally (3.0 for
    above/below's outside-the-band clearance vs as little as 1.0 for a
    between-YES lock's inside-the-band clearance to the at-risk edge --
    see weather_markets._metar_lock_in's between branch,
    `_yes_inband_margin = (_hi - _lo) / 2.0`). Sharing one function risked a
    future above/below calibration refit (batch 37 owns that loop) silently
    changing between's behavior too, or vice versa, especially now that
    between is gated separately (weather_markets._between_metar_gates_active())
    while above/below is not. Forking removes that coupling; if/when between
    accumulates its own calibration evidence
    (tracker.get_sameday_calibration's by_condition_type breakout +
    count_settled_between_predictions()), this function's own constants are
    the place to change, independent of above/below's.
    """
    extra_f = max(0.0, clearance_f - margin_f)
    c_factor = min(1.0, extra_f / 10.0)
    h_factor = max(0.0, min(1.0, (local_hour - _LOCK_IN_HOUR) / 6.0))
    conf = 0.72 + 0.18 * c_factor + 0.07 * h_factor
    return round(min(0.97, max(0.72, conf)), 3)


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

# In-process cache: station → result (negative-cached as None on fetch
# failure). METAR stations update every 20–30 min; 5-min TTL eliminates
# redundant HTTP calls when cmd_today / cmd_scan loop over many markets for
# the same cities. Migrated to the shared ForecastCache 2026-07-19
# (backlog.txt "ForecastCache EXISTS, BUT ~14 HAND-ROLLED TTL DICTS..."). A
# real (negative-cached) None value is indistinguishable from "no entry" via
# plain .get() alone, so the read site below uses get_with_ts()'s explicit
# hit flag instead.
_METAR_CACHE_TTL = (
    900  # 15 minutes — extended so pre-warm survives the full analysis window
)
_METAR_CACHE: ForecastCache[dict | None] = ForecastCache(ttl_secs=_METAR_CACHE_TTL)


def fetch_metar(station: str) -> dict | None:
    """
    Fetch the most recent METAR observation for a station.

    Returns:
        dict with keys: current_temp_f, station, obs_time (datetime UTC)
        or None on failure
    """
    key = station.upper()
    _cached_result, _cache_hit, _ = _METAR_CACHE.get_with_ts(key)
    if _cache_hit:
        return _cached_result

    try:
        resp = _session.get(
            _METAR_URL,
            params={"ids": station.upper(), "format": "json"},
            timeout=(5, 10),  # (connect, read) — 5s cap on SSL handshake
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log.debug("fetch_metar(%s): %s", station, exc)
        _METAR_CACHE.set(key, None)
        return None

    if not data:
        _METAR_CACHE.set(key, None)
        return None

    obs = data[0]
    # Prefer tmpf (°F) if present, otherwise convert temp (°C)
    temp_f = obs.get("tmpf")
    if temp_f is None:
        temp_c = obs.get("temp")
        if temp_c is None:
            # M-18b(c)/L-2: negative-cache this failure too -- the two
            # siblings below (staleness gate, plausibility gate) both do,
            # and without it a station reporting no usable temp field
            # re-issues the ~21s HTTP call on every scan instead of being
            # absorbed by the 15-min TTL like every other fetch_metar
            # failure path.
            _METAR_CACHE.set(key, None)
            return None
        temp_f = float(temp_c) * 9 / 5 + 32
    else:
        temp_f = float(temp_f)

    # P1-2: plausibility check — physically impossible temperatures
    if not (-80.0 <= temp_f <= 140.0):
        _log.warning(
            "%s: METAR temp_f=%.1f outside plausible range — discarding",
            station,
            temp_f,
        )
        # M-18b(c)/L-2: same negative-cache gap as the missing-temp branch above.
        _METAR_CACHE.set(key, None)
        return None

    # P1-2: staleness gate — never fabricate a timestamp for a missing obsTime.
    # A missing or unparseable obsTime means we can't verify freshness; reject rather
    # than silently treating stale data as current.
    # The API returns obsTime as a Unix integer epoch; fall back to reportTime (ISO str).
    obs_time = None
    raw_obs_time = obs.get("obsTime")
    if isinstance(raw_obs_time, int | float) and raw_obs_time > 0:
        try:
            obs_time = datetime.fromtimestamp(raw_obs_time, UTC)
        except Exception:
            pass
    elif isinstance(raw_obs_time, str) and raw_obs_time:
        obs_time = _parse_iso_utc(raw_obs_time)
    if obs_time is None:
        report_time_str = obs.get("reportTime") or ""
        if report_time_str:
            obs_time = _parse_iso_utc(report_time_str)
    if obs_time is None:
        _log.warning(
            "%s: METAR obsTime missing or unparseable — refusing to use stale data",
            station,
        )
        _METAR_CACHE.set(key, None)
        return None
    age_minutes = (datetime.now(UTC) - obs_time).total_seconds() / 60
    if age_minutes > 90:
        _log.warning(
            "%s: METAR observation %d min old — too stale for lock-in",
            station,
            int(age_minutes),
        )
        _METAR_CACHE.set(key, None)
        return None

    def _safe_extreme(f_field: str, c_field: str) -> float | None:
        # aviationweather.gov's real /api/data/metar payload has no *f
        # Fahrenheit extreme field at all -- only maxT/minT in Celsius (found
        # 2026-08-09, opus review of backlog.txt "BETWEEN-BUCKET MARKETS ...
        # METAR LOCK-IN WAS DISABLED": the code had read the nonexistent
        # "minf"/"maxf" since this function was written, so max_temp_f/
        # min_temp_f were ALWAYS None in production -- silently, since every
        # caller already has an `is not None` fallback to current_temp_f).
        # f_field is kept as a defensive first choice only, mirroring
        # current_temp_f's own tmpf-then-temp pattern above, in case the API
        # ever adds a Fahrenheit variant.
        raw_f = obs.get(f_field)
        if raw_f is not None:
            try:
                val_f = float(raw_f)
            except (TypeError, ValueError):
                pass
            else:
                return val_f if -80.0 <= val_f <= 140.0 else None
        raw_c = obs.get(c_field)
        if raw_c is None:
            return None
        try:
            val = float(raw_c) * 9 / 5 + 32
        except (TypeError, ValueError):
            return None
        return val if -80.0 <= val <= 140.0 else None

    # Extract dew point: prefer dwpf (°F) if present, else convert the real
    # payload's "dewp" (°C) field. "dwpt" is kept as a second Celsius fallback
    # only in case some other endpoint/format uses that name -- the live
    # aviationweather.gov payload uses "dewp", not "dwpt" (same field-name
    # audit as _safe_extreme above; dew_point_f was ALSO always None before
    # this fix).
    dp_f = obs.get("dwpf")
    if dp_f is None:
        dp_c = obs.get("dewp", obs.get("dwpt"))
        if dp_c is not None:
            try:
                dp_f = float(dp_c) * 9 / 5 + 32
            except (TypeError, ValueError):
                dp_f = None
    else:
        try:
            dp_f = float(dp_f)
        except (TypeError, ValueError):
            dp_f = None

    result = {
        "current_temp_f": temp_f,
        "min_temp_f": _safe_extreme("minf", "minT"),
        "max_temp_f": _safe_extreme("maxf", "maxT"),
        "dew_point_f": dp_f,
        "station": obs.get("icaoId", station),
        "obs_time": obs_time,
    }
    _METAR_CACHE.set(key, result)
    return result


# In-process cache for the true running daily extreme (see
# fetch_metar_daily_extreme below) — keyed by station+local-date so the
# cached value never leaks across a day boundary. Same 15-min TTL as
# _METAR_CACHE.
#
# The staleness this TTL trades away is NOT symmetric between the two
# extremes: for a NO-direction lock, a stale (under-reported) max/min is
# still a valid lower/upper bound on the true running extreme, so staleness
# only makes a real NO lock arrive up to ~15 min late — never wrong. For a
# YES-direction lock (both settlement_monitor._check_between_settlement and
# weather_markets._metar_lock_in's between branch require the extreme to
# sit INSIDE the band with clearance to the at-risk edge), an
# under-reported extreme makes the measured clearance LARGER than the true
# current clearance — i.e. a stale read can make a YES lock look safer than
# it currently is, for up to ~15 minutes, until the next real observation
# is cached. Both callers additionally require a real (non-fallback) extreme
# and per-observation staleness/date guards elsewhere in the call chain,
# which bound the practical exposure, but this cache's own staleness is
# not, by itself, safe in the YES direction the way it is in the NO
# direction — do not assume otherwise when reusing this cache elsewhere.
_DAILY_OBS_CACHE_TTL = 900
_DAILY_OBS_CACHE: ForecastCache[list[float] | None] = ForecastCache(
    ttl_secs=_DAILY_OBS_CACHE_TTL
)


def _extract_temp_f(obs: dict) -> float | None:
    """Extract a plausible temp_f from a raw METAR obs dict (prefers tmpf
    °F, else converts temp °C). Returns None for a missing or physically
    implausible reading. Deliberately NOT shared with fetch_metar()'s own
    inline version of this same logic — fetch_metar() is heavily tested and
    logs a specific warning on the implausible-temp path; duplicating the
    ~10 lines here avoids touching that already-verified code as a side
    effect of adding this function."""
    temp_f = obs.get("tmpf")
    if temp_f is None:
        temp_c = obs.get("temp")
        if temp_c is None:
            return None
        try:
            temp_f = float(temp_c) * 9 / 5 + 32
        except (TypeError, ValueError):
            return None
    else:
        try:
            temp_f = float(temp_f)
        except (TypeError, ValueError):
            return None
    return temp_f if -80.0 <= temp_f <= 140.0 else None


def _extract_obs_time(obs: dict) -> datetime | None:
    """Parse a raw METAR obs dict's obsTime (Unix epoch int/float, or an
    ISO-8601 string) into a UTC datetime. Deliberately NOT shared with
    fetch_metar()'s own version of this parsing (same rationale as
    _extract_temp_f) — omits fetch_metar()'s reportTime tertiary fallback
    and 90-min staleness gate, neither of which apply when aggregating a
    historical window rather than validating a single live reading."""
    raw = obs.get("obsTime")
    if isinstance(raw, int | float) and raw > 0:
        try:
            return datetime.fromtimestamp(raw, UTC)
        except Exception:
            return None
    if isinstance(raw, str) and raw:
        return _parse_iso_utc(raw)
    return None


def _fetch_daily_temps_f(
    station: str, city_tz: str, target_date: date
) -> list[float] | None:
    """Fetch every METAR temp_f reading for `station` that falls on the
    LOCAL calendar date `target_date`, by requesting a wide (30-hour)
    window of historical observations — enough to cover local midnight to
    now for any continental-US timezone with buffer to spare — and
    filtering+converting each reading's obsTime to `city_tz` locally.

    Returns None on fetch failure (network error, unparseable response);
    an empty list is a valid result (fetch succeeded, no reading fell on
    target_date yet — e.g. right after local midnight).
    """
    key = f"{station.upper()}|{target_date.isoformat()}"
    cached, hit, _ = _DAILY_OBS_CACHE.get_with_ts(key)
    if hit:
        return cached

    try:
        resp = _session.get(
            _METAR_URL,
            params={"ids": station.upper(), "format": "json", "hours": "30"},
            timeout=(5, 10),
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log.debug("_fetch_daily_temps_f(%s): %s", station, exc)
        # Negative-cache the failure (mirrors fetch_metar()'s own pattern) —
        # without this, an API outage makes every same-day between/above-
        # below market re-attempt this fetch on every scan, since
        # _metar_lock_in runs once per market rather than once per station.
        _DAILY_OBS_CACHE.set(key, None)
        return None

    if not data:
        _DAILY_OBS_CACHE.set(key, [])
        return []

    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(city_tz)
    except Exception:
        _log.debug("_fetch_daily_temps_f(%s): bad city_tz %r", station, city_tz)
        _DAILY_OBS_CACHE.set(key, None)
        return None

    temps: list[float] = []
    for obs in data:
        temp_f = _extract_temp_f(obs)
        if temp_f is None:
            continue
        obs_time = _extract_obs_time(obs)
        if obs_time is None:
            continue
        if obs_time.astimezone(tz).date() != target_date:
            continue
        temps.append(temp_f)

    _DAILY_OBS_CACHE.set(key, temps)
    return temps


def fetch_metar_daily_extreme(
    station: str, city_tz: str, target_date: date, extreme: str
) -> float | None:
    """
    Compute the TRUE running daily extreme (max or min observed temp_f)
    since LOCAL midnight of `target_date`, by fetching a window of
    historical METAR observations and taking the extreme LOCALLY.

    Do NOT use fetch_metar()'s own max_temp_f/min_temp_f fields for any
    reasoning that depends on a full-day running extreme (e.g. "the running
    high can only stay flat or rise, never fall back into the band") —
    live-verified 2026-08-09 (backlog.txt "SETTLEMENT_MONITOR.PY'S OWN
    BETWEEN-BUCKET LOCK..."): those come from the METAR remark group's
    6-hour max/min (maxT/minT), populated ONLY on synoptic-hour (00Z/06Z/
    12Z/18Z) reports and covering only THAT report's own preceding 6 hours
    — not a cumulative value since local midnight. A station whose true
    daily high occurred outside the most recent synoptic window (e.g. an
    early-afternoon peak followed by a cold-frontal cooldown before the
    next synoptic report) silently under-reports it via that field; on
    KDEN, live-checked the same day, maxT was populated on only 2 of 15
    hourly reports and each value matched only that report's own 6h window.

    Only reliable for target_date == "today" (in city_tz) at call time: the
    underlying fetch requests a 30-hour window ending NOW, which covers
    local midnight through now for any continental-US timezone with buffer
    to spare — but for any OTHER target_date that window will generally
    miss part of that date's readings (e.g. a `target_date` of yesterday,
    called this afternoon, would only see yesterday's evening hours, not
    its morning). All current callers (settlement_monitor.py,
    weather_markets.py's _metar_lock_in, weather_markets.py's
    _compute_persistence_prob) only ever pass today's date; this function
    does not enforce that itself.

    Args:
        station: ICAO station code
        city_tz: IANA timezone name for the station's city
        target_date: the LOCAL calendar date to compute the extreme for —
            see the "today only" restriction above
        extreme: "max" or "min"

    Returns:
        The extreme temp_f among target_date's observations so far, or
        None on fetch failure or if no observation has fallen on
        target_date yet.
    """
    if extreme not in ("max", "min"):
        raise ValueError(f"extreme must be 'max' or 'min', got {extreme!r}")
    temps = _fetch_daily_temps_f(station, city_tz, target_date)
    if not temps:
        return None
    return max(temps) if extreme == "max" else min(temps)


def check_metar_lockout(
    current_temp_f: float,
    threshold_f: float,
    direction: str,
    obs_time: datetime,
    city_tz: str = "America/New_York",
    margin_f: float = 3.0,
) -> dict:
    """
    Determine if a METAR reading locks in the trade outcome.

    Lock-in conditions (ALL must be true):
    1. Local time >= 2 PM (temperature has had time to peak)
    2. Temperature is more than margin_f beyond the threshold

    Returns:
        dict: {locked: bool, outcome: "yes"|"no"|None, confidence: float, reason: str}
    """
    NOT_LOCKED = {"locked": False, "outcome": None, "confidence": 0.0, "reason": ""}

    # 1. Check local time
    try:
        from zoneinfo import ZoneInfo

        local_time = obs_time.astimezone(ZoneInfo(city_tz))
    except Exception:
        # M-18b(d): fail CLOSED on a bad city_tz, not open. Falling back to
        # obs_time as-is (UTC) would pass the "local hour >= 14" gate at
        # e.g. ~09:00 real-local for any city west of UTC -- the same
        # premature-lock-in risk _fetch_daily_temps_f's own bad-tz fallback
        # already fails closed on (mos.py mirrors this too). Never actually
        # reachable for any of this bot's 20 traded cities (all real IANA
        # names, pinned tzdata) -- defense in depth, not a live gap.
        return {
            **NOT_LOCKED,
            "reason": f"could not resolve local time for tz={city_tz!r} — fail closed",
        }
    if local_time.hour < _LOCK_IN_HOUR:
        return {
            **NOT_LOCKED,
            "reason": f"too early ({local_time.hour}h < {_LOCK_IN_HOUR}h local)",
        }

    # 2. Check temperature clearance
    if direction == "above":
        if current_temp_f >= threshold_f + margin_f:
            # L6-D: confidence scales with clearance and time of day
            _conf = _dynamic_lock_in_confidence(
                current_temp_f - threshold_f, local_time.hour, margin_f
            )
            return {
                "locked": True,
                "outcome": "yes",
                "confidence": _conf,
                "reason": f"METAR {current_temp_f:.1f}°F >= threshold {threshold_f}°F + margin {margin_f}°F",
            }
        elif current_temp_f <= threshold_f - margin_f:
            _conf = _dynamic_lock_in_confidence(
                threshold_f - current_temp_f, local_time.hour, margin_f
            )
            return {
                "locked": True,
                "outcome": "no",
                "confidence": _conf,
                "reason": f"METAR {current_temp_f:.1f}°F <= threshold {threshold_f}°F - margin {margin_f}°F",
            }
    elif direction == "below":
        if current_temp_f <= threshold_f - margin_f:
            _conf = _dynamic_lock_in_confidence(
                threshold_f - current_temp_f, local_time.hour, margin_f
            )
            return {
                "locked": True,
                "outcome": "yes",
                "confidence": _conf,
                "reason": f"METAR {current_temp_f:.1f}°F <= threshold {threshold_f}°F - margin {margin_f}°F",
            }
        elif current_temp_f >= threshold_f + margin_f:
            _conf = _dynamic_lock_in_confidence(
                current_temp_f - threshold_f, local_time.hour, margin_f
            )
            return {
                "locked": True,
                "outcome": "no",
                "confidence": _conf,
                "reason": f"METAR {current_temp_f:.1f}°F >= threshold {threshold_f}°F + margin {margin_f}°F",
            }

    return {
        **NOT_LOCKED,
        "reason": f"temperature {current_temp_f:.1f}°F within margin of {threshold_f}°F",
    }


# ── Phase 4: station-level observation recording ──────────────────────────────

# Maps city name (matching CITY_COORDS keys) to primary ICAO observation station.
MARKET_STATION_MAP: dict[str, str] = {
    "NYC": "KNYC",
    "Chicago": "KMDW",
    "LA": "KLAX",
    "Miami": "KMIA",
    "Boston": "KBOS",
    "Dallas": "KDFW",
    "Phoenix": "KPHX",
    "Seattle": "KSEA",
    "Denver": "KDEN",
    "Atlanta": "KATL",
    # Additional cities matching Kalshi ticker detection
    "Austin": "KAUS",
    "Washington": "KDCA",
    "Philadelphia": "KPHL",
    "OklahomaCity": "KOKC",
    "SanFrancisco": "KSFO",
    "Minneapolis": "KMSP",
    "Houston": "KHOU",
    "SanAntonio": "KSAT",
    "LasVegas": "KLAS",
    "NewOrleans": "KMSY",
    # Rain-only city (KXRAINSTPM) -- settlement station confirmed live via the
    # market's own rules_secondary text ("CLISPG" / "Albert Whitted").
    "StPetersburg": "KSPG",
}
