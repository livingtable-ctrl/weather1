---
type: community
cohesion: 0.33
members: 7
---

# Community 500

**Cohesion:** 0.33 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_acquires_when_no_lock_exists()]] - code - tests/test_cron_lock.py
- [[dot-test_lock_file_contains_pid_and_timestamps()]] - code - tests/test_cron_lock.py
- [[Helper point LOCK_PATH at tmp_path and call _acquire_cron_lock.]] - rationale - tests/test_cron_lock.py
- [[No existing lock → returns True and writes lock file.]] - rationale - tests/test_cron_lock.py
- [[TestAcquireCronLockFreshInstall]] - code - tests/test_cron_lock.py
- [[Written lock must be valid JSON with pid, started_at, heartbeat.]] - rationale - tests/test_cron_lock.py
- [[_acquire()]] - code - tests/test_cron_lock.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_500
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[_acquire()]] - degree 4, connects to 1 community
- [[TestAcquireCronLockFreshInstall]] - degree 3, connects to 1 community