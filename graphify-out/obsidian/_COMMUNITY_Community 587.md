---
type: community
cohesion: 0.33
members: 6
---

# Community 587

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_fresh_weights_file_is_loaded()]] - code - tests/test_weather_markets.py
- [[dot-test_stale_weights_file_falls_back_to_defaults()]] - code - tests/test_weather_markets.py
- [[File mtime 1 day ago → loader reads and returns file contents.]] - rationale - tests/test_weather_markets.py
- [[File mtime 8 days ago → loader returns {} (default weights).]] - rationale - tests/test_weather_markets.py
- [[L4-D load_learned_weights() must discard files older than 7 days.]] - rationale - tests/test_weather_markets.py
- [[TestLearnedWeightsTTL]] - code - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_587
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 11]]

## Top bridge nodes
- [[TestLearnedWeightsTTL]] - degree 4, connects to 1 community