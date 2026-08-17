---
type: community
cohesion: 0.16
members: 17
---

# Community 203

**Cohesion:** 0.16 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-_cond()]] - code - tests/test_weather.py
- [[dot-test_above_near_threshold_not_near_zero()]] - code - tests/test_weather.py
- [[dot-test_below_near_threshold_not_near_one()]] - code - tests/test_weather.py
- [[dot-test_centered_temp_gives_low_probability()]] - code - tests/test_weather.py
- [[dot-test_centered_temp_not_near_one()]] - code - tests/test_weather.py
- [[dot-test_temp_outside_bucket_gives_low_probability()]] - code - tests/test_weather.py
- [[Convert a live observation to a probability. Uses sigma=3.5 — a midday…]] - rationale - nws.py
- [[Old sigma=0.25 gave ~0.95; new sigma=3.5 must give much less.]] - rationale - tests/test_weather.py
- [[Regression obs_prob for 'above''below' must use sigma=3.5, not sigma=1.0.…]] - rationale - tests/test_weather.py
- [[Regression obs_prob for 'between' must use sigma=3.5, not sigma=0.25. The old…]] - rationale - tests/test_weather.py
- [[Temp 2°F above 'below' threshold → must be meaningfully below 1.]] - rationale - tests/test_weather.py
- [[Temp 2°F below 'above' threshold → must be meaningfully above 0.]] - rationale - tests/test_weather.py
- [[Temp 5°F above the bucket → probability should be tiny.]] - rationale - tests/test_weather.py
- [[Temp at centre of a 1°F band → ~11%, not ~95%.]] - rationale - tests/test_weather.py
- [[TestObsProbAboveBelowSigma]] - code - tests/test_weather.py
- [[TestObsProbBetweenSigma]] - code - tests/test_weather.py
- [[obs_prob()]] - code - nws.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_203
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 396]]
- 2 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 38]]

## Top bridge nodes
- [[obs_prob()]] - degree 12, connects to 4 communities
- [[TestObsProbBetweenSigma]] - degree 6, connects to 1 community
- [[TestObsProbAboveBelowSigma]] - degree 4, connects to 1 community