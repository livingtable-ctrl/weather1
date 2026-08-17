---
type: community
cohesion: 0.25
members: 11
---

# Community 356

**Cohesion:** 0.25 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_above_condition()]] - code - tests/test_weather.py
- [[dot-test_above_uses_prob_threshold_not_raw_threshold()]] - code - tests/test_weather.py
- [[dot-test_below_condition()]] - code - tests/test_weather.py
- [[dot-test_below_uses_prob_threshold_not_raw_threshold()]] - code - tests/test_weather.py
- [[dot-test_between_condition()]] - code - tests/test_weather.py
- [[A very wide range around the forecast should have high probability.]] - rationale - tests/test_weather.py
- [[Estimate probability of the market condition given a forecast temperature.]] - rationale - weather_markets.py
- [[If forecast equals threshold exactly, P(above) ~ 0.5.]] - rationale - tests/test_weather.py
- [[If forecast is much higher than threshold, P(below) ~ 0.]] - rationale - tests/test_weather.py
- [[TestForecastProbability]] - code - tests/test_weather.py
- [[_forecast_probability()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_356
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 5]]
- 2 edges to [[_COMMUNITY_Community 396]]
- 1 edge to [[_COMMUNITY_Community 38]]
- 1 edge to [[_COMMUNITY_Community 6]]
- 1 edge to [[_COMMUNITY_Community 409]]

## Top bridge nodes
- [[_forecast_probability()]] - degree 13, connects to 5 communities
- [[TestForecastProbability]] - degree 6, connects to 1 community