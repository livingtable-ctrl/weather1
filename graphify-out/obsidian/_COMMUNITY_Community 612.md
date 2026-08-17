---
type: community
cohesion: 0.40
members: 5
---

# Community 612

**Cohesion:** 0.40 - moderately connected
**Members:** 5 nodes

## Members
- [[dot-test_blocks_when_live_pid_holds_lock()]] - code - tests/test_cron_lock.py
- [[dot-test_overrides_dead_pid_lock()]] - code - tests/test_cron_lock.py
- [[Lock held by a dead PID → returns True and overwrites lock.]] - rationale - tests/test_cron_lock.py
- [[Lock held by a live PID → returns False (fail closed).]] - rationale - tests/test_cron_lock.py
- [[TestAcquireCronLockLivePid]] - code - tests/test_cron_lock.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_612
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestAcquireCronLockLivePid]] - degree 3, connects to 1 community