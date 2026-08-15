---
type: community
cohesion: 0.04
members: 67
---

# Climatology & Climate Index Fetching

**Cohesion:** 0.04 - loosely connected
**Members:** 67 nodes

## Members
- [[NOTE this gate only protects preload_all()'s own (always force=True)]] - rationale - climatology.py
- [[28 Return the current ONI (ENSO) index value, or None if unavailable.…]] - rationale - climate_indices.py
- [[dot-test_days_out_frozen()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_is_controllable_via_patch()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_matches_datetime_now_utc()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_mos_imports_utc_today()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_returns_date_object()]] - code - tests/test_phase2_batch_h.py
- [[Callers can freeze time by patching utils.utc_today.]] - rationale - tests/test_phase2_batch_h.py
- [[Cities in city_coords not yet present -- or present with no real computed data,…]] - rationale - climatology.py
- [[Climate indices from NOAA Climate Prediction Center. Fetches AO (Arctic…]] - rationale - climate_indices.py
- [[Compute per-month forecast sigma (°F) from 30yr climate archive for one city.…]] - rationale - climatology.py
- [[Download 30 years of daily highlow for a city and cache to disk. Auto-…]] - rationale - climatology.py
- [[Estimate temperature adjustment (°F) to apply to the climatological baseline…]] - rationale - climate_indices.py
- [[Fetch and cache historical data for all cities. Refreshes stale caches.]] - rationale - climatology.py
- [[GET Open-Meteo Seasonal (monthly=precipitation_mean -- NOT precipitation_sum,…]] - rationale - acis_precip.py
- [[Historical climatology from Open-Meteo archive API. Fetches 30 years of daily…]] - rationale - climatology.py
- [[Map calendar month (1-12) to meteorological season abbreviation.]] - rationale - climate_indices.py
- [[Northern Hemisphere season category used to key AO_SENSNAO_SENS.]] - rationale - climate_indices.py
- [[P2-18P2-25 mos.fetch_mos must use UTC date for days_out.]] - rationale - tests/test_phase2_batch_h.py
- [[Parse a NOAA CPC monthly index table (year + up to 12 monthly values per row).…]] - rationale - climate_indices.py
- [[Parse a NOAA teleconnections CSV (Date=YYYYMM, Value columns). Returns {YYYYMM…]] - rationale - climate_indices.py
- [[Parse the ONI (Oceanic Niño Index) from NOAA CPC. Returns dict keyed by (year,…]] - rationale - climate_indices.py
- [[Patching _utc_today in mos changes sigma lookup.]] - rationale - tests/test_phase2_batch_h.py
- [[Path_28]] - code
- [[Phase 2 Batch H Regression Tests]] - code - tests/test_phase2_batch_h.py
- [[Phase 2 Batch H regression tests P2-18 + P2-25 — UTC date consistency.]] - rationale - tests/test_phase2_batch_h.py
- [[Probability of the market condition based purely on historical observations.…]] - rationale - climatology.py
- [[Read _SIGMA_CACHE_PATH and return its dict content, or {} on any readparse…]] - rationale - climatology.py
- [[Return True if the cache file is missing or older than CACHE_MAX_AGE seconds.]] - rationale - climatology.py
- [[Return current (or specified) AO, NAO, ENSO values. Results are cached with a…]] - rationale - climate_indices.py
- [[Return current PDO and PNA values. Reads from file; fetches if stale or absent.…]] - rationale - climate_indices.py
- [[Return per-city, per-month forecast sigmas computed from 30yr climate archive.…]] - rationale - climatology.py
- [[Return temperature bias correction (degrees F) based on PDOPNA for city and…]] - rationale - climate_indices.py
- [[Return the current UTC date. Use everywhere instead of date.today().]] - rationale - utils.py
- [[TestMosUtcDate]] - code - tests/test_phase2_batch_h.py
- [[TestUtcToday]] - code - tests/test_phase2_batch_h.py
- [[True if a per-city sigma cache entry has at least one real computed month…]] - rationale - climatology.py
- [[_cache_is_stale()_3]] - code - climatology.py
- [[_cache_path()_3]] - code - climatology.py
- [[_climatological_prob_inner()]] - code - climatology.py
- [[_fetch_enso()]] - code - climate_indices.py
- [[_fetch_monthly_index()]] - code - climate_indices.py
- [[_fetch_noaa_csv_index()]] - code - climate_indices.py
- [[_load_sigma_cache_file()]] - code - climatology.py
- [[_month_to_season()_1]] - code - climate_indices.py
- [[_season_bucket()]] - code - climate_indices.py
- [[_sigma_cache_missing_cities()]] - code - climatology.py
- [[_sigma_entry_has_data()]] - code - climatology.py
- [[apply_pdo_pna_correction()]] - code - climate_indices.py
- [[climate_indices.py]] - code - climate_indices.py
- [[climatological_prob()]] - code - climatology.py
- [[climatology.py]] - code - climatology.py
- [[compute_sigma_from_climate()]] - code - climatology.py
- [[date_8]] - code
- [[date_9]] - code
- [[date_10]] - code
- [[fetch_historical()]] - code - climatology.py
- [[fetch_seasonal_precip_mean_mm()]] - code - acis_precip.py
- [[get_enso_index()]] - code - climate_indices.py
- [[get_indices()]] - code - climate_indices.py
- [[get_pdo_pna()]] - code - climate_indices.py
- [[load_all_sigmas()]] - code - climatology.py
- [[main.py setup wizard]] - code - main.py
- [[preload_all()]] - code - climatology.py
- [[temperature_adjustment()]] - code - climate_indices.py
- [[utc_today()]] - code - utils.py
- [[utc_today() must return UTC date, not local-clock date.]] - rationale - tests/test_phase2_batch_h.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Climatology__Climate_Index_Fetching
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 8 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 8 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 8 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 7 edges to [[_COMMUNITY_Black Swan Halt State]]
- 6 edges to [[_COMMUNITY_Community 62]]
- 5 edges to [[_COMMUNITY_Community 51]]
- 5 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 5 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 4 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 3 edges to [[_COMMUNITY_Community 169]]
- 3 edges to [[_COMMUNITY_Community 26]]
- 3 edges to [[_COMMUNITY_Community 79]]
- 2 edges to [[_COMMUNITY_Community 44]]
- 2 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 2 edges to [[_COMMUNITY_Community 344]]
- 2 edges to [[_COMMUNITY_Community 87]]
- 2 edges to [[_COMMUNITY_Community 119]]
- 2 edges to [[_COMMUNITY_Community 302]]
- 2 edges to [[_COMMUNITY_Community 99]]
- 2 edges to [[_COMMUNITY_Community 182]]
- 2 edges to [[_COMMUNITY_Community 59]]
- 1 edge to [[_COMMUNITY_Community 517]]
- 1 edge to [[_COMMUNITY_Community 518]]
- 1 edge to [[_COMMUNITY_Community 519]]
- 1 edge to [[_COMMUNITY_Community 554]]
- 1 edge to [[_COMMUNITY_Community 168]]
- 1 edge to [[_COMMUNITY_Community 288]]
- 1 edge to [[_COMMUNITY_Community 501]]
- 1 edge to [[_COMMUNITY_Community 604]]
- 1 edge to [[_COMMUNITY_Community 82]]
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Community 194]]
- 1 edge to [[_COMMUNITY_Community 109]]
- 1 edge to [[_COMMUNITY_Community 181]]
- 1 edge to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 1 edge to [[_COMMUNITY_Community 56]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 497]]
- 1 edge to [[_COMMUNITY_Community 202]]
- 1 edge to [[_COMMUNITY_Community 31]]

## Top bridge nodes
- [[utc_today()]] - degree 51, connects to 21 communities
- [[climatology.py]] - degree 29, connects to 11 communities
- [[Phase 2 Batch H Regression Tests]] - degree 13, connects to 9 communities
- [[climate_indices.py]] - degree 20, connects to 7 communities
- [[load_all_sigmas()]] - degree 17, connects to 7 communities