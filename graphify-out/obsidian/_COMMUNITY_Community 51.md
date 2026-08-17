---
type: community
cohesion: 0.06
members: 40
---

# Community 51

**Cohesion:** 0.06 - loosely connected
**Members:** 40 nodes

## Members
- [[dot-test_b_ticker_locks_yes_from_max_temp_despite_evening_cooling()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_malformed_band_missing_bounds_fails_closed()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_no_signal_when_max_temp_unavailable_despite_in_band_reading()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_outside_near_edge_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_yes_signal_when_max_temp_inside()]] - code - tests/test_settlement_monitor.py
- [[dot-test_t_ticker_still_works_as_before()]] - code - tests/test_settlement_monitor.py
- [[A between market dict missing 'lower''upper' must be skipped, not silently…]] - rationale - tests/test_settlement_monitor.py
- [[AC3 regression guard at the check_city_settlement integration level an in-band…]] - rationale - tests/test_settlement_monitor.py
- [[B-ticker (between-bucket) detection in check_city_settlement.]] - rationale - tests/test_settlement_monitor.py
- [[B-ticker locked YES when the real daily high (from fetch_metar_daily_extreme,…]] - rationale - tests/test_settlement_monitor.py
- [[B-ticker market with daily high just outside band (clearance  2°F) → no signal.]] - rationale - tests/test_settlement_monitor.py
- [[Check METAR for a city and return any new settlement signals. Args city City…]] - rationale - settlement_monitor.py
- [[Check METAR for a city and return any new settlement signals. Args city City…_1]] - rationale - settlement_monitor.py
- [[Compute METAR lock-in confidence from temperature clearance and time of day.…]] - rationale - metar.py
- [[Compute the TRUE running daily extreme (max or min observed temp_f) since LOCAL…]] - rationale - metar.py
- [[Determine if a METAR reading locks in the trade outcome. Lock-in conditions…]] - rationale - metar.py
- [[Extract a plausible temp_f from a raw METAR obs dict (prefers tmpf °F, else…]] - rationale - metar.py
- [[Fetch every METAR temp_f reading for `station` that falls on the LOCAL calendar…]] - rationale - metar.py
- [[Grade Audit Module Doc metar.py]] - document - docs/grade_audit/modules/metar.md
- [[Integration-level version of the entry's own failure scenario real daily high…]] - rationale - tests/test_settlement_monitor.py
- [[METAR Lock-In Module]] - code - metar.py
- [[METAR same-day lock-in strategy. After ~2 PM local time, if the daily highlow…]] - rationale - metar.py
- [[Parse a raw METAR obs dict's obsTime (Unix epoch intfloat, or an ISO-8601…]] - rationale - metar.py
- [[Systemic DEBUG-vs-WARNING Gap on IO Failures (_load_obs_save_obs)]] - document - docs/grade_audit/outputs/metar.py.md
- [[T-ticker (abovebelow) markets are unaffected by the B-ticker changes.]] - rationale - tests/test_settlement_monitor.py
- [[TestBTickerParsing]] - code - tests/test_settlement_monitor.py
- [[_dynamic_lock_in_confidence()]] - code - metar.py
- [[_extract_obs_time()]] - code - metar.py
- [[_extract_temp_f()]] - code - metar.py
- [[_fetch_daily_temps_f()]] - code - metar.py
- [[check_city_settlement()]] - code - settlement_monitor.py
- [[check_metar_lockout()]] - code - metar.py
- [[check_metar_lockout() Silent ZoneInfo Fallback (810)]] - document - docs/grade_audit/outputs/metar.py.md
- [[date_10]] - code
- [[datetime_3]] - code
- [[fetch_metar_daily_extreme()]] - code - metar.py
- [[get_station_bias() Unconditional NotImplementedError Stub (710)]] - document - docs/grade_audit/outputs/metar.py.md
- [[metar.py]] - code - metar.py
- [[metar.py File Grade median 810 T1, systemic DEBUG gap in T2]] - document - docs/grade_audit/outputs/metar.py.md
- [[metar.py Grade Audit]] - document - docs/grade_audit/outputs/metar.py.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_51
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 4]]
- 6 edges to [[_COMMUNITY_Community 8]]
- 5 edges to [[_COMMUNITY_Community 5]]
- 3 edges to [[_COMMUNITY_Community 88]]
- 3 edges to [[_COMMUNITY_Community 53]]
- 3 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 15]]
- 1 edge to [[_COMMUNITY_Community 23]]
- 1 edge to [[_COMMUNITY_Community 38]]
- 1 edge to [[_COMMUNITY_Community 33]]

## Top bridge nodes
- [[metar.py]] - degree 25, connects to 9 communities
- [[check_city_settlement()]] - degree 14, connects to 6 communities
- [[fetch_metar_daily_extreme()]] - degree 10, connects to 5 communities
- [[check_metar_lockout()]] - degree 9, connects to 4 communities
- [[TestBTickerParsing]] - degree 10, connects to 2 communities