---
type: community
cohesion: 0.06
members: 55
---

# Community 23

**Cohesion:** 0.06 - loosely connected
**Members:** 55 nodes

## Members
- [[dot-test_is_controllable_via_patch()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_matches_datetime_now_utc()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_returns_date_object()]] - code - tests/test_phase2_batch_h.py
- [[Callers can freeze time by patching utils.utc_today.]] - rationale - tests/test_phase2_batch_h.py
- [[Derive an ACIS StnData `sid` from metar.MARKET_STATION_MAPcity by stripping…]] - rationale - acis_precip.py
- [[For each historical year present in `history`, sum the remaining_start_day,…]] - rationale - acis_precip.py
- [[GET Open-Meteo Seasonal (monthly=precipitation_mean -- NOT precipitation_sum,…]] - rationale - acis_precip.py
- [[GET Open-Meteo Seasonal (monthly=snowfall_mean -- confirmed live 2026-07-30 as…]] - rationale - acis_snow.py
- [[Mirrors weather_markets._bootstrap_ci_precip's exact resampling shape n…]] - rationale - acis_precip.py
- [[NOAA ACIS StnData (month-to-date actual + historical daily precipitation) and…]] - rationale - acis_precip.py
- [[NOAA ACIS StnData (month-to-date actual + historical daily snowfall) and Open-…]] - rationale - acis_snow.py
- [[No Test for Concurrent Cache Access]] - document - docs/grade_audit/outputs/forecast_cache.py.md
- [[One POST call covering the full `years`-year daily history, disk- cached so one…]] - rationale - acis_precip.py
- [[One POST call covering the full `years`-year daily snowfall history, disk-…]] - rationale - acis_snow.py
- [[Own copy, not imported from acis_precip that module's version reads…]] - rationale - acis_snow.py
- [[POST to ACIS StnData for sdate=YYYY-MM-01 through through_day (always…]] - rationale - acis_precip.py
- [[POST to ACIS StnData for sdate=YYYY-MM-01 through through_day (always…_1]] - rationale - acis_snow.py
- [[Parse one ACIS 'pcpn' daily value. Returns None for missing unparseable (never…]] - rationale - acis_precip.py
- [[Parse one ACIS 'snow' daily value. Returns None for missing unparseable (never…]] - rationale - acis_snow.py
- [[Path_9]] - code
- [[Path_10]] - code
- [[Phase 2 Batch H regression tests P2-18 + P2-25 — UTC date consistency.]] - rationale - tests/test_phase2_batch_h.py
- [[Return the current UTC date. Use everywhere instead of date.today().]] - rationale - utils.py
- [[Returns (possibly-shifted remaining_sums, tilt_applied). No-ops…]] - rationale - acis_precip.py
- [[TestUtcToday]] - code - tests/test_phase2_batch_h.py
- [[Thread-safe in-memory forecast cache with TTL expiry. Replaces the module-level…]] - rationale - forecast_cache.py
- [[_cache_is_stale()_1]] - code - acis_precip.py
- [[_cache_is_stale()_2]] - code - acis_snow.py
- [[_cache_path()_1]] - code - acis_precip.py
- [[_cache_path()_2]] - code - acis_snow.py
- [[_load_stale_cache_or_none()]] - code - acis_precip.py
- [[_load_stale_cache_or_none()_1]] - code - acis_snow.py
- [[_parse_pcpn_value()]] - code - acis_precip.py
- [[_parse_snow_value()]] - code - acis_snow.py
- [[_station_sid_for_city()]] - code - acis_precip.py
- [[acis_precip.py]] - code - acis_precip.py
- [[acis_snow.py]] - code - acis_snow.py
- [[apply_seasonal_tilt()]] - code - acis_precip.py
- [[bootstrap_ci_month_total()]] - code - acis_precip.py
- [[date_5]] - code
- [[fetch_historical_daily()]] - code - acis_precip.py
- [[fetch_historical_daily_snow()]] - code - acis_snow.py
- [[fetch_month_to_date_actual()]] - code - acis_precip.py
- [[fetch_month_to_date_actual_snow()]] - code - acis_snow.py
- [[fetch_seasonal_precip_mean_mm()]] - code - acis_precip.py
- [[fetch_seasonal_snow_mean_cm()]] - code - acis_snow.py
- [[forecast_cache.py]] - code - forecast_cache.py
- [[forecast_cache.py File Grade median 810, all TIER1]] - document - docs/grade_audit/outputs/forecast_cache.py.md
- [[forecast_cache.py Grade Audit]] - document - docs/grade_audit/outputs/forecast_cache.py.md
- [[historical_remaining_and_full_month_sums()]] - code - acis_precip.py
- [[len(entry)==3 Storage-Format Discriminator Fragility]] - document - docs/grade_audit/outputs/forecast_cache.py.md
- [[set_at() Bypasses max_size Eviction Guard (710)]] - document - docs/grade_audit/outputs/forecast_cache.py.md
- [[test_phase2_batch_h.py]] - code - tests/test_phase2_batch_h.py
- [[utc_today()]] - code - utils.py
- [[utc_today() must return UTC date, not local-clock date.]] - rationale - tests/test_phase2_batch_h.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_23
SORT file.name ASC
```

## Connections to other communities
- 24 edges to [[_COMMUNITY_Community 4]]
- 14 edges to [[_COMMUNITY_Community 6]]
- 7 edges to [[_COMMUNITY_Community 8]]
- 5 edges to [[_COMMUNITY_Community 0]]
- 5 edges to [[_COMMUNITY_Community 15]]
- 5 edges to [[_COMMUNITY_Community 2]]
- 4 edges to [[_COMMUNITY_Community 9]]
- 4 edges to [[_COMMUNITY_Community 102]]
- 4 edges to [[_COMMUNITY_Community 303]]
- 4 edges to [[_COMMUNITY_Community 3]]
- 3 edges to [[_COMMUNITY_Community 14]]
- 3 edges to [[_COMMUNITY_Community 5]]
- 2 edges to [[_COMMUNITY_Community 7]]
- 2 edges to [[_COMMUNITY_Community 226]]
- 2 edges to [[_COMMUNITY_Community 350]]
- 1 edge to [[_COMMUNITY_Community 575]]
- 1 edge to [[_COMMUNITY_Community 576]]
- 1 edge to [[_COMMUNITY_Community 577]]
- 1 edge to [[_COMMUNITY_Community 627]]
- 1 edge to [[_COMMUNITY_Community 628]]
- 1 edge to [[_COMMUNITY_Community 209]]
- 1 edge to [[_COMMUNITY_Community 453]]
- 1 edge to [[_COMMUNITY_Community 292]]
- 1 edge to [[_COMMUNITY_Community 96]]
- 1 edge to [[_COMMUNITY_Community 148]]
- 1 edge to [[_COMMUNITY_Community 99]]
- 1 edge to [[_COMMUNITY_Community 21]]
- 1 edge to [[_COMMUNITY_Community 35]]
- 1 edge to [[_COMMUNITY_Community 33]]
- 1 edge to [[_COMMUNITY_Community 141]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[utc_today()]] - degree 49, connects to 20 communities
- [[forecast_cache.py]] - degree 32, connects to 11 communities
- [[test_phase2_batch_h.py]] - degree 13, connects to 9 communities
- [[acis_precip.py]] - degree 28, connects to 7 communities
- [[acis_snow.py]] - degree 27, connects to 6 communities