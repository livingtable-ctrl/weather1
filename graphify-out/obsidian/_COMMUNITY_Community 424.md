---
type: community
cohesion: 0.25
members: 8
---

# Community 424

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_cycle_boundaries()]] - code - tests/test_forecasting.py
- [[dot-test_cycle_labels_cover_all_hours()]] - code - tests/test_forecasting.py
- [[dot-test_log_prediction_called_with_forecast_cycle()]] - code - tests/test_forecasting.py
- [[Boundary hours map to the correct cycle, including the date prefix.]] - rationale - tests/test_forecasting.py
- [[Every UTC hour maps to a valid, date-prefixed cycle label.]] - rationale - tests/test_forecasting.py
- [[Retargeted 2026-07-18 (backlog.txt TWO FUNCTIONS NAMED…]] - rationale - tests/test_forecasting.py
- [[TestForecastCycle]] - code - tests/test_forecasting.py
- [[main.py's log_prediction calls must carry forecast_cycle metadata, either as a…]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_424
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[TestForecastCycle]] - degree 6, connects to 2 communities
- [[dot-test_cycle_boundaries()]] - degree 3, connects to 1 community
- [[dot-test_cycle_labels_cover_all_hours()]] - degree 3, connects to 1 community