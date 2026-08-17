---
type: community
cohesion: 0.22
members: 9
---

# Community 402

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_city_weights_override_hardcoded()]] - code - tests/test_weather_markets.py
- [[dot-test_fallback_to_hardcoded_when_no_calibration()]] - code - tests/test_weather_markets.py
- [[dot-test_seasonal_weights_used_when_no_city_weights()]] - code - tests/test_weather_markets.py
- [[If city weights loaded, _blend_weights uses them (days_out=1 = neutral NWS…]] - rationale - tests/test_weather_markets.py
- [[If no city weights but seasonal weights loaded, use seasonal (days_out=1 =…]] - rationale - tests/test_weather_markets.py
- [[TestBlendWeightCalibrationPriority]] - code - tests/test_weather_markets.py
- [[With empty dicts, result should match original hardcoded schedule.]] - rationale - tests/test_weather_markets.py
- [[_blend_weights() must use city weights  seasonal weights  hardcoded.]] - rationale - tests/test_weather_markets.py
- [[condition_weights.json (abovebelowbetween blend weights)]] - document - data/condition_weights.json

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_402
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 11]]
- 1 edge to [[_COMMUNITY_Community 94]]

## Top bridge nodes
- [[TestBlendWeightCalibrationPriority]] - degree 7, connects to 2 communities