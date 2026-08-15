---
type: community
cohesion: 0.20
members: 10
---

# Community 363

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-setup_method()_4]] - code - tests/test_execution_log.py
- [[dot-teardown_method()_4]] - code - tests/test_execution_log.py
- [[dot-test_forecast_cycle_and_live_columns_exist()]] - code - tests/test_execution_log.py
- [[dot-test_log_order_stores_cycle_and_live_flag()]] - code - tests/test_execution_log.py
- [[dot-test_was_ordered_this_cycle_false_different_cycle()]] - code - tests/test_execution_log.py
- [[dot-test_was_ordered_this_cycle_true()]] - code - tests/test_execution_log.py
- [[dot-test_was_ordered_this_cycle_true_for_cancelled()]] - code - tests/test_execution_log.py
- [[Cancelled orders still block the cycle (same as was_recently_ordered behaviour).]] - rationale - tests/test_execution_log.py
- [[Point execution_log at a fresh temp DB for each test.]] - rationale - tests/test_execution_log.py
- [[TestExecutionLogMigration]] - code - tests/test_execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_363
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]

## Top bridge nodes
- [[TestExecutionLogMigration]] - degree 8, connects to 1 community