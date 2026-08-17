---
type: community
cohesion: 0.22
members: 9
---

# Community 444

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_all_above_threshold_gives_high_prob()]] - code - tests/test_weather.py
- [[dot-test_half_above_gives_straddling_ci()]] - code - tests/test_weather.py
- [[dot-test_none_above_threshold_gives_low_prob()]] - code - tests/test_weather.py
- [[dot-test_small_sample_returns_full_range()]] - code - tests/test_weather.py
- [[All members above 0.01in → precip_any CI should be near (1, 1).]] - rationale - tests/test_weather.py
- [[Fewer than 5 members → returns (0.0, 1.0) as uninformative CI.]] - rationale - tests/test_weather.py
- [[Half members above 0.10in → CI should straddle 0.5.]] - rationale - tests/test_weather.py
- [[No members above threshold → CI near (0, 0).]] - rationale - tests/test_weather.py
- [[TestBootstrapCIPrecip]] - code - tests/test_weather.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_444
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 396]]

## Top bridge nodes
- [[TestBootstrapCIPrecip]] - degree 5, connects to 1 community
- [[dot-test_all_above_threshold_gives_high_prob()]] - degree 3, connects to 1 community
- [[dot-test_half_above_gives_straddling_ci()]] - degree 3, connects to 1 community
- [[dot-test_none_above_threshold_gives_low_prob()]] - degree 3, connects to 1 community
- [[dot-test_small_sample_returns_full_range()]] - degree 3, connects to 1 community