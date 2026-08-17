---
type: community
cohesion: 0.12
members: 25
---

# Community 120

**Cohesion:** 0.12 - loosely connected
**Members:** 25 nodes

## Members
- [[Confirmed live 2026-07-20 a transient fetchparse hiccup can return markets…]] - rationale - tests/test_hourly_target_hours.py
- [[If max_hour and min_hour ever coincide (degenerate data), behavior must be…]] - rationale - tests/test_hourly_target_hours.py
- [[One city already refreshed today, the rest weren't — only the stale ones should…]] - rationale - tests/test_hourly_target_hours.py
- [[One finalized ladder whose close_time, converted to `city_tz`, lands on…]] - rationale - tests/test_hourly_target_hours.py
- [[Tests for refresh_hourly_target_hours()get_hourly_target_hour_role() — once-…]] - rationale - tests/test_hourly_target_hours.py
- [[Ticker hour-parse failure must gate out safely, not crash.]] - rationale - tests/test_hourly_target_hours.py
- [[_finalized_market()]] - code - tests/test_hourly_target_hours.py
- [[_ladder_at_local_hour()]] - code - tests/test_hourly_target_hours.py
- [[_mock_client()]] - code - tests/test_hourly_target_hours.py
- [[_today()]] - code - tests/test_hourly_target_hours.py
- [[test_first_run_creates_cache_for_all_cities()]] - code - tests/test_hourly_target_hours.py
- [[test_gated_to_run_once_per_city_per_day()]] - code - tests/test_hourly_target_hours.py
- [[test_hourly_target_hours.py]] - code - tests/test_hourly_target_hours.py
- [[test_never_raises_when_fetch_throws()]] - code - tests/test_hourly_target_hours.py
- [[test_no_usable_data_not_cached_as_done_for_today()]] - code - tests/test_hourly_target_hours.py
- [[test_one_city_fetch_failure_does_not_block_others()]] - code - tests/test_hourly_target_hours.py
- [[test_role_degenerate_max_equals_min_prefers_max()]] - code - tests/test_hourly_target_hours.py
- [[test_role_returns_max_for_cached_max_hour()]] - code - tests/test_hourly_target_hours.py
- [[test_role_returns_min_for_cached_min_hour()]] - code - tests/test_hourly_target_hours.py
- [[test_role_returns_none_for_non_target_hour()]] - code - tests/test_hourly_target_hours.py
- [[test_role_returns_none_when_cache_missing()]] - code - tests/test_hourly_target_hours.py
- [[test_role_returns_none_when_city_not_cached()]] - code - tests/test_hourly_target_hours.py
- [[test_role_returns_none_when_hour_is_none()]] - code - tests/test_hourly_target_hours.py
- [[test_series_drift.py (referenced, not in this chunk)]] - code - tests/test_series_drift.py
- [[test_stale_city_refreshed_others_untouched()]] - code - tests/test_hourly_target_hours.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_120
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 53]]
- 1 edge to [[_COMMUNITY_Community 235]]

## Top bridge nodes
- [[test_hourly_target_hours.py]] - degree 24, connects to 2 communities
- [[_ladder_at_local_hour()]] - degree 7, connects to 1 community