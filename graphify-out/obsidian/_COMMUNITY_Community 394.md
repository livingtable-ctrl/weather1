---
type: community
cohesion: 0.22
members: 9
---

# Community 394

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_analyze_trade_applies_time_decay()]] - code - tests/test_forecasting.py
- [[dot-test_full_edge_at_reference_hours()]] - code - tests/test_forecasting.py
- [[dot-test_half_edge_at_half_reference()]] - code - tests/test_forecasting.py
- [[dot-test_zero_edge_at_close()]] - code - tests/test_forecasting.py
- [[24h before close with 48h reference â†’ edge  0.5.]] - rationale - tests/test_forecasting.py
- [[At = reference_hours before close, return full raw_edge.]] - rationale - tests/test_forecasting.py
- [[Atpast close_time, return 0.0.]] - rationale - tests/test_forecasting.py
- [[TestTimeDecayEdge_1]] - code - tests/test_forecasting.py
- [[analyze_trade edge is time-decay scaled (not raw blended - market).]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_394
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 64]]

## Top bridge nodes
- [[TestTimeDecayEdge_1]] - degree 6, connects to 2 communities
- [[dot-test_analyze_trade_applies_time_decay()]] - degree 3, connects to 1 community
- [[dot-test_full_edge_at_reference_hours()]] - degree 3, connects to 1 community
- [[dot-test_half_edge_at_half_reference()]] - degree 3, connects to 1 community
- [[dot-test_zero_edge_at_close()]] - degree 3, connects to 1 community