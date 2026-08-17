---
type: community
cohesion: 0.31
members: 9
---

# Community 405

**Cohesion:** 0.31 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_partial_data_high_only()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_high_low_dict()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_when_date_missing()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_when_nws_unavailable()]] - code - tests/test_weather_markets.py
- [[Return NBM highlow for a specific date via the NWS gridpoints API. NBM…]] - rationale - nws.py
- [[TestFetchNbmForecast]] - code - tests/test_weather_markets.py
- [[date_8]] - code
- [[fetch_nbm_forecast()]] - code - nws.py
- [[fetch_nbm_forecast() wraps get_nws_daily_forecast() into a flat dict.]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_405
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 11]]
- 2 edges to [[_COMMUNITY_Community 5]]

## Top bridge nodes
- [[fetch_nbm_forecast()]] - degree 11, connects to 3 communities
- [[TestFetchNbmForecast]] - degree 6, connects to 1 community
- [[date_8]] - degree 2, connects to 1 community