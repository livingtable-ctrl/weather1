---
type: community
cohesion: 0.40
members: 5
---

# Community 611

**Cohesion:** 0.40 - moderately connected
**Members:** 5 nodes

## Members
- [[dot-test_fails_closed_on_corrupt_lock_file()]] - code - tests/test_cron_lock.py
- [[dot-test_fails_closed_on_io_error()]] - code - tests/test_cron_lock.py
- [[Corrupt  unreadable lock → returns False, never True.]] - rationale - tests/test_cron_lock.py
- [[IO error writing lock → returns False, never True (old code returned True).]] - rationale - tests/test_cron_lock.py
- [[TestAcquireCronLockFailClosed]] - code - tests/test_cron_lock.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_611
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestAcquireCronLockFailClosed]] - degree 3, connects to 1 community