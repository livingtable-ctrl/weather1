---
type: community
cohesion: 0.25
members: 8
---

# Community 443

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_low_spread_tier_at_boundary_still_clears_gate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_low_spread_tier_untiers_when_net_edge_below_confidence_threshold()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_missing_ensemble_spread_falls_back_to_flat_paper_min_edge()]] - code - tests/test_trade_cycle_engine.py
- [[LOW-confidence tier (spread=0.15) requires paper edge = 0.10. net_edge=0.08…]] - rationale - tests/test_trade_cycle_engine.py
- [[No ensemble_spread key -- matches validate()'s own fallback to…]] - rationale - tests/test_trade_cycle_engine.py
- [[Sibling of the Kelly floor gate above, same backlog.txt entry -- validate()'s…]] - rationale - tests/test_trade_cycle_engine.py
- [[TestPlacementConfidenceTierGateTierClassification]] - code - tests/test_trade_cycle_engine.py
- [[validate() rejects strictly-below min_edge, so net_edge exactly at the LOW-tier…]] - rationale - tests/test_trade_cycle_engine.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_443
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 3 edges to [[_COMMUNITY_Community 42]]

## Top bridge nodes
- [[TestPlacementConfidenceTierGateTierClassification]] - degree 7, connects to 1 community
- [[dot-test_low_spread_tier_at_boundary_still_clears_gate()]] - degree 3, connects to 1 community
- [[dot-test_low_spread_tier_untiers_when_net_edge_below_confidence_threshold()]] - degree 3, connects to 1 community
- [[dot-test_missing_ensemble_spread_falls_back_to_flat_paper_min_edge()]] - degree 3, connects to 1 community