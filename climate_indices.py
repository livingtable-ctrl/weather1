"""
Climate indices from NOAA Climate Prediction Center.
Fetches AO (Arctic Oscillation), NAO (North Atlantic Oscillation), and
ENSO (El Niño/La Niña via ONI index).

These large-scale patterns shift temperature distributions beyond what
short-range ensemble models can capture — especially for the climatological
baseline probability.

Temperature adjustment logic (applied to climatological baseline only):
  AO:  Each +1 unit on East Coast → ~+1.5°F in spring, +2°F in winter
  NAO: Each +1 unit on East Coast → ~+1.0°F
  ENSO: El Niño winter → East Coast warmer; La Niña → cooler
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests

CPC_BASE = "https://www.cpc.ncep.noaa.gov"

# In-memory cache with 24-hour TTL so long-running processes refresh daily
_indices_cache: dict = {}
_indices_loaded_at: float = 0.0
_INDICES_TTL_SECS: float = 86400.0
_indices_lock = threading.Lock()


# ── Fetch helpers ─────────────────────────────────────────────────────────────


def _fetch_monthly_index(url: str) -> dict[tuple[int, int], float]:
    """
    Parse a NOAA CPC monthly index table (year + up to 12 monthly values per row).
    Returns dict keyed by (year, month) -> value.

    Accepts both complete rows (13 cols) and partial current-year rows (2+ cols)
    so that the most recent months are always available for lookback.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        result = {}
        for line in resp.text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    year = int(parts[0])
                    for m, v in enumerate(parts[1:], start=1):
                        if m > 12:
                            break
                        val = float(v)
                        if val > -99:  # -99.9 = missing
                            result[(year, m)] = val
                except ValueError:
                    continue
        return result
    except Exception:
        return {}


def _fetch_enso() -> dict[tuple[int, int], float]:
    """
    Parse the ONI (Oceanic Niño Index) from NOAA CPC.
    Returns dict keyed by (year, month_mid) -> ANOM value.
    """
    url = f"{CPC_BASE}/data/indices/oni.ascii.txt"  # 4-col format: SEAS YR TOTAL ANOM
    season_month = {
        "DJF": 1,
        "JFM": 2,
        "FMA": 3,
        "MAM": 4,
        "AMJ": 5,
        "MJJ": 6,
        "JJA": 7,
        "JAS": 8,
        "ASO": 9,
        "SON": 10,
        "OND": 11,
        "NDJ": 12,
    }
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        result = {}
        for line in resp.text.splitlines():
            parts = line.split()
            # File format: SEAS YR TOTAL ANOM (4 cols). parts[3] = ANOM.
            if len(parts) >= 4 and parts[0] in season_month:
                try:
                    year = int(parts[1])
                    anom = float(parts[3])
                    month = season_month[parts[0]]
                    result[(year, month)] = anom
                except (ValueError, IndexError):
                    continue
        return result
    except Exception:
        return {}


# ── Public interface ──────────────────────────────────────────────────────────


def get_indices(
    target_month: int | None = None, target_year: int | None = None
) -> dict:
    """
    Return current (or specified) AO, NAO, ENSO values.
    Results are cached with a 24-hour TTL so long-running processes refresh daily.
    Thread-safe.
    """
    global _indices_cache, _indices_loaded_at

    with _indices_lock:
        if (
            _indices_cache
            and (time.monotonic() - _indices_loaded_at) < _INDICES_TTL_SECS
        ):
            return _indices_cache.get("latest", {})

        from utils import utc_today as _utc_today

        now = _utc_today()
        year = target_year or now.year
        month = target_month or now.month

        ao_url = f"{CPC_BASE}/products/precip/CWlink/daily_ao_index/monthly.ao.index.b50.current.ascii.table"
        nao_url = f"{CPC_BASE}/products/precip/CWlink/pna/norm.nao.monthly.b5001.current.ascii.table"

        ao_data = _fetch_monthly_index(ao_url)
        nao_data = _fetch_monthly_index(nao_url)
        enso_data = _fetch_enso()

        def latest(data, y, m, lookback=3):
            for i in range(lookback):
                mm = m - i
                yy = y
                if mm <= 0:
                    mm += 12
                    yy -= 1
                if (yy, mm) in data:
                    return data[(yy, mm)]
            return 0.0

        result = {
            "ao": latest(ao_data, year, month),
            "nao": latest(nao_data, year, month),
            "enso": latest(enso_data, year, month),
            "year": year,
            "month": month,
        }
        # H-17: only cache when at least one index was successfully fetched.
        # A full-zero result from a network outage must not lock in zero adjustments
        # for the next 24 hours — leave _indices_loaded_at unchanged so the next
        # call retries immediately.
        if result["ao"] == 0.0 and result["nao"] == 0.0 and result["enso"] == 0.0:
            import logging as _ci_log

            _ci_log.getLogger(__name__).warning(
                "climate_indices: all three NOAA fetches returned empty — "
                "NOT caching zero result; will retry on next call"
            )
            return result  # return zeros for this call but don't update the timestamp

        _indices_cache["latest"] = result
        _indices_loaded_at = time.monotonic()
        return result


