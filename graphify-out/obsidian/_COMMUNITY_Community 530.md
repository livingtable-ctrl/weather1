---
type: community
cohesion: 0.33
members: 6
---

# Community 530

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_forecast_uncertainty_is_a_pure_function_of_days_out()]] - code - tests/test_weather_markets.py
- [[dot-test_no_date_today_calls_remain()]] - code - tests/test_weather_markets.py
- [[L5-E weather_markets must use datetime.now(UTC).date() not date.today() for…]] - rationale - tests/test_weather_markets.py
- [[TestUtcTodayDate]] - code - tests/test_weather_markets.py
- [[_forecast_uncertainty(days_out) no longer recomputes today itself (from UTC…]] - rationale - tests/test_weather_markets.py
- [[weather_markets.py must not contain any date.today() calls.]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_530
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]

## Top bridge nodes
- [[TestUtcTodayDate]] - degree 4, connects to 1 community