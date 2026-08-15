---
type: community
cohesion: 0.23
members: 14
---

# Community 252

**Cohesion:** 0.23 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_boundary_005_is_moderate()]] - code - tests/test_confidence_tiers.py
- [[dot-test_classify_confidence_returns_string()]] - code - tests/test_confidence_tiers.py
- [[dot-test_high_confidence_low_spread()]] - code - tests/test_confidence_tiers.py
- [[dot-test_live_thresholds_higher()]] - code - tests/test_confidence_tiers.py
- [[dot-test_low_confidence_wide_spread()]] - code - tests/test_confidence_tiers.py
- [[dot-test_moderate_confidence_medium_spread()]] - code - tests/test_confidence_tiers.py
- [[dot-test_zero_spread_is_high()]] - code - tests/test_confidence_tiers.py
- [[Classify ensemble spread into HIGH, MODERATE, or LOW confidence tier.]] - rationale - utils.py
- [[Return minimum edge required given ensemble spread and trading mode.]] - rationale - utils.py
- [[TestGetMinEdgeForConfidence]] - code - tests/test_confidence_tiers.py
- [[Tests for confidence-tiered edge thresholds.]] - rationale - tests/test_confidence_tiers.py
- [[classify_confidence_tier()]] - code - utils.py
- [[get_min_edge_for_confidence()]] - code - utils.py
- [[test_confidence_tiers.py]] - code - tests/test_confidence_tiers.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_252
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 215]]
- 1 edge to [[_COMMUNITY_Community 85]]

## Top bridge nodes
- [[get_min_edge_for_confidence()]] - degree 15, connects to 5 communities
- [[test_confidence_tiers.py]] - degree 5, connects to 1 community
- [[classify_confidence_tier()]] - degree 5, connects to 1 community