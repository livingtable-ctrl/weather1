---
type: community
cohesion: 0.18
members: 16
---

# Community 215

**Cohesion:** 0.18 - loosely connected
**Members:** 16 nodes

## Members
- [[dot-test_defaults_to_min_edge_constant()]] - code - tests/test_live_execution.py
- [[dot-test_falls_back_to_min_edge_on_tier_exception()]] - code - tests/test_live_execution.py
- [[dot-test_false_for_thin_edge()]] - code - tests/test_live_execution.py
- [[dot-test_invalid_side_returns_false()]] - code - tests/test_live_execution.py
- [[dot-test_missing_entry_price_returns_false()]] - code - tests/test_live_execution.py
- [[dot-test_missing_forecast_prob_returns_false()]] - code - tests/test_live_execution.py
- [[dot-test_no_side_computed_correctly()]] - code - tests/test_live_execution.py
- [[dot-test_true_for_strong_edge()]] - code - tests/test_live_execution.py
- [[dot-test_uses_confidence_tier_when_spread_present()]] - code - tests/test_live_execution.py
- [[Replicate _validate_trade_opportunity's live min-edge threshold (confidence-…]] - rationale - order_executor.py
- [[TestClearsTakerFee]] - code - tests/test_live_execution.py
- [[TestLiveMinEdge]] - code - tests/test_live_execution.py
- [[True if net_edge, recomputed with the REAL taker fee instead of the maker fee…]] - rationale - order_executor.py
- [[_clears_taker_fee recomputes net_edge with the real taker fee instead of the…]] - rationale - tests/test_live_execution.py
- [[_clears_taker_fee()]] - code - order_executor.py
- [[_live_min_edge()]] - code - order_executor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_215
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 111]]
- 4 edges to [[_COMMUNITY_Community 45]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 252]]
- 1 edge to [[_COMMUNITY_Community 67]]

## Top bridge nodes
- [[_clears_taker_fee()]] - degree 11, connects to 3 communities
- [[_live_min_edge()]] - degree 8, connects to 3 communities
- [[TestClearsTakerFee]] - degree 10, connects to 2 communities
- [[TestLiveMinEdge]] - degree 6, connects to 2 communities