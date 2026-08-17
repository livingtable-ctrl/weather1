---
type: community
cohesion: 0.15
members: 19
---

# Community 174

**Cohesion:** 0.15 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-test_condition_compounds_horizon()]] - code - tests/test_signal_quality.py
- [[dot-test_day_0_returns_one()]] - code - tests/test_weather_markets.py
- [[dot-test_day_14_returns_0_60()]] - code - tests/test_weather_markets.py
- [[dot-test_day_2_returns_one()]] - code - tests/test_weather_markets.py
- [[dot-test_day_7_in_linear_segment()]] - code - tests/test_weather_markets.py
- [[dot-test_floor_at_day_20()]] - code - tests/test_weather_markets.py
- [[dot-test_monotonically_decreasing()]] - code - tests/test_weather_markets.py
- [[dot-test_precip_snow_lower_than_temp()]] - code - tests/test_signal_quality.py
- [[dot-test_unknown_condition_defaults_to_one()]] - code - tests/test_signal_quality.py
- [[Horizon + condition discount factor for edge signal (6314). Combines the…]] - rationale - weather_markets.py
- [[Same horizon, snow produces lower confidence than temperature.]] - rationale - tests/test_signal_quality.py
- [[TestAdjustedEdgeInAnalyzeTrade (63)]] - code - tests/test_weather_markets.py
- [[TestEdgeConfidence]] - code - tests/test_weather_markets.py
- [[TestEdgeConfidenceConditionType]] - code - tests/test_signal_quality.py
- [[Tests for edge_confidence(days_out) horizon discount factor.]] - rationale - tests/test_weather_markets.py
- [[Unknown condition_type uses multiplier 1.0 — no change from no condition.]] - rationale - tests/test_signal_quality.py
- [[days_out=10, precip_snow horizon≈0.7143, × 0.80 ≈ 0.5714.]] - rationale - tests/test_signal_quality.py
- [[days_out=7 is at the boundary of segment 2; should be 0.80.]] - rationale - tests/test_weather_markets.py
- [[edge_confidence()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_174
SORT file.name ASC
```

## Connections to other communities
- 11 edges to [[_COMMUNITY_Community 5]]
- 2 edges to [[_COMMUNITY_Community 238]]
- 2 edges to [[_COMMUNITY_Community 11]]

## Top bridge nodes
- [[edge_confidence()]] - degree 24, connects to 3 communities
- [[TestEdgeConfidence]] - degree 9, connects to 1 community
- [[TestEdgeConfidenceConditionType]] - degree 4, connects to 1 community
- [[TestAdjustedEdgeInAnalyzeTrade (63)]] - degree 2, connects to 1 community