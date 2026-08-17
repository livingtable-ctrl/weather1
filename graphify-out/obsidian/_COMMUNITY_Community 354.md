---
type: community
cohesion: 0.25
members: 11
---

# Community 354

**Cohesion:** 0.25 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-_call()_1]] - code - tests/test_weather_markets.py
- [[dot-test_low_market_above_already_below_margin_is_locked()]] - code - tests/test_weather_markets.py
- [[dot-test_low_market_above_still_above_margin_is_not_locked()]] - code - tests/test_weather_markets.py
- [[dot-test_low_market_below_already_below_margin_is_locked()]] - code - tests/test_weather_markets.py
- [[dot-test_low_market_below_still_above_margin_is_not_locked()]] - code - tests/test_weather_markets.py
- [[A LOW market's running daily-min-so-far can only DECREASE as the day progresses…]] - rationale - tests/test_weather_markets.py
- [[TestMetarLockInLowMarketAsymmetry]] - code - tests/test_weather_markets.py
- [[low above 40', running min=30 (= 40-3 margin) monotone-safe — the min can…]] - rationale - tests/test_weather_markets.py
- [[low above 40', running min=45 (= 40+3 margin) NOT monotone-safe — the min…]] - rationale - tests/test_weather_markets.py
- [[low below 60', running min=50 (= 60-3 margin) monotone-safe — the min already…]] - rationale - tests/test_weather_markets.py
- [[low below 60', running min=65 (= 60+3 margin) NOT monotone-safe for the NO…]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_354
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 11]]
- 1 edge to [[_COMMUNITY_Community 53]]

## Top bridge nodes
- [[TestMetarLockInLowMarketAsymmetry]] - degree 7, connects to 1 community
- [[dot-_call()_1]] - degree 6, connects to 1 community