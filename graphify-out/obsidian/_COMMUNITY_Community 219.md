---
type: community
cohesion: 0.17
members: 16
---

# Community 219

**Cohesion:** 0.17 - loosely connected
**Members:** 16 nodes

## Members
- [[dot-_run_place()]] - code - tests/test_prelog.py
- [[dot-test_exactly_one_log_row_on_failure()]] - code - tests/test_prelog.py
- [[dot-test_exactly_one_log_row_on_success()]] - code - tests/test_prelog.py
- [[dot-test_pending_row_exists_before_api_call()]] - code - tests/test_prelog.py
- [[dot-test_placed_order_counts_toward_open_positions()]] - code - tests/test_prelog.py
- [[dot-test_status_updated_to_failed_on_exception()]] - code - tests/test_prelog.py
- [[dot-test_status_updated_to_pending_on_success()]] - code - tests/test_prelog.py
- [[A 'pending' log row must exist in the DB before place_order is called.]] - rationale - tests/test_prelog.py
- [[After a successful place_order, status must be updated to 'pending' — the…]] - rationale - tests/test_prelog.py
- [[After place_order raises, status must be updated to 'failed'.]] - rationale - tests/test_prelog.py
- [[Even on API failure, exactly one DB row must exist.]] - rationale - tests/test_prelog.py
- [[Exactly one DB row must be created (pre-log + in-place update, not two inserts).]] - rationale - tests/test_prelog.py
- [[F1 regression a successfully-placed live order must actually be counted by…]] - rationale - tests/test_prelog.py
- [[Helper run _place_live_order with the gate open and capture log calls.]] - rationale - tests/test_prelog.py
- [[TestPreLogPattern]] - code - tests/test_prelog.py
- [[_place_live_order must pre-log with status='pending' before calling place_order.]] - rationale - tests/test_prelog.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_219
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 183]]

## Top bridge nodes
- [[TestPreLogPattern]] - degree 9, connects to 1 community
- [[dot-test_placed_order_counts_toward_open_positions()]] - degree 4, connects to 1 community