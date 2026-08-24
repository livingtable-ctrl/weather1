"""
Climate indices from NOAA Climate Prediction Center.
Fetches AO (Arctic Oscillation), NAO (North Atlantic Oscillation), and
ENSO (El Niño/La Niña via ONI index).

These large-scale patterns shift temperature distributions beyond what
short-range ensemble models can capture — especially for the climatological
baseline probability.

Temperature adjustment logic (applied to climatological baseline only):
  Per-city, per-season °F-per-unit-index coefficients, in AO_SENS/NAO_SENS/
  ENSO_SENS below. As of 2026-07-25 (re-derived via real lag-1 regression
  against each city's 31yr temp record, replacing the original hand-set
  East Coast estimates this docstring used to describe) only a handful of
  cells across all 20 cities clear a Benjamini-Hochberg FDR significance
  bar -- most cities are flat DEFAULT_AO_SENS/NAO_SENS/ENSO_SENS in every
  season. See the module comment directly above each table for the current
  per-city breakdown; do not hand-restate specific numbers here, they will
  drift the next time a city's fit changes.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, date, datetime

import requests

import safe_io
from forecast_cache import ForecastCache
from paths import PDO_PNA_PATH as _PDO_PNA_PATH

_log = logging.getLogger(__name__)

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
        # H-17 + L-6: don't cache when ANY of the three raw fetches came back
        # empty, not just when the combined result happens to be all-zero.
        # Both _fetch_monthly_index and _fetch_enso return {} whenever that
        # source has NO usable data this cycle -- a request exception (their
        # own except clauses), or a 200 response whose body simply parsed to
        # zero valid rows. A non-empty dict that just has no entry for this
        # specific (year, month) is different: it still yields 0.0 via
        # latest()'s own default, so checking the RESULT's zero-ness
        # conflated "this source has nothing at all" with "this source's
        # real recent value happens to be near zero". The original all-zero
        # check missed
        # a partial outage entirely: e.g. AO fails (0.0, spurious) while NAO/
        # ENSO succeed -- not all three are 0.0, so the old guard cached the
        # combined result anyway, freezing AO's failure into the shared
        # (year, month) slot for the full 24h TTL even after AO recovered.
        if not ao_data or not nao_data or not enso_data:
            _log.warning(
                "climate_indices: at least one NOAA fetch failed this cycle "
                "(ao=%s nao=%s enso=%s) — NOT caching a partial result; will "
                "retry on next call",
                bool(ao_data),
                bool(nao_data),
                bool(enso_data),
            )
            return result  # return what we have for this call but don't cache it

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
# needing to execute or parse the function body. "other" is the original
# ternary's trailing else-branch (June-November, where AO/NAO influence is
# weak and wasn't split further).
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
#
# RE-DERIVED 2026-07-25 (later same session, backlog.txt "EXISTING 10
# climate_indices CITIES' HAND-SET AO/NAO/ENSO VALUES DISAGREE WITH THE REAL
# 31-YEAR REGRESSION", explicit user confirmation): the original 10's
# hand-set values below were replaced by applying the IDENTICAL lag-1 +
# BH-FDR regression used for the 10 gap cities above, at the same evidenced-
# only bar -- a cell keeps a non-default value only if it clears BOTH
# p<0.05 AND Benjamini-Hochberg FDR control at 5% across the 80 cells tested
# this pass (10 cities x 8 cells, same shape/count as the gap-fill pass, so
# the two 80-cell BH corrections are independent of each other). Only 4 of
# 80 cells survive: Miami AO-spring, Miami NAO-spring, Seattle ENSO-other,
# Denver ENSO-other -- every other cell for these 10 cities reverts to the
# flat DEFAULT_AO_SENS/NAO_SENS/ENSO_SENS value, replacing the previous
# hand-set domain-knowledge numbers entirely (not a magnitude tweak -- e.g.
# Denver's ENSO-"other" flips sign from hand-set +0.3 to fitted -1.0).
# Non-significance here isn't proof the removed values were wrong, only
# that the real 31yr record at the lag get_indices() actually returns gives
# no usable evidence for or against them -- same evidenced-only standard
# already applied to the gap cities, not a stricter one invented for this
# pass. Re-verified live before adopting: re-running this regression from
# scratch reproduced the backlog entry's own numbers to 2-3 decimals.
AO_SENS: dict[str, dict[str, float]] = {
    # Re-derived 2026-07-25 -- only Miami-spring survives lag-1 + BH-FDR of
    # all 30 AO cells across these 10 cities; see module comment above.
    "NYC": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Boston": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Chicago": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    # spring: fitted, positive, n=93, p<0.001, survives BH-FDR
    "Miami": {"winter": 0.5, "spring": 0.6, "other": 0.5},
    "LA": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Dallas": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Phoenix": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Seattle": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Denver": {"winter": 0.5, "spring": 0.5, "other": 0.5},
    "Atlanta": {"winter": 0.5, "spring": 0.5, "other": 0.5},
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
    # Re-derived 2026-07-25 (see AO_SENS module comment above for the full
    # methodology/rationale). 3 of 30 NAO cells clear raw p<0.05 (Miami-
    # winter p=0.027, Miami-spring p=0.002, Atlanta-spring p=0.024) but only
    # Miami-spring also survives BH-FDR across the 80 cells tested -- Miami-
    # winter and Atlanta-spring revert to default rather than being kept on
    # a looser bar than the gap cities got.
    "NYC": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Boston": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Chicago": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    # winter: raw-sig p=0.027 but not FDR-sig -- stays default
    # spring: fitted, positive, n=93, p=0.002, survives BH-FDR
    "Miami": {"winter": 0.4, "spring": 0.6, "other": 0.4},
    "LA": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Dallas": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Phoenix": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Seattle": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    "Denver": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    # spring: raw-sig p=0.024 but not FDR-sig -- stays default
    "Atlanta": {"winter": 0.4, "spring": 0.4, "other": 0.4},
    # None of the 10 researched cities' NAO cells survived lag-1 + BH-FDR
    # either -- all-default (closest raw-significant miss across these 10
    # is NewOrleans NAO-winter, p=0.030 raw but not FDR-significant across
    # the 80 cells; OklahomaCity NAO-other is the next-closest at p=0.042).
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
# season: Austin/OklahomaCity/SanAntonio negative, SanFrancisco positive
# (a real West Coast ENSO teleconnection, opposite sign from the Gulf Coast
# cities). Adopted as-is (2026-07-25, explicit user confirmation,
# reaffirmed after the lag/FDR correction made these 4 cells the ONLY ones
# surviving the strictest test applied this pass): physically plausible
# (Gulf Coast ENSO teleconnection during Jun-Nov, which includes hurricane
# season, is a documented different pattern than the East Coast winter
# relationship the original 10's since-replaced hand-set values were tuned
# on -- see AO_SENS module comment above) -- excluding a cell only because
# its sign is novel would mean the significance floor wasn't the actual
# rule being applied. 2 more of the 10 (Dallas/Phoenix ENSO-other) are also
# negative and raw-significant but don't survive BH-FDR, so they stay
# default rather than being adopted on a looser bar.
#
# RE-DERIVED 2026-07-25 (later same session, see AO_SENS module comment
# above for the full methodology): the original 10's since-replaced
# hand-set ENSO values below went through the identical lag-1 + BH-FDR
# regression. 5 of 20 ENSO cells clear raw p<0.05 (Seattle-winter, Seattle-
# other, Denver-other, Dallas-other, Phoenix-other) but only Seattle-other
# and Denver-other survive BH-FDR. Denver's fitted ENSO-other is NEGATIVE
# (-1.0) -- the opposite sign from its removed hand-set value (+0.3), and
# the table's 4th negative cell overall alongside the 3 gap-city negatives
# above (Austin/OklahomaCity/SanAntonio).
ENSO_SENS: dict[str, dict[str, float]] = {
    "NYC": {"winter": 0.4, "other": 0.4},
    "Boston": {"winter": 0.4, "other": 0.4},
    "Chicago": {"winter": 0.4, "other": 0.4},
    "Miami": {"winter": 0.4, "other": 0.4},
    "LA": {"winter": 0.4, "other": 0.4},
    # other: raw-sig p=0.005 and NEGATIVE (wrong-signed vs. removed hand-set
    # +0.4) but not FDR-sig -- stays default
    "Dallas": {"winter": 0.4, "other": 0.4},
    # other: raw-sig p=0.021 and NEGATIVE (wrong-signed vs. removed hand-set
    # +0.5) but not FDR-sig -- stays default
    "Phoenix": {"winter": 0.4, "other": 0.4},
    # other: fitted, positive, n=279, p<0.001, survives BH-FDR. winter:
    # raw-sig p=0.003 but not FDR-sig, stays default.
    "Seattle": {"winter": 0.4, "other": 0.7},
    # other: fitted, NEGATIVE (opposite sign from hand-set +0.3), n=279,
    # p<0.001, survives BH-FDR
    "Denver": {"winter": 0.4, "other": -1.0},
    "Atlanta": {"winter": 0.4, "other": 0.4},
    # other: fitted, negative, n=279, p=0.001, survives BH-FDR
    "Austin": {"winter": 0.4, "other": -0.7},
    "Washington": {"winter": 0.4, "other": 0.4},  # none significant
    "Philadelphia": {"winter": 0.4, "other": 0.4},  # none significant
    # other: fitted, negative, n=279, p=0.002, survives BH-FDR (the
    # tightest BH-FDR cutoff cell of the 4 gap-city survivors)
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
    try:
        # Default retries=3 (up to ~3.5s worst case, see safe_io._replace_
        # with_retry's own docstring) is kept rather than lowered for this
        # call specifically (opus-review-caught 2026-08-08: this write sits
        # on the live per-market analyze_trade() path, so a persistent disk
        # failure here compounds across every market scanned) -- consistent
        # with every other atomic_write_json call site in this codebase,
        # including several others also reachable from the same per-market
        # path (e.g. weather_markets.py's HOURLY_TARGET_HOURS_PATH write).
        # The added latency only manifests when the disk is ALREADY failing
        # writes persistently, a state this fail-open handling already
        # accepts as degraded; singling out this one site with a shorter
        # retry budget would trade a small amount of write reliability for
        # negligible benefit in the common case.
        safe_io.atomic_write_json(payload, _PDO_PNA_PATH)
    except Exception as _e:
        # A cache-write failure must not discard data already fetched
        # successfully from NOAA -- mirrors hurricane_climatology.
        # fetch_hurdat2_raw's own fail-open shape for the identical
        # situation. Without this, the exception would propagate to
        # get_pdo_pna()'s own except Exception (below), silently returning
        # {"pdo": 0.0, "pna": 0.0} to apply_pdo_pna_correction() -- a live
        # model-input path. This only bites once a stale pdo_pna.json
        # already exists and a refresh write then fails (the file must
        # exist for weather_markets._pdopna_blend_active() to ever let this
        # path run at all -- a first-ever write failure is unreachable from
        # the live path) -- but in that state, WITHOUT this fail-open, every
        # call would return zeros for as long as writes kept failing, not
        # just for one TTL window (a failed write never lands the file, so
        # there's no successful refresh to start a new TTL cycle from).
        _log.warning("fetch_pdo_pna: cache write failed for %s: %s", _PDO_PNA_PATH, _e)
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
            data = json.loads(_PDO_PNA_PATH.read_text(encoding="utf-8"))
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

    M-18d: `season` below is derived from the caller's own target `month`,
    but get_pdo_pna() previously ran with no arguments -- defaulting to the
    CURRENT UTC month's index lookback regardless of what `month` actually
    was. That mixes a target month's seasonal coefficient with a
    potentially different month's index value, the exact defect class
    get_indices() was already fixed for (see its own docstring) and that
    temperature_adjustment() above already avoids by passing target_date's
    own month/year through. Thread `month` through to get_pdo_pna(month=...)
    so the coefficient and the index lookback agree on which month they're
    both about. Year is deliberately NOT threaded through the same way: the
    sole production caller (weather_markets.py, out of scope for this
    module) only ever passes `month`, not a year -- get_pdo_pna() keeps
    resolving the current year by its own existing default, same as before
    this fix.
    """
    season = _month_to_season(month)
    pdo_coeff = _PDO_TEMP_COEFF.get(city, {}).get(season, 0.0)
    pna_coeff = _PNA_TEMP_COEFF.get(city, {}).get(season, 0.0)

    if pdo_coeff == 0.0 and pna_coeff == 0.0:
        return 0.0

    indices = get_pdo_pna(month=month)
    correction = pdo_coeff * indices["pdo"] + pna_coeff * indices["pna"]
    return round(max(-3.0, min(3.0, correction)), 2)
