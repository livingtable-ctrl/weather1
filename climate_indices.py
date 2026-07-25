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
from datetime import UTC, date, datetime
from pathlib import Path

import requests

from forecast_cache import ForecastCache

CPC_BASE = "https://www.cpc.ncep.noaa.gov"

# In-memory cache with 24-hour TTL so long-running processes refresh daily.
# Keyed by (year, month) -- was a single "latest" slot until 2026-07-19,
# which let one target month's cached result silently answer for a
# different one (see get_indices' docstring for the real bug this caused).
# Migrated to ForecastCache 2026-07-19 (backlog.txt "ForecastCache EXISTS,
# BUT ~14 HAND-ROLLED TTL DICTS..."); already used monotonic time via the
# old _indices_loaded_at sibling variable, now owned by ForecastCache
# itself instead. Never negative-cached (an all-zero failure result is
# returned but deliberately NOT written to cache -- see the H-17 comment in
# get_indices -- so plain .get() is unambiguous).
_INDICES_TTL_SECS: float = 86400.0
_indices_cache: ForecastCache[dict] = ForecastCache(ttl_secs=_INDICES_TTL_SECS)
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
    Results are cached with a 24-hour TTL, keyed by (year, month) -- 2026-07-19
    fix: a single shared "latest" slot let one target month's cached result
    silently answer for a DIFFERENT target month, which temperature_adjustment()
    (called once per scanned market with that market's own target_date) could
    hit for real: a scan cycle spanning a month boundary (any multi-day-out
    market near month-end) would apply the wrong city-wide climate-index
    adjustment to whichever markets were analyzed after the first one cached a
    different month's result. Thread-safe.
    """
    from utils import utc_today as _utc_today

    now = _utc_today()
    year = target_year or now.year
    month = target_month or now.month
    cache_key = (year, month)

    with _indices_lock:
        _cached_indices = _indices_cache.get(cache_key)
        if _cached_indices is not None:
            return _cached_indices

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
        # for the next 24 hours — skip the _indices_cache.set() call below so the
        # next call retries immediately instead of hitting a frozen zero result.
        if result["ao"] == 0.0 and result["nao"] == 0.0 and result["enso"] == 0.0:
            import logging as _ci_log

            _ci_log.getLogger(__name__).warning(
                "climate_indices: all three NOAA fetches returned empty — "
                "NOT caching zero result; will retry on next call"
            )
            return result  # return zeros for this call but don't update the timestamp

        _indices_cache.set(cache_key, result)
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


# City-specific atmospheric-index sensitivity coefficients (°F per unit index
# value), by season. Moved to module level 2026-07-19 (previously 3 dict
# literals rebuilt from scratch inside temperature_adjustment() on every
# call) so per-city coverage is inspectable for the completeness manifest
# (backlog.txt "PER-CITY KNOWLEDGE SCATTERED ACROSS ~8 REGISTRIES") without
# needing to execute or parse the function body. The original 10 cities'
# values below (NYC through Atlanta) are unchanged hand-set domain-knowledge
# estimates -- "other" is the original ternary's trailing else-branch
# (June-November, where AO/NAO influence is weak and wasn't split further).
#
# The remaining 10 (Austin through NewOrleans) were researched 2026-07-25
# (backlog.txt "PER-CITY KNOWLEDGE" follow-up) via real regression -- REVISED
# same day after an independent review caught a real methodological gap in
# the first pass (see git history for the superseded, more optimistic first
# version). Methodology: monthly mean temp anomaly (city's 30yr Open-Meteo
# archive, vs. that city's own per-month climatological normal, linearly
# detrended by year to rule out a secular-warming confound) regressed
# against the PRIOR month's real NOAA CPC AO/NAO/ONI value -- lag 1, not
# lag 0 -- because get_indices() can only ever return an already-published
# index value, and CPC hasn't published the current month's AO/NAO/ONI by
# the time a near-term market for that same month is actually being scanned
# (verified live: get_indices(7, 2026), run 2026-07-25, returns JUNE
# AO/NAO and MAY ONI, not July's). The first pass fit lag-0 and looked much
# stronger than what the live code can actually use; refitting at the lag
# `get_indices()` actually returns collapses almost all of the AO/NAO
# signal (AO/NAO lag-1 autocorrelation is only ~0.3), while ENSO mostly
# survives (ONI lag-1 autocorrelation ~0.97, since El Nino/La Nina states
# persist for months). Bucketed by the same 3 (2 for ENSO) seasons as this
# table, n=93-279 per cell (scipy.stats.linregress). A cell only gets the
# fitted slope if it clears BOTH p<0.05 AND Benjamini-Hochberg FDR control
# at 5% across the 80 cells tested this pass (10 cities x 8 cells) -- the
# BH step matters here specifically because testing 80 cells at a raw 0.05
# threshold would produce ~4 false positives by chance alone, and the first
# pass had adopted several cells that were only raw-significant, not
# FDR-significant. Anything short of both bars keeps the flat
# DEFAULT_AO_SENS/NAO_SENS/ENSO_SENS value (per-city notes below record
# which cells are real vs. default-filled) -- for 6 of the 10 researched
# cities (Washington/Philadelphia/Minneapolis/Houston/LasVegas/NewOrleans),
# NOTHING survived this bar, so their entries below are 100% default
# values: still worth recording explicitly (vs. leaving the city out of the
# dict entirely, which would behave identically) because it turns "not yet
# researched" into "researched, no real signal found at a usable lag" in
# the completeness manifest -- a genuine, evidenced null result, not an
# unresearched gap.
# Known simplification carried over from the original 10 (not introduced
# here): the regression's temperature series is the daily (high+low)/2
# mean, but temperature_adjustment()'s single index_adj is applied
# identically to both KXHIGH (max) and KXLOW (min) markets. A city whose
# AO/NAO/ENSO response is asymmetric between max and min (physically
# plausible -- these indices shift cloud cover and dewpoint, which tend to
# move overnight lows more than daytime highs) would have a coefficient
# that's some kind of average of two different true effects, not exactly
# right for either market type. Splitting by max vs. min would double the
# regression's cell count and require rethinking the "one adjustment per
# city" shape of AO_SENS/NAO_SENS/ENSO_SENS -- out of scope for this pass.
# Deliberately did NOT re-derive the original 10's hand-set values even
# though the same regression disagrees with several of them (e.g. Denver's
# AO is insignificant/wrong-signed at every season in the real 31yr record,
# same for Seattle) -- revising values already live in the paper-trading
# blend is separate, larger-blast-radius scope than filling the 10 gaps
# that were asked for; the specific disagreeing cells are filed as their
# own backlog.txt follow-up instead of silently left unlisted.
AO_SENS: dict[str, dict[str, float]] = {
    "NYC": {"winter": 2.0, "spring": 1.2, "other": 0.4},
    "Boston": {"winter": 2.0, "spring": 1.2, "other": 0.4},
    "Chicago": {"winter": 2.2, "spring": 1.3, "other": 0.5},
    "Miami": {"winter": 0.6, "spring": 0.3, "other": 0.1},
    "LA": {"winter": 0.3, "spring": 0.3, "other": 0.3},
    "Dallas": {"winter": 1.2, "spring": 0.7, "other": 0.3},
    "Phoenix": {"winter": 0.5, "spring": 0.3, "other": 0.1},
    "Seattle": {"winter": 1.0, "spring": 0.8, "other": 0.3},
    "Denver": {"winter": 1.8, "spring": 1.0, "other": 0.4},
    "Atlanta": {"winter": 1.0, "spring": 0.6, "other": 0.2},
    # None of the 10 researched cities' AO cells survived lag-1 + BH-FDR --
    # all-default across the board (see module comment above).
    "Austin": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Washington": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Philadelphia": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "OklahomaCity": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "SanFrancisco": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Minneapolis": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Houston": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "SanAntonio": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "LasVegas": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "NewOrleans": {"winter": 0.5, "spring": 0.5, "other": 0.5},
}

NAO_SENS: dict[str, dict[str, float]] = {
    "NYC": {"winter": 1.2, "spring": 0.7, "other": 0.2},
    "Boston": {"winter": 1.3, "spring": 0.8, "other": 0.2},
    "Chicago": {"winter": 0.8, "spring": 0.5, "other": 0.2},
    "Miami": {"winter": 0.4, "spring": 0.2, "other": 0.1},
    "LA": {"winter": 0.2, "spring": 0.2, "other": 0.2},
    "Dallas": {"winter": 0.5, "spring": 0.3, "other": 0.1},
    "Phoenix": {"winter": 0.2, "spring": 0.1, "other": 0.1},
    "Seattle": {"winter": 0.6, "spring": 0.4, "other": 0.2},
    "Denver": {"winter": 0.7, "spring": 0.4, "other": 0.2},
    "Atlanta": {"winter": 0.6, "spring": 0.3, "other": 0.1},
    # None of the 10 researched cities' NAO cells survived lag-1 + BH-FDR
    # either -- all-default (closest raw-significant miss was OklahomaCity
    # NAO-other, p=0.042 raw but not FDR-significant across the 80 cells).
    "Austin": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Washington": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Philadelphia": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "OklahomaCity": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "SanFrancisco": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Minneapolis": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Houston": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "SanAntonio": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "LasVegas": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "NewOrleans": {"winter": 0.4, "spring": 0.4, "other": 0.4},
}

# ENSO's original ternary only ever had 2 branches (winter vs everything
# else) -- preserved as 2 buckets here rather than inventing a spring-
# specific value that was never there. temperature_adjustment() collapses
# "spring"/"other" to the same "other" lookup key for this table only.
#
# 4 of the 10 researched cities cleared lag-1 + BH-FDR, all in the "other"
# season, and 3 of the 4 (Austin/OklahomaCity/SanAntonio) are NEGATIVE --
# every other cell in this table, old and new, is positive. Adopted as-is
# (2026-07-25, explicit user confirmation, reaffirmed after the lag/FDR
# correction made these 4 cells the ONLY ones surviving the strictest test
# applied this pass): physically plausible (Gulf Coast ENSO teleconnection
# during Jun-Nov, which includes hurricane season, is a documented
# different pattern than the East Coast winter relationship the hand-set 10
# were tuned on) -- excluding it only because the sign is novel would mean
# the significance floor wasn't the actual rule being applied.
ENSO_SENS: dict[str, dict[str, float]] = {
    "NYC": {"winter": 1.0, "other": 0.3},
    "Boston": {"winter": 1.0, "other": 0.3},
    "Chicago": {"winter": 0.8, "other": 0.3},
    "Miami": {"winter": 0.5, "other": 0.2},
    "LA": {"winter": 0.8, "other": 0.4},
    "Dallas": {"winter": 1.0, "other": 0.4},
    "Phoenix": {"winter": 1.2, "other": 0.5},
    "Seattle": {"winter": 0.9, "other": 0.5},
    "Denver": {"winter": 0.9, "other": 0.3},
    "Atlanta": {"winter": 0.7, "other": 0.3},
    # other: fitted, negative, n=279, p=0.001, survives BH-FDR
    "Austin": {"winter": 0.4, "other": -0.7},
    "Washington": {"winter": 0.4, "other": 0.4},  # none significant
    "Philadelphia": {"winter": 0.4, "other": 0.4},  # none significant
    # other: fitted, negative, n=279, p=0.003, survives BH-FDR
    "OklahomaCity": {"winter": 0.4, "other": -0.7},
    # other: fitted, POSITIVE (real West Coast ENSO teleconnection,
    # opposite sign from the Gulf Coast cities above), n=279, p<0.001,
    # survives BH-FDR. winter: not significant, stays default.
    "SanFrancisco": {"winter": 0.4, "other": 0.6},
    "Minneapolis": {"winter": 0.4, "other": 0.4},  # winter raw p=0.008 but not FDR-sig
    "Houston": {"winter": 0.4, "other": 0.4},  # winter/other raw-sig but not FDR-sig
    # other: fitted, negative, n=279, p=0.002, survives BH-FDR
    "SanAntonio": {"winter": 0.4, "other": -0.6},
    "LasVegas": {"winter": 0.4, "other": 0.4},  # none significant
    "NewOrleans": {"winter": 0.4, "other": 0.4},  # none significant
}

DEFAULT_AO_SENS = 0.5
DEFAULT_NAO_SENS = 0.4
DEFAULT_ENSO_SENS = 0.4


def _season_bucket(month: int) -> str:
    """Northern Hemisphere season category used to key AO_SENS/NAO_SENS."""
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    return "other"


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

    season = _season_bucket(target_date.month)
    enso_season = season if season == "winter" else "other"  # ENSO has only 2 buckets

    ao_adj = ao * AO_SENS.get(city, {}).get(season, DEFAULT_AO_SENS)
    nao_adj = nao * NAO_SENS.get(city, {}).get(season, DEFAULT_NAO_SENS)
    enso_adj = enso * ENSO_SENS.get(city, {}).get(enso_season, DEFAULT_ENSO_SENS)

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
