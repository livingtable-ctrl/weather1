---
type: community
cohesion: 0.13
members: 15
---

# Community 240

**Cohesion:** 0.13 - loosely connected
**Members:** 15 nodes

## Members
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

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_240
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 92]]

## Top bridge nodes
- [[TestTimeDecayEdge]] - degree 8, connects to 1 community
- [[dot-test_edge_decays_as_close_approaches()]] - degree 3, connects to 1 community
- [[dot-test_full_edge_beyond_reference_hours()]] - degree 3, connects to 1 community
- [[dot-test_full_edge_far_from_close()]] - degree 3, connects to 1 community
- [[dot-test_half_edge_at_half_reference_hours()]] - degree 3, connects to 1 community