---
type: community
cohesion: 0.31
members: 9
---

# Community 393

**Cohesion:** 0.31 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-_insert()]] - code - tests/test_execution_log.py
- [[dot-setup_method()_26]] - code - tests/test_execution_log.py
- [[dot-teardown_method()_18]] - code - tests/test_execution_log.py
- [[dot-test_row_1_hour_past_the_7_day_cutoff_does_not_block_reentry()]] - code - tests/test_execution_log.py
- [[dot-test_row_older_than_7_days_does_not_block_reentry()]] - code - tests/test_execution_log.py
- [[dot-test_row_within_7_days_blocks_reentry()]] - code - tests/test_execution_log.py
- [[H-21 followup was_ordered_recently() compared raw ISO-T placed_at against…]] - rationale - tests/test_execution_log.py
- [[TestWasOrderedRecentlyTimestampBoundary]] - code - tests/test_execution_log.py
- [[The exact bug scenario a row on the same calendar day as the cutoff, but…]] - rationale - tests/test_execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_393
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]

## Top bridge nodes
- [[TestWasOrderedRecentlyTimestampBoundary]] - degree 8, connects to 1 community