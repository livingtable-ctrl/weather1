---
type: community
cohesion: 0.24
members: 11
---

# Community 329

**Cohesion:** 0.24 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_no_remaining_count_means_pure_price_change_pending()]] - code - tests/test_live_execution.py
- [[dot-test_remaining_count_positive_means_still_pending()]] - code - tests/test_live_execution.py
- [[dot-test_remaining_count_zero_means_filled()]] - code - tests/test_live_execution.py
- [[dot-test_unparseable_remaining_count_fails_to_pending()]] - code - tests/test_live_execution.py
- [[Amend caused a partial fill (2 of 5) but 3 are still resting -- must stay…]] - rationale - tests/test_live_execution.py
- [[Fail toward the safer assumption (still resting, will be re-verified by the…]] - rationale - tests/test_live_execution.py
- [[TestResolveAmendStatus]] - code - tests/test_live_execution.py
- [[Translate an amend_order() response into this bot's internal status vocabulary…]] - rationale - order_executor.py
- [[_resolve_amend_status()]] - code - order_executor.py
- [[order_executor._resolve_amend_status -- translates an amend_order() response…]] - rationale - tests/test_live_execution.py
- [[remaining_countfill_count absent (both None) -- Kalshi's docs say these are…]] - rationale - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_329
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 111]]
- 2 edges to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 67]]

## Top bridge nodes
- [[_resolve_amend_status()]] - degree 9, connects to 4 communities
- [[TestResolveAmendStatus]] - degree 8, connects to 2 communities