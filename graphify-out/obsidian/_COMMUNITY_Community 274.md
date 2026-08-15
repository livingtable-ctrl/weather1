---
type: community
cohesion: 0.15
members: 13
---

# Community 274

**Cohesion:** 0.15 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-setup_method()_6]] - code - tests/test_execution_log.py
- [[dot-teardown_method()_6]] - code - tests/test_execution_log.py
- [[dot-test_add_live_loss_write_failure_fails_closed()]] - code - tests/test_execution_log.py
- [[dot-test_daily_live_loss_accumulates()]] - code - tests/test_execution_log.py
- [[dot-test_daily_live_loss_add_returns_new_total()]] - code - tests/test_execution_log.py
- [[dot-test_daily_live_loss_returns_zero_for_new_day()]] - code - tests/test_execution_log.py
- [[dot-test_degraded_flag_clears_on_next_successful_write()]] - code - tests/test_execution_log.py
- [[dot-test_degraded_flag_from_yesterday_does_not_affect_today()]] - code - tests/test_execution_log.py
- [[A DB write that raises must not silently report 0.0 (the old bug) — it should…]] - rationale - tests/test_execution_log.py
- [[Once the DB recovers, a real write should clear the fail-closed flag.]] - rationale - tests/test_execution_log.py
- [[Seeding yesterday's row should not affect today's total.]] - rationale - tests/test_execution_log.py
- [[TestDailyLiveLoss]] - code - tests/test_execution_log.py
- [[The flag is date-keyed and should not linger past the day it was set.]] - rationale - tests/test_execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_274
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]

## Top bridge nodes
- [[TestDailyLiveLoss]] - degree 9, connects to 1 community