def get_enso_index(
    target_month: int | None = None, target_year: int | None = None
) -> float | None:
    """
    #28: Return the current ONI (ENSO) index value, or None if unavailable.
    Positive values indicate El Niño, negative indicate La Niña.
    """
    try:
        indices = get_indices(target_month, target_year)
        val = indices.get("enso")
        return val if val is not None else None
    except Exception:
        return None


def temperature_adjustment(city: str, target_date: date) -> float:
    """
    Estimate temperature adjustment (°F) to apply to the climatological baseline
    based on current AO, NAO, and ENSO state.

    Positive = warmer than climatology expected.
    Negative = cooler than climatology expected.

    Applied ONLY to climatological baseline, not to ensemble
    (the ensemble already responds to the current atmospheric pattern).
    """
    indices = get_indices(target_date.month, target_date.year)
    ao = indices.get("ao", 0.0)
    nao = indices.get("nao", 0.0)
    enso = indices.get("enso", 0.0)

    month = target_date.month

    # Season categories (Northern Hemisphere)
    is_winter = month in (12, 1, 2)
    is_spring = month in (3, 4, 5)
    # AO sensitivity (°F per unit AO) — stronger in winter/spring on East Coast
    ao_sens = {
        "NYC": 2.0 if is_winter else 1.2 if is_spring else 0.4,
        "Boston": 2.0 if is_winter else 1.2 if is_spring else 0.4,
        "Chicago": 2.2 if is_winter else 1.3 if is_spring else 0.5,
        "Miami": 0.6 if is_winter else 0.3 if is_spring else 0.1,
        "LA": 0.3,
        "Dallas": 1.2 if is_winter else 0.7 if is_spring else 0.3,
        "Phoenix": 0.5 if is_winter else 0.3 if is_spring else 0.1,
        "Seattle": 1.0 if is_winter else 0.8 if is_spring else 0.3,
        "Denver": 1.8 if is_winter else 1.0 if is_spring else 0.4,
        "Atlanta": 1.0 if is_winter else 0.6 if is_spring else 0.2,
    }

    # NAO sensitivity (°F per unit NAO)
    nao_sens = {
        "NYC": 1.2 if is_winter else 0.7 if is_spring else 0.2,
        "Boston": 1.3 if is_winter else 0.8 if is_spring else 0.2,
        "Chicago": 0.8 if is_winter else 0.5 if is_spring else 0.2,
        "Miami": 0.4 if is_winter else 0.2 if is_spring else 0.1,
        "LA": 0.2,
        "Dallas": 0.5 if is_winter else 0.3 if is_spring else 0.1,
        "Phoenix": 0.2 if is_winter else 0.1 if is_spring else 0.1,
        "Seattle": 0.6 if is_winter else 0.4 if is_spring else 0.2,
        "Denver": 0.7 if is_winter else 0.4 if is_spring else 0.2,
        "Atlanta": 0.6 if is_winter else 0.3 if is_spring else 0.1,
    }

    # ENSO sensitivity (°F per unit ONI)
    enso_sens = {
        "NYC": 1.0 if is_winter else 0.3,
        "Boston": 1.0 if is_winter else 0.3,
        "Chicago": 0.8 if is_winter else 0.3,
        "Miami": 0.5 if is_winter else 0.2,
        "LA": 0.8 if is_winter else 0.4,
        "Dallas": 1.0 if is_winter else 0.4,
        "Phoenix": 1.2 if is_winter else 0.5,
        "Seattle": 0.9 if is_winter else 0.5,
        "Denver": 0.9 if is_winter else 0.3,
        "Atlanta": 0.7 if is_winter else 0.3,
    }

    ao_adj = ao * ao_sens.get(city, 0.5)
    nao_adj = nao * nao_sens.get(city, 0.4)
    enso_adj = enso * enso_sens.get(city, 0.4)

    # Cap total adjustment at ±6°F to avoid over-correction
    total = ao_adj + nao_adj + enso_adj
    return max(-6.0, min(6.0, total))


# ── PDO / PNA (Pacific Decadal Oscillation / Pacific-North American pattern) ─


_PDO_URL = "https://www.ncdc.noaa.gov/teleconnections/pdo/data.csv"
_PNA_URL = "https://www.ncdc.noaa.gov/teleconnections/pna/data.csv"
_PDO_PNA_PATH = Path(__file__).parent / "data" / "pdo_pna.json"
_PDO_PNA_TTL_DAYS = 7


