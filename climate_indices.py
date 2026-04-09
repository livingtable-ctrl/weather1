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

from datetime import date

import requests

CPC_BASE = "https://www.cpc.ncep.noaa.gov"

# In-memory cache
_indices_cache: dict = {}


# ── Fetch helpers ─────────────────────────────────────────────────────────────


def _fetch_monthly_index(url: str) -> dict[tuple[int, int], float]:
    """
    Parse a NOAA CPC monthly index table (year + 12 monthly values per row).
    Returns dict keyed by (year, month) -> value.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        result = {}
        for line in resp.text.splitlines():
            parts = line.split()
            if len(parts) == 13:
                try:
                    year = int(parts[0])
                    for m, v in enumerate(parts[1:], start=1):
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
    url = f"{CPC_BASE}/data/indices/oni.ascii.txt"
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
            if len(parts) >= 5 and parts[0] in season_month:
                try:
                    year = int(parts[1])
                    anom = float(parts[4])
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
    Results cached for the session.
    """
    if _indices_cache:
        return _indices_cache.get("latest", {})

    now = date.today()
    year = target_year or now.year
    month = target_month or now.month

    ao_url = f"{CPC_BASE}/products/precip/CWlink/daily_ao_index/ao.index.b50.current.ascii.table"
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
    _indices_cache["latest"] = result
    return result


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
