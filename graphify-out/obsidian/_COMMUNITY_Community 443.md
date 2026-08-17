---
type: community
cohesion: 0.22
members: 9
---

# Community 443

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_days_out_above_two_returns_none()]] - code - tests/test_weather_markets.py
- [[dot-test_exception_in_lookup_returns_none_not_raises()]] - code - tests/test_weather_markets.py
- [[dot-test_no_live_observation_returns_none()]] - code - tests/test_weather_markets.py
- [[dot-test_uses_daily_max_for_max_var_at_days_out_zero()]] - code - tests/test_weather_markets.py
- [[dot-test_uses_instantaneous_temp_for_min_var()]] - code - tests/test_weather_markets.py
- [[Dedicated unit tests for _compute_persistence_prob(), the second function…]] - rationale - tests/test_weather_markets.py
- [[TestComputePersistenceProbRefactorSafetyNet]] - code - tests/test_weather_markets.py
- [[var='max' at days_out=0 must prefer the observed running daily max over the…]] - rationale - tests/test_weather_markets.py
- [[var='min' must use the instantaneous current temp, not max_temp_f (the daily-…]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_443
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 11]]

## Top bridge nodes
- [[TestComputePersistenceProbRefactorSafetyNet]] - degree 7, connects to 1 community