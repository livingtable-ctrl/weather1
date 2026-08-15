---
type: community
cohesion: 0.25
members: 8
---

# Community 421

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-setup_method()_28]] - code - tests/test_execution_log.py
- [[dot-teardown_method()_20]] - code - tests/test_execution_log.py
- [[dot-test_api_canceled_order_does_not_block_reentry()]] - code - tests/test_execution_log.py
- [[dot-test_filled_order_still_blocks_reentry()]] - code - tests/test_execution_log.py
- [[dot-test_legacy_british_cancelled_spelling_does_not_block_reentry()]] - code - tests/test_execution_log.py
- [[Deep-review followup rows written before the F8 spelling fix deployed (with…]] - rationale - tests/test_execution_log.py
- [[F8 was_ordered_recently() must exclude API-canceled orders.…]] - rationale - tests/test_execution_log.py
- [[TestWasOrderedRecentlyCanceledSpelling]] - code - tests/test_execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_421
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]

## Top bridge nodes
- [[TestWasOrderedRecentlyCanceledSpelling]] - degree 7, connects to 1 community