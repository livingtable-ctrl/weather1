---
type: community
cohesion: 0.36
members: 8
---

# Community 460

**Cohesion:** 0.36 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_fetch_hrrr_temp_negative_caches_failure()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_hrrr_temp_returns_float_or_none()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_hrrr_temp_returns_max_of_hourly()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_hrrr_temp_returns_none_for_unknown_city()]] - code - tests/test_forecasting.py
- [[A failed fetch must be negative-cached -- a second call within the TTL must not…_2]] - rationale - tests/test_forecasting.py
- [[Fetch HRRR-derived hourly temperature and return the daily max or min. Uses…]] - rationale - weather_markets.py
- [[TestHRRR]] - code - tests/test_forecasting.py
- [[_fetch_hrrr_temp()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_460
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 38]]
- 2 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 33]]

## Top bridge nodes
- [[_fetch_hrrr_temp()]] - degree 9, connects to 3 communities
- [[TestHRRR]] - degree 6, connects to 2 communities