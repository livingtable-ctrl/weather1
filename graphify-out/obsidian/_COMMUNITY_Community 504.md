---
type: community
cohesion: 0.33
members: 6
---

# Community 504

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_enrich_uses_cache_timestamp_not_current_time()]] - code - tests/test_forecasting.py
- [[dot-test_enrich_uses_current_time_on_cache_miss()]] - code - tests/test_forecasting.py
- [[On a cache miss, data_fetched_at must be the current wall-clock time.]] - rationale - tests/test_forecasting.py
- [[P1-1 data_fetched_at must reflect the cache entry's original fetch time, not…]] - rationale - tests/test_forecasting.py
- [[TestEnrichWithForecastCacheTimestamp]] - code - tests/test_forecasting.py
- [[When the forecast is already cached, data_fetched_at must equal the original…]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_504
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[TestEnrichWithForecastCacheTimestamp]] - degree 5, connects to 2 communities