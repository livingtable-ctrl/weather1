---
type: community
cohesion: 0.40
members: 5
---

# Community 614

**Cohesion:** 0.40 - moderately connected
**Members:** 5 nodes

## Members
- [[dot-test_fetch_forecast_default_true_still_calls_get_weather_forecast()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_forecast_false_skips_get_weather_forecast()]] - code - tests/test_forecasting.py
- [[Regression default behavior (every other existing caller) is unchanged.]] - rationale - tests/test_forecasting.py
- [[TestEnrichWithForecastSkipsFetch]] - code - tests/test_forecasting.py
- [[fetch_forecast=False must skip get_weather_forecast() entirely (used by…]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_614
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 38]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[TestEnrichWithForecastSkipsFetch]] - degree 5, connects to 2 communities