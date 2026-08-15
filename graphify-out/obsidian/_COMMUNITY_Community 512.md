---
type: community
cohesion: 0.33
members: 6
---

# Community 512

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_returns_false_for_corrupt_lock_file()]] - code - tests/test_p0_16_cron_endpoint.py
- [[dot-test_returns_false_for_dead_pid_with_psutil()]] - code - tests/test_p0_16_cron_endpoint.py
- [[dot-test_returns_false_when_no_lock_file()]] - code - tests/test_p0_16_cron_endpoint.py
- [[dot-test_returns_true_for_live_pid_with_psutil()]] - code - tests/test_p0_16_cron_endpoint.py
- [[TestIsCronRunning]] - code - tests/test_p0_16_cron_endpoint.py
- [[Unit tests for the _is_cron_running() helper in cron.py.]] - rationale - tests/test_p0_16_cron_endpoint.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_512
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 566]]

## Top bridge nodes
- [[TestIsCronRunning]] - degree 6, connects to 1 community