---
type: community
cohesion: 0.33
members: 6
---

# Community 528

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_no_entry_side_edge_uses_no_ask()]] - code - tests/test_weather_markets.py
- [[dot-test_yes_entry_side_edge_uses_yes_ask()]] - code - tests/test_weather_markets.py
- [[L7-C entry_side_edge must use ask price, not mid, for each side.]] - rationale - tests/test_weather_markets.py
- [[NO trades entry_side_edge = P(NO wins) - no_ask = (1-blended_prob) -…]] - rationale - tests/test_weather_markets.py
- [[TestEntryEdgeVsMidEdge]] - code - tests/test_weather_markets.py
- [[YES trades entry_side_edge = blended_prob - yes_ask (smaller than mid-edge).]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_528
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]

## Top bridge nodes
- [[TestEntryEdgeVsMidEdge]] - degree 4, connects to 1 community
- [[dot-test_no_entry_side_edge_uses_no_ask()]] - degree 3, connects to 1 community
- [[dot-test_yes_entry_side_edge_uses_yes_ask()]] - degree 3, connects to 1 community