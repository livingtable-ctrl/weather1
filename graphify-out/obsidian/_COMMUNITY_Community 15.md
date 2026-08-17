---
type: community
cohesion: 0.05
members: 64
---

# Community 15

**Cohesion:** 0.05 - loosely connected
**Members:** 64 nodes

## Members
- [[dot-test_M_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_T_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_all_M_codes_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_empty_string_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_na_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_none_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_nws_prob_at_median_is_near_half()]] - code - tests/test_nbm.py
- [[dot-test_nws_prob_below_is_complement_of_above()]] - code - tests/test_nbm.py
- [[dot-test_nws_prob_empty_quantiles_returns_half()]] - code - tests/test_nbm.py
- [[dot-test_nws_prob_uses_quantiles_above()]] - code - tests/test_nbm.py
- [[dot-test_rows_with_M_code_are_excluded()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_unknown_code_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_valid_float_string_returns_float()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_valid_int_returns_float()]] - code - tests/test_phase2_batch_a.py
- [[B2 Fetch MOS using the best available model for the given days_out. For…]] - rationale - mos.py
- [[CITY-LOCAL today for the given IANA tz, or UTC today if tz is None or…]] - rationale - mos.py
- [[Compute probability from NBM native quantiles using linear ECDF interpolation.…]] - rationale - nws.py
- [[Empty quantile dict should return 0.5 as a safe fallback.]] - rationale - tests/test_nbm.py
- [[Fetch MOS forecast for a station from the IEM API. Args station ASOS station…]] - rationale - mos.py
- [[Fetch NBM's native probabilistic quantiles ({10,25,50,75,90} temp_f) for a…]] - rationale - mos.py
- [[Fetch and parse every available NBS txn value for a station into {(local_date,…]] - rationale - mos.py
- [[Fetch and parse the station's current NBP bulletin into {(local_date,…]] - rationale - mos.py
- [[Fetch the real NBM daily maxmin for target_date from IEM's NBS bulletin --…]] - rationale - mos.py
- [[NOAA MOS (Model Output Statistics) via Iowa Environmental Mesonet API. Station-…]] - rationale - mos.py
- [[NWS AFD FetchParse Module]] - code - nws_afd.py
- [[P(T  threshold) + P(T  threshold) should approximately equal 1.]] - rationale - tests/test_nbm.py
- [[P(T  median) should be ~0.50 by definition.]] - rationale - tests/test_nbm.py
- [[P2-11 _parse_temp must handle ASOS special codes without crashing.]] - rationale - tests/test_phase2_batch_a.py
- [[P2-11 fetch_mos must exclude rows with ASOS special temp codes.]] - rationale - tests/test_phase2_batch_a.py
- [[Parse MOS temperature field, handling ASOS special codes.]] - rationale - mos.py
- [[Parse a raw NBP (NBM Probabilistic) AFOS text bulletin into {(local_date,…]] - rationale - mos.py
- [[Phase 2 Batch A regression tests P2-3, P2-8, P2-9, P2-11.]] - rationale - tests/test_phase2_batch_a.py
- [[Return True if a fresh MOS cache entry exists for this stationdate (no network…]] - rationale - mos.py
- [[Return the ASOS station code for a city, or None if unknown.]] - rationale - mos.py
- [[Split an NBP data row's pipe-delimited day-groups into a flat list of values,…]] - rationale - mos.py
- [[TestFetchMosSpecialCodes]] - code - tests/test_phase2_batch_a.py
- [[TestMosParseTemp]] - code - tests/test_phase2_batch_a.py
- [[TestNBMQuantiles]] - code - tests/test_nbm.py
- [[Tests for NBM data source integration.]] - rationale - tests/test_nbm.py
- [[Tests for mos.py's NBP (NBM probabilistic quantiles) parsing -- the core logic…]] - rationale - tests/test_mos_nbp.py
- [[_fetch_nbp_percentiles()]] - code - mos.py
- [[_fetch_nbs_daily_extremes()]] - code - mos.py
- [[_local_or_utc_today()]] - code - mos.py
- [[_parse_nbp_bulletin()]] - code - mos.py
- [[_parse_temp()]] - code - mos.py
- [[_split_nbp_row()]] - code - mos.py
- [[date_3]] - code
- [[fetch_hurdat2_raw Function]] - code - hurricane_climatology.py
- [[fetch_mos()]] - code - mos.py
- [[fetch_mos_best()]] - code - mos.py
- [[fetch_nbm_iem()]] - code - mos.py
- [[fetch_nbm_quantiles()]] - code - mos.py
- [[get_mos_station()]] - code - mos.py
- [[is_mos_cached()]] - code - mos.py
- [[load_basin_storms Function]] - code - hurricane_climatology.py
- [[mos.py]] - code - mos.py
- [[nws.nws_prob_from_quantiles]] - code - nws.py
- [[nws_prob_from_quantiles uses ECDF interpolation for above condition.]] - rationale - tests/test_nbm.py
- [[nws_prob_from_quantiles()]] - code - nws.py
- [[parse_hurdat2 Function]] - code - hurricane_climatology.py
- [[test_mos_nbp.py]] - code - tests/test_mos_nbp.py
- [[test_nbm.py]] - code - tests/test_nbm.py
- [[test_phase2_batch_a.py]] - code - tests/test_phase2_batch_a.py
- [[utils.KALSHI_FEE_RATE]] - code - utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_15
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_Community 4]]
- 8 edges to [[_COMMUNITY_Community 6]]
- 5 edges to [[_COMMUNITY_Community 145]]
- 5 edges to [[_COMMUNITY_Community 23]]
- 4 edges to [[_COMMUNITY_Community 9]]
- 4 edges to [[_COMMUNITY_Community 121]]
- 3 edges to [[_COMMUNITY_Community 53]]
- 3 edges to [[_COMMUNITY_Community 5]]
- 2 edges to [[_COMMUNITY_Community 126]]
- 1 edge to [[_COMMUNITY_Community 152]]
- 1 edge to [[_COMMUNITY_Community 285]]
- 1 edge to [[_COMMUNITY_Community 517]]
- 1 edge to [[_COMMUNITY_Community 623]]
- 1 edge to [[_COMMUNITY_Community 326]]
- 1 edge to [[_COMMUNITY_Community 11]]
- 1 edge to [[_COMMUNITY_Community 409]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 14]]
- 1 edge to [[_COMMUNITY_Community 382]]

## Top bridge nodes
- [[mos.py]] - degree 23, connects to 6 communities
- [[nws_prob_from_quantiles()]] - degree 15, connects to 6 communities
- [[test_mos_nbp.py]] - degree 15, connects to 6 communities
- [[test_nbm.py]] - degree 15, connects to 6 communities
- [[test_phase2_batch_a.py]] - degree 16, connects to 5 communities