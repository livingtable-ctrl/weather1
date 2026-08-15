---
type: community
cohesion: 0.09
members: 24
---

# Community 121

**Cohesion:** 0.09 - loosely connected
**Members:** 24 nodes

## Members
- [[dot-test_acquires_when_no_lock_exists()]] - code - tests/test_cron_lock.py
- [[dot-test_blocks_when_live_pid_holds_lock()]] - code - tests/test_cron_lock.py
- [[dot-test_blocks_when_lock_is_fresh_without_psutil()]] - code - tests/test_cron_lock.py
- [[dot-test_fails_closed_on_corrupt_lock_file()]] - code - tests/test_cron_lock.py
- [[dot-test_fails_closed_on_io_error()]] - code - tests/test_cron_lock.py
- [[dot-test_lock_file_contains_pid_and_timestamps()]] - code - tests/test_cron_lock.py
- [[dot-test_overrides_dead_pid_lock()]] - code - tests/test_cron_lock.py
- [[dot-test_overrides_stale_lock_without_psutil()]] - code - tests/test_cron_lock.py
- [[Corrupt  unreadable lock → returns False, never True.]] - rationale - tests/test_cron_lock.py
- [[Helper point LOCK_PATH at tmp_path and call _acquire_cron_lock.]] - rationale - tests/test_cron_lock.py
- [[IO error writing lock → returns False, never True (old code returned True).]] - rationale - tests/test_cron_lock.py
- [[Lock held by a dead PID → returns True and overwrites lock.]] - rationale - tests/test_cron_lock.py
- [[Lock held by a live PID → returns False (fail closed).]] - rationale - tests/test_cron_lock.py
- [[No existing lock → returns True and writes lock file.]] - rationale - tests/test_cron_lock.py
- [[P0-5 _acquire_cron_lock must fail closed and use PID-aware stale detection.]] - rationale - tests/test_cron_lock.py
- [[TestAcquireCronLockFailClosed]] - code - tests/test_cron_lock.py
- [[TestAcquireCronLockFreshInstall]] - code - tests/test_cron_lock.py
- [[TestAcquireCronLockLivePid]] - code - tests/test_cron_lock.py
- [[TestAcquireCronLockNoPsutil]] - code - tests/test_cron_lock.py
- [[Without psutil, a lock  1800s old must block.]] - rationale - tests/test_cron_lock.py
- [[Without psutil, a lock  1800s old must be overridden.]] - rationale - tests/test_cron_lock.py
- [[Written lock must be valid JSON with pid, started_at, heartbeat.]] - rationale - tests/test_cron_lock.py
- [[_acquire()]] - code - tests/test_cron_lock.py
- [[test_cron_lock.py]] - code - tests/test_cron_lock.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_121
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 109]]

## Top bridge nodes
- [[test_cron_lock.py]] - degree 7, connects to 1 community