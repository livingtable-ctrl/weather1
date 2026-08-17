---
type: community
cohesion: 0.09
members: 28
---

# Community 100

**Cohesion:** 0.09 - loosely connected
**Members:** 28 nodes

## Members
- [[dot-_epoch()]] - code - tests/test_metar.py
- [[dot-test_cache_key_includes_target_date_not_just_station()]] - code - tests/test_metar.py
- [[dot-test_computes_max_across_multiple_readings_same_local_date()]] - code - tests/test_metar.py
- [[dot-test_computes_min_across_multiple_readings_same_local_date()]] - code - tests/test_metar.py
- [[dot-test_excludes_readings_from_a_different_local_date()]] - code - tests/test_metar.py
- [[dot-test_ignores_sparse_synoptic_maxt_field_uses_raw_readings_instead()]] - code - tests/test_metar.py
- [[dot-test_invalid_extreme_argument_raises()]] - code - tests/test_metar.py
- [[dot-test_negative_caches_fetch_failure()]] - code - tests/test_metar.py
- [[dot-test_obs_time_accepts_iso_string_not_only_epoch()]] - code - tests/test_metar.py
- [[dot-test_requests_a_wide_hours_window_not_just_the_latest_reading()]] - code - tests/test_metar.py
- [[dot-test_returns_none_on_fetch_failure()]] - code - tests/test_metar.py
- [[dot-test_returns_none_when_no_readings_match_target_date()]] - code - tests/test_metar.py
- [[dot-test_second_call_within_ttl_does_not_refetch()]] - code - tests/test_metar.py
- [[dot-test_uses_celsius_temp_field_when_tmpf_absent()]] - code - tests/test_metar.py
- [[A failed fetch must be negative-cached — a second call within the TTL must not…]] - rationale - tests/test_metar.py
- [[A reading from the PRIOR local calendar day (e.g. a UTC obsTime that converts…]] - rationale - tests/test_metar.py
- [[Cache hit a second call for the same station+date within the TTL must not re-…]] - rationale - tests/test_metar.py
- [[Daily max is the max of ALL today's readings, not just the latest one or a…]] - rationale - tests/test_metar.py
- [[Fetch succeeds but every reading is from a different date (e.g. called right…]] - rationale - tests/test_metar.py
- [[Mutation-tested 2026-08-09 a station-only cache key would leak one date's…]] - rationale - tests/test_metar.py
- [[Mutation-tested 2026-08-09 without an explicit `hours` param the API returns…]] - rationale - tests/test_metar.py
- [[Regression guard for the exact bug this function exists to fix even when a…]] - rationale - tests/test_metar.py
- [[TestFetchMetarDailyExtreme]] - code - tests/test_metar.py
- [[Tests for fetch_metar_daily_extreme  _fetch_daily_temps_f — the true running-…]] - rationale - tests/test_metar.py
- [[The REAL aviationweather.gov payload has no tmpf field at all — only temp in…]] - rationale - tests/test_metar.py
- [[_extract_obs_time must also accept an ISO-8601 string obsTime (test-fixture…]] - rationale - tests/test_metar.py
- [[extreme must be exactly 'max' or 'min' — a typo like 'MAX' must raise loudly,…]] - rationale - tests/test_metar.py
- [[extreme='min' returns the lowest reading, not the highest.]] - rationale - tests/test_metar.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_100
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 53]]
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[TestFetchMetarDailyExtreme]] - degree 17, connects to 2 communities
- [[dot-test_cache_key_includes_target_date_not_just_station()]] - degree 4, connects to 1 community
- [[dot-test_computes_max_across_multiple_readings_same_local_date()]] - degree 4, connects to 1 community
- [[dot-test_computes_min_across_multiple_readings_same_local_date()]] - degree 4, connects to 1 community
- [[dot-test_excludes_readings_from_a_different_local_date()]] - degree 4, connects to 1 community