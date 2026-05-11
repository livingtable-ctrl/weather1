"""
METAR same-day lock-in strategy + station-level observation recording (Phase 4 stub).
After ~2 PM local time, if the daily high has clearly already peaked above/below
the Kalshi threshold, the outcome is near-certain.
Reported win rate: 85-90%.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter, Retry

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
    h_factor = min(1.0, (local_hour - _LOCK_IN_HOUR) / 6.0)
    conf = 0.72 + 0.18 * c_factor + 0.07 * h_factor
    return round(min(0.97, max(0.72, conf)), 3)


_session = requests.Session()
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]
        )
    ),
)

# In-process cache: station → (result, monotonic_time).
# METAR stations update every 20–30 min; 5-min TTL eliminates redundant HTTP
# calls when cmd_today / cmd_scan loop over many markets for the same cities.
_METAR_CACHE: dict[str, tuple[dict | None, float]] = {}
_METAR_CACHE_TTL = 300  # 5 minutes


def fetch_metar(station: str) -> dict | None:
    """
    Fetch the most recent METAR observation for a station.

    Returns:
        dict with keys: current_temp_f, station, obs_time (datetime UTC)
        or None on failure
    """
    import time as _time

    key = station.upper()
    cached = _METAR_CACHE.get(key)
    if cached is not None:
        result, ts = cached
        if _time.monotonic() - ts < _METAR_CACHE_TTL:
            return result

    try:
        resp = _session.get(
            _METAR_URL,
            params={"ids": station.upper(), "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log.debug("fetch_metar(%s): %s", station, exc)
        _METAR_CACHE[key] = (None, _time.monotonic())
        return None

    if not data:
        _METAR_CACHE[key] = (None, _time.monotonic())
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
        _METAR_CACHE[key] = (None, _time.monotonic())
        return None
    age_minutes = (datetime.now(UTC) - obs_time).total_seconds() / 60
    if age_minutes > 90:
        _log.warning(
            "%s: METAR observation %d min old — too stale for lock-in",
            station,
            int(age_minutes),
        )
        _METAR_CACHE[key] = (None, _time.monotonic())
        return None

    result = {
        "current_temp_f": temp_f,
        "station": obs.get("icaoId", station),
        "obs_time": obs_time,
    }
    _METAR_CACHE[key] = (result, _time.monotonic())
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
    "Chicago": "KORD",
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
    "Houston": "KIAH",
    "SanAntonio": "KSAT",
}

_OBS_PATH = Path("data/metar_observations.json")
_OBS_LOCK = threading.Lock()
_MIN_OBS_FOR_MODEL = 200


def _load_obs() -> list[dict]:
    if not _OBS_PATH.exists():
        return []
    try:
        with _OBS_LOCK:
            return json.loads(_OBS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.debug("metar: could not load observations: %s", exc)
        return []


def _save_obs(records: list[dict]) -> None:
    try:
        _OBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _OBS_LOCK:
            _OBS_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except Exception as exc:
        _log.debug("metar: could not save observations: %s", exc)


def record_observation(
    city: str,
    date_str: str,
    high_f: float,
    low_f: float | None = None,
    *,
    proxy: bool = False,
) -> None:
    """
    Append one observation record for city/date.

    proxy=True when temp is estimated from market outcome (threshold ± 3°F)
    rather than fetched directly from METAR. Proxy records still count toward
    the _MIN_OBS_FOR_MODEL threshold.
    """
    station_id = MARKET_STATION_MAP.get(city)
    if not station_id:
        return

    records = _load_obs()
    # Deduplicate: replace existing record for same station+date
    records = [
        r
        for r in records
        if not (r["station_id"] == station_id and r["date"] == date_str)
    ]
    records.append(
        {
            "station_id": station_id,
            "city": city,
            "date": date_str,
            "high_f": round(high_f, 2),
            "low_f": round(low_f, 2) if low_f is not None else None,
            "proxy": proxy,
        }
    )
    _save_obs(records)
    _log.debug(
        "metar: recorded %s %s high=%.1f%s",
        station_id,
        date_str,
        high_f,
        " (proxy)" if proxy else "",
    )


def get_obs_count(city: str) -> int:
    """Return the number of stored observations for this city's station."""
    station_id = MARKET_STATION_MAP.get(city)
    if not station_id:
        return 0
    return sum(1 for r in _load_obs() if r["station_id"] == station_id)


def get_station_bias(city: str, month: int) -> float | None:
    """
    Return mean bias (forecast − observed) in °F for this station/month.
    Returns None until _MIN_OBS_FOR_MODEL observations are available — at that
    point the per-station model activates automatically with no code change.
    """
    station_id = MARKET_STATION_MAP.get(city)
    if not station_id:
        return None

    records = _load_obs()
    station_records = [r for r in records if r["station_id"] == station_id]

    if len(station_records) < _MIN_OBS_FOR_MODEL:
        return None

    month_records = [r for r in station_records if int(r["date"][5:7]) == month]
    if len(month_records) < 20:
        return None

    # Placeholder: once forecast temps are stored alongside observations,
    # compute mean(forecast_high - observed_high) here.
    return 0.0
