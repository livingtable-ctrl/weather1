---
type: community
cohesion: 0.16
members: 17
---

# Community 212

**Cohesion:** 0.16 - loosely connected
**Members:** 17 nodes

## Members
- [[63 Scale edge linearly to zero as the market approaches close. At…]] - rationale - weather_markets.py
- [[dot-test_edge_decays_as_close_approaches()]] - code - tests/test_trading.py
- [[dot-test_full_edge_beyond_reference_hours()]] - code - tests/test_trading.py
- [[dot-test_full_edge_far_from_close()]] - code - tests/test_trading.py
- [[dot-test_half_edge_at_half_reference_hours()]] - code - tests/test_trading.py
- [[dot-test_half_edge_at_half_time()]] - code - tests/test_trading.py
- [[dot-test_near_close_retains_meaningful_edge()]] - code - tests/test_trading.py
- [[dot-test_zero_at_close_time()]] - code - tests/test_trading.py
- [[At 10h before close with 8h reference full edge returned.]] - rationale - tests/test_trading.py
- [[At 2h before close with 8h reference 5% edge retained (was 4% with 48h).]] - rationale - tests/test_trading.py
- [[At 4h before close with 8h reference ~50% of edge returned.]] - rationale - tests/test_trading.py
- [[At exactly half of reference_hours remaining, edge should be halved.]] - rationale - tests/test_trading.py
- [[At or past close_time, edge should be 0.]] - rationale - tests/test_trading.py
- [[Edge at 6h remaining  edge at 3h remaining (within 8h reference window).]] - rationale - tests/test_trading.py
- [[TestTimeDecayEdge]] - code - tests/test_trading.py
- [[Well before close (= reference_hours), edge should be unchanged.]] - rationale - tests/test_trading.py
- [[time_decay_edge()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_212
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 418]]
- 3 edges to [[_COMMUNITY_Community 5]]
- 2 edges to [[_COMMUNITY_Community 86]]
- 1 edge to [[_COMMUNITY_Community 38]]

## Top bridge nodes
- [[time_decay_edge()]] - degree 16, connects to 4 communities
- [[TestTimeDecayEdge]] - degree 8, connects to 1 community