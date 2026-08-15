---
type: community
cohesion: 0.17
members: 12
---

# Community 303

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-_restore_module_caches()]] - code - tests/test_forecasting.py
- [[dot-test_cache_hit_returns_ensemble_without_fetch()]] - code - tests/test_forecasting.py
- [[dot-test_cache_hit_returns_forecast_without_fetch()]] - code - tests/test_forecasting.py
- [[dot-test_ttl_until_next_cycle_before_02z()]] - code - tests/test_forecasting.py
- [[dot-test_ttl_until_next_cycle_minimum()]] - code - tests/test_forecasting.py
- [[At 0100 UTC, next cycle is 0200 UTC â†’ ~3600s.]] - rationale - tests/test_forecasting.py
- [[TTL is at least 1800 seconds.]] - rationale - tests/test_forecasting.py
- [[TestDynamicCacheTTL]] - code - tests/test_forecasting.py
- [[fixture_6]] - code
- [[get_ensemble_temps returns cached data without making API calls.]] - rationale - tests/test_forecasting.py
- [[get_weather_forecast returns cached data without making API calls.]] - rationale - tests/test_forecasting.py
- [[test_cache_hit_returns_forecast_without_fetch and…]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_303
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[TestDynamicCacheTTL]] - degree 7, connects to 2 communities
- [[dot-test_ttl_until_next_cycle_before_02z()]] - degree 3, connects to 1 community
- [[dot-test_ttl_until_next_cycle_minimum()]] - degree 3, connects to 1 community