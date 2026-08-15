---
type: community
cohesion: 0.10
members: 20
---

# Community 161

**Cohesion:** 0.10 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-test_circuit_open_serves_cached_value_instead_of_none()]] - code - tests/test_acis_precip.py
- [[dot-test_correct_mm_unit_returns_value()]] - code - tests/test_acis_precip.py
- [[dot-test_different_params_are_not_cache_collisions()]] - code - tests/test_acis_precip.py
- [[dot-test_fetch_exception_returns_none()]] - code - tests/test_acis_precip.py
- [[dot-test_month_outside_window_result_is_also_cached()]] - code - tests/test_acis_precip.py
- [[dot-test_month_outside_window_returns_none()]] - code - tests/test_acis_precip.py
- [[dot-test_none_result_IS_cached_second_call_skips_http()]] - code - tests/test_acis_precip.py
- [[dot-test_one_response_fills_cache_for_every_month_present()]] - code - tests/test_acis_precip.py
- [[dot-test_parses_matching_month()]] - code - tests/test_acis_precip.py
- [[dot-test_successful_result_is_cached_second_call_skips_http()]] - code - tests/test_acis_precip.py
- [[dot-test_unexpected_unit_refuses_value()]] - code - tests/test_acis_precip.py
- [[A different (lat, lon, tz, year, month) must be a real cache miss, not…]] - rationale - tests/test_acis_precip.py
- [[Control for the guard above an explicit, correct 'mm' unit must not be refused.]] - rationale - tests/test_acis_precip.py
- [[One response covers ~6 months of data -- every (year, month) actually present…]] - rationale - tests/test_acis_precip.py
- [[Opus-review-caught gap (Snow Step 2 round-2 review) the mm claim was, like…]] - rationale - tests/test_acis_precip.py
- [[TestFetchSeasonalPrecipMeanMm]] - code - tests/test_acis_precip.py
- [[The target-month-absent-from-response None path (a successful HTTP call whose…]] - rationale - tests/test_acis_precip.py
- [[Unlike a plain .get()-based cache, None results ARE cached here too (via…]] - rationale - tests/test_acis_precip.py
- [[While the circuit breaker is open, a cache hit must still win -- matches…]] - rationale - tests/test_acis_precip.py
- [[backlog.txt 'OPEN-METEO SEASONAL API...' research finding this function had…]] - rationale - tests/test_acis_precip.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_161
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 271]]

## Top bridge nodes
- [[TestFetchSeasonalPrecipMeanMm]] - degree 12, connects to 1 community