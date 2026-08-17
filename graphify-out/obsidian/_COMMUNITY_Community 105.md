---
type: community
cohesion: 0.11
members: 27
---

# Community 105

**Cohesion:** 0.11 - loosely connected
**Members:** 27 nodes

## Members
- [[dot-_recent_order()]] - code - tests/test_execution_stability.py
- [[dot-test_cmd_cron_exits_early_when_lock_denied()]] - code - tests/test_execution_stability.py
- [[dot-test_get_recent_orders_failure_does_not_raise()]] - code - tests/test_execution_stability.py
- [[dot-test_lock_acquired_when_no_file()]] - code - tests/test_execution_stability.py
- [[dot-test_lock_denied_when_fresh_file_exists()]] - code - tests/test_execution_stability.py
- [[dot-test_lock_released_in_finally()]] - code - tests/test_execution_stability.py
- [[dot-test_no_orders_no_warning()]] - code - tests/test_execution_stability.py
- [[dot-test_old_order_no_warning()]] - code - tests/test_execution_stability.py
- [[dot-test_recent_order_triggers_warning()]] - code - tests/test_execution_stability.py
- [[dot-test_release_lock_removes_file()]] - code - tests/test_execution_stability.py
- [[dot-test_release_missing_lock_is_noop()]] - code - tests/test_execution_stability.py
- [[dot-test_stale_lock_overridden()]] - code - tests/test_execution_stability.py
- [[Empty order list must not trigger any warning.]] - rationale - tests/test_execution_stability.py
- [[If an order was placed within the last 5 minutes, _check_startup_orders must…]] - rationale - tests/test_execution_stability.py
- [[If execution_log.get_recent_orders raises, _check_startup_orders must not…]] - rationale - tests/test_execution_stability.py
- [[Orders older than 5 minutes must not trigger a warning.]] - rationale - tests/test_execution_stability.py
- [[Return a fake order dict placed `minutes_ago` minutes in the past.]] - rationale - tests/test_execution_stability.py
- [[TestCheckStartupOrders]] - code - tests/test_execution_stability.py
- [[TestCronLock]] - code - tests/test_execution_stability.py
- [[_acquire_cron_lock() returns False when a live PID holds the lock.]] - rationale - tests/test_execution_stability.py
- [[_acquire_cron_lock() returns True and writes JSON lock when none exists.]] - rationale - tests/test_execution_stability.py
- [[_acquire_cron_lock() returns True when the locking PID is dead.]] - rationale - tests/test_execution_stability.py
- [[_import_main()]] - code - tests/test_execution_stability.py
- [[_release_cron_lock() deletes the lock file.]] - rationale - tests/test_execution_stability.py
- [[_release_cron_lock() is called even when cmd_cron raises mid-run.]] - rationale - tests/test_execution_stability.py
- [[_release_cron_lock() must not raise when lock file does not exist.]] - rationale - tests/test_execution_stability.py
- [[cmd_cron must call sys.exit(1) when _acquire_cron_lock() returns False.]] - rationale - tests/test_execution_stability.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_105
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[_import_main()]] - degree 12, connects to 1 community
- [[TestCronLock]] - degree 8, connects to 1 community
- [[TestCheckStartupOrders]] - degree 6, connects to 1 community