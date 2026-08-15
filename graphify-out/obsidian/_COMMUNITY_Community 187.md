---
type: community
cohesion: 0.11
members: 18
---

# Community 187

**Cohesion:** 0.11 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-setup_method()_14]] - code - tests/test_mos.py
- [[dot-test_days_out_uses_city_local_today_not_utc()]] - code - tests/test_mos.py
- [[dot-test_fetch_mos_best_routing_uses_city_local_today_not_utc()]] - code - tests/test_mos.py
- [[dot-test_max_temp_is_highest_in_day()]] - code - tests/test_mos.py
- [[dot-test_negative_caches_failure()]] - code - tests/test_mos.py
- [[dot-test_returns_dict_on_success()]] - code - tests/test_mos.py
- [[dot-test_returns_none_on_empty_data()]] - code - tests/test_mos.py
- [[dot-test_returns_none_on_request_exception()]] - code - tests/test_mos.py
- [[dot-test_station_lookup()]] - code - tests/test_mos.py
- [[dot-test_unknown_city_returns_none()_1]] - code - tests/test_mos.py
- [[A failed fetch must be negative-cached -- a second call within the TTL must not…]] - rationale - tests/test_mos.py
- [[Clear the MOS in-process cache before each test.]] - rationale - tests/test_mos.py
- [[TestFetchMos]] - code - tests/test_mos.py
- [[fetch_mos returns a dict with max_temp_f on success.]] - rationale - tests/test_mos.py
- [[fetch_mos's days_out (and thus sigma) must be computed against the tz passed…]] - rationale - tests/test_mos.py
- [[fetch_mos_best's NAM-vs-GFS routing must also key off the passed tz, not UTC --…]] - rationale - tests/test_mos.py
- [[get_mos_station returns correct ASOS station for each city. Keys are full city…]] - rationale - tests/test_mos.py
- [[max_temp_f is the highest tmp reading across all hours for the target date.]] - rationale - tests/test_mos.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_187
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 457]]

## Top bridge nodes
- [[TestFetchMos]] - degree 11, connects to 1 community