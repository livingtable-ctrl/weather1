---
type: community
cohesion: 0.18
members: 11
---

# Community 342

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_clear_missing_flag_is_noop()]] - code - tests/test_execution_stability.py
- [[dot-test_flag_cleared_at_end()]] - code - tests/test_execution_stability.py
- [[dot-test_flag_written_at_start()]] - code - tests/test_execution_stability.py
- [[dot-test_fresh_flag_triggers_warning()]] - code - tests/test_execution_stability.py
- [[dot-test_stale_flag_no_warning()]] - code - tests/test_execution_stability.py
- [[A flag older than 600 s must NOT trigger a warning.]] - rationale - tests/test_execution_stability.py
- [[A flag younger than 600 s must trigger a WARNING.]] - rationale - tests/test_execution_stability.py
- [[TestWriteCronRunningFlag]] - code - tests/test_execution_stability.py
- [[_clear_cron_running_flag() must not raise when flag does not exist.]] - rationale - tests/test_execution_stability.py
- [[_clear_cron_running_flag() removes the flag file.]] - rationale - tests/test_execution_stability.py
- [[_write_cron_running_flag() creates the flag file with a UTC ISO timestamp.]] - rationale - tests/test_execution_stability.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_342
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestWriteCronRunningFlag]] - degree 6, connects to 1 community