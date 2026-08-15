---
type: community
cohesion: 0.25
members: 11
---

# Community 348

**Cohesion:** 0.25 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_analyze_trade_result_includes_city()]] - code - tests/test_weather_markets.py
- [[dot-test_different_city_is_not_a_hedge()]] - code - tests/test_weather_markets.py
- [[dot-test_missing_city_returns_false()]] - code - tests/test_weather_markets.py
- [[dot-test_same_city_different_date_is_not_a_hedge()]] - code - tests/test_weather_markets.py
- [[dot-test_same_city_same_date_opposite_side_is_a_hedge()]] - code - tests/test_weather_markets.py
- [[A NO on tomorrow's market must NOT be flagged as a hedge of a YES on today's…]] - rationale - tests/test_weather_markets.py
- [[Return True if the new trade would partially hedge an existing open position…]] - rationale - weather_markets.py
- [[TestDetectHedgeOpportunity]] - code - tests/test_weather_markets.py
- [[analyze_trade must surface 'city' in its result (previously missing entirely)…]] - rationale - tests/test_weather_markets.py
- [[analyze_trade's returned dict must include a 'city' key so…]] - rationale - tests/test_weather_markets.py
- [[detect_hedge_opportunity()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_348
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]

## Top bridge nodes
- [[detect_hedge_opportunity()]] - degree 8, connects to 2 communities
- [[TestDetectHedgeOpportunity]] - degree 7, connects to 1 community