---
type: community
cohesion: 0.24
members: 11
---

# Community 350

**Cohesion:** 0.24 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-_close_time()]] - code - tests/test_weather.py
- [[dot-test_far_out_returns_high_risk()]] - code - tests/test_weather.py
- [[dot-test_missing_close_time_returns_high_risk()]] - code - tests/test_weather.py
- [[dot-test_near_close_returns_low_risk()]] - code - tests/test_weather.py
- [[dot-test_within_12_hours_returns_medium_or_low()]] - code - tests/test_weather.py
- [[Build an ISO close_time string.]] - rationale - tests/test_weather.py
- [[Empty close_time string → HIGH  1.0 (safe default).]] - rationale - tests/test_weather.py
- [[Market closing in 48 hours during daytime → HIGH  1.0.]] - rationale - tests/test_weather.py
- [[Market closing in 6 hours → MEDIUM or LOW.]] - rationale - tests/test_weather.py
- [[Market closing in 90 minutes → LOW  0.5.]] - rationale - tests/test_weather.py
- [[TestTimeRisk]] - code - tests/test_weather.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_350
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Weather Probability Math Tests]]

## Top bridge nodes
- [[TestTimeRisk]] - degree 6, connects to 1 community
- [[dot-test_far_out_returns_high_risk()]] - degree 4, connects to 1 community
- [[dot-test_near_close_returns_low_risk()]] - degree 4, connects to 1 community
- [[dot-test_within_12_hours_returns_medium_or_low()]] - degree 4, connects to 1 community
- [[dot-test_missing_close_time_returns_high_risk()]] - degree 3, connects to 1 community