def _fetch_noaa_csv_index(url: str) -> dict[str, float]:
    """Parse a NOAA teleconnections CSV (Date=YYYYMM, Value columns).

    Returns {YYYYMM: value} dict. Skips header and missing-value rows.
    """
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    result = {}
    for line in resp.text.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            date_str = parts[0].strip()
            val = float(parts[1].strip())
            if len(date_str) == 6 and date_str.isdigit() and val > -99:
                result[date_str] = val
        except (ValueError, IndexError):
            continue
    return result


def fetch_pdo_pna() -> dict:
    """Fetch PDO and PNA indices from NOAA and save to data/pdo_pna.json."""
    pdo = _fetch_noaa_csv_index(_PDO_URL)
    pna = _fetch_noaa_csv_index(_PNA_URL)
    payload = {
        "pdo": pdo,
        "pna": pna,
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    _PDO_PNA_PATH.parent.mkdir(exist_ok=True)
    _PDO_PNA_PATH.write_text(json.dumps(payload))
    return payload


def get_pdo_pna(year: int | None = None, month: int | None = None) -> dict[str, float]:
    """Return current PDO and PNA values. Reads from file; fetches if stale or absent.

    Returns {"pdo": float, "pna": float}. Returns {"pdo": 0.0, "pna": 0.0} on failure.
    Accepts keyword arguments so callers and tests can use get_pdo_pna(year=Y, month=M).
    """
    now = datetime.now(UTC)
    data = None
    if _PDO_PNA_PATH.exists():
        try:
            data = json.loads(_PDO_PNA_PATH.read_text())
            fetched_at = datetime.fromisoformat(data["fetched_at"])
            if (now - fetched_at).days >= _PDO_PNA_TTL_DAYS:
                data = None  # stale — refetch below
        except Exception:
            data = None

    if data is None:
        try:
            data = fetch_pdo_pna()
        except Exception:
            return {"pdo": 0.0, "pna": 0.0}

    target_year = year or now.year
    target_month = month or now.month

    def _latest(index_dict: dict, lookback: int = 3) -> float:
        for i in range(lookback):
            m = target_month - i
            y = target_year
            if m <= 0:
                m += 12
                y -= 1
            k = f"{y}{m:02d}"
            if k in index_dict:
                return float(index_dict[k])
        return 0.0

    return {
        "pdo": _latest(data.get("pdo", {})),
        "pna": _latest(data.get("pna", {})),
    }


# Seasonal temperature coefficients (degrees F per +1 index unit) for PDO.
# PDO primarily affects west-coast cities where Pacific SSTs modulate
# onshore air temperatures — strongest in winter, weak in summer.
_PDO_TEMP_COEFF: dict[str, dict[str, float]] = {
    "LA": {"DJF": 0.8, "MAM": 0.4, "JJA": 0.2, "SON": 0.4},
    "SanFrancisco": {"DJF": 0.8, "MAM": 0.4, "JJA": 0.2, "SON": 0.4},
    "Seattle": {"DJF": 0.8, "MAM": 0.4, "JJA": 0.2, "SON": 0.4},
}

# PNA affects central and eastern US via ridge/trough modulation.
# Positive PNA -> ridge over West, trough over East -> warmer central, colder East.
_PNA_TEMP_COEFF: dict[str, dict[str, float]] = {
    "Chicago": {"DJF": 1.2, "MAM": 0.4, "JJA": 0.1, "SON": 0.4},
    "Minneapolis": {"DJF": 1.2, "MAM": 0.4, "JJA": 0.1, "SON": 0.4},
    "NYC": {"DJF": 1.0, "MAM": 0.3, "JJA": 0.1, "SON": 0.3},
    "Boston": {"DJF": 1.0, "MAM": 0.3, "JJA": 0.1, "SON": 0.3},
}


def _month_to_season(month: int) -> str:
    """Map calendar month (1-12) to meteorological season abbreviation."""
    return {
        12: "DJF",
        1: "DJF",
        2: "DJF",
        3: "MAM",
        4: "MAM",
        5: "MAM",
        6: "JJA",
        7: "JJA",
        8: "JJA",
        9: "SON",
        10: "SON",
        11: "SON",
    }[month]


def apply_pdo_pna_correction(city: str, forecast_temp_f: float, month: int) -> float:
    """Return temperature bias correction (degrees F) based on PDO/PNA for city and month.

    Returns 0.0 for cities not in coefficient tables.
    Caller adds the result: forecast_temp_f += apply_pdo_pna_correction(...)
    Clamped to +-3 degrees F to prevent over-correction from extreme index values.
    """
    season = _month_to_season(month)
    pdo_coeff = _PDO_TEMP_COEFF.get(city, {}).get(season, 0.0)
    pna_coeff = _PNA_TEMP_COEFF.get(city, {}).get(season, 0.0)

    if pdo_coeff == 0.0 and pna_coeff == 0.0:
        return 0.0

    indices = get_pdo_pna()
    correction = pdo_coeff * indices["pdo"] + pna_coeff * indices["pna"]
    return round(max(-3.0, min(3.0, correction)), 2)
