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
from datetime import UTC, datetime

import requests
from requests.adapters import HTTPAdapter, Retry

from forecast_cache import ForecastCache

_log = logging.getLogger(__name__)

_METAR_URL = "https://aviationweather.gov/api/data/metar"
_LOCK_IN_HOUR = 14  # 2 PM local — earliest lock-in time


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
        try:
            obs_time = datetime.fromisoformat(raw_obs_time.replace("Z", "+00:00"))
        except Exception:
            pass
    if obs_time is None:
        report_time_str = obs.get("reportTime") or ""
        if report_time_str:
            try:
                obs_time = datetime.fromisoformat(
                    report_time_str.replace("Z", "+00:00")
                )
            except Exception:
                pass
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

    def _safe_extreme(field: str) -> float | None:
        raw = obs.get(field)
        if raw is None:
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        return val if -80.0 <= val <= 140.0 else None

    # Extract dew point: prefer dwpf (°F) if present, else convert dwpt (°C).
    # Returns None when neither field is available.
    dp_f = obs.get("dwpf")
    if dp_f is None:
        dp_c = obs.get("dwpt")
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
        "min_temp_f": _safe_extreme("minf"),
        "max_temp_f": _safe_extreme("maxf"),
        "dew_point_f": dp_f,
        "station": obs.get("icaoId", station),
        "obs_time": obs_time,
    }
    _METAR_CACHE.set(key, result)
    return result


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
        local_time = obs_time  # fallback to UTC
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
}
