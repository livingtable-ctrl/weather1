---
type: community
cohesion: 0.22
members: 9
---

# Community 423

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_no_remaining_count_means_pure_price_change_pending()]] - code - tests/test_live_execution.py
- [[dot-test_remaining_count_positive_means_still_pending()]] - code - tests/test_live_execution.py
- [[dot-test_remaining_count_zero_means_filled()]] - code - tests/test_live_execution.py
- [[dot-test_unparseable_remaining_count_fails_to_pending()]] - code - tests/test_live_execution.py
- [[Amend caused a partial fill (2 of 5) but 3 are still resting -- must stay…]] - rationale - tests/test_live_execution.py
- [[Fail toward the safer assumption (still resting, will be re-verified by the…]] - rationale - tests/test_live_execution.py
- [[TestResolveAmendStatus]] - code - tests/test_live_execution.py
- [[order_executor._resolve_amend_status -- translates an amend_order() response…]] - rationale - tests/test_live_execution.py
- [[remaining_countfill_count absent (both None) -- Kalshi's docs say these are…]] - rationale - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_423
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 1]]
- 3 edges to [[_COMMUNITY_Community 12]]

## Top bridge nodes
- [[TestResolveAmendStatus]] - degree 8, connects to 1 community
- [[dot-test_no_remaining_count_means_pure_price_change_pending()]] - degree 3, connects to 1 community
- [[dot-test_remaining_count_positive_means_still_pending()]] - degree 3, connects to 1 community
- [[dot-test_unparseable_remaining_count_fails_to_pending()]] - degree 3, connects to 1 community
- [[dot-test_remaining_count_zero_means_filled()]] - degree 2, connects to 1 community