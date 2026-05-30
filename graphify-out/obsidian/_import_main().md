---
source_file: "tests/test_execution_stability.py"
type: "code"
community: "Module: tests"
location: "L23"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# _import_main()

## Connections
- [[.test_cmd_cron_exits_early_when_lock_denied()]] - `calls` [EXTRACTED]
- [[.test_get_recent_orders_failure_does_not_raise()]] - `calls` [EXTRACTED]
- [[.test_lock_acquired_when_no_file()]] - `calls` [EXTRACTED]
- [[.test_lock_denied_when_fresh_file_exists()]] - `calls` [EXTRACTED]
- [[.test_lock_released_in_finally()]] - `calls` [EXTRACTED]
- [[.test_no_orders_no_warning()]] - `calls` [EXTRACTED]
- [[.test_old_order_no_warning()]] - `calls` [EXTRACTED]
- [[.test_recent_order_triggers_warning()]] - `calls` [EXTRACTED]
- [[.test_release_lock_removes_file()]] - `calls` [EXTRACTED]
- [[.test_release_missing_lock_is_noop()]] - `calls` [EXTRACTED]
- [[.test_stale_lock_overridden()]] - `calls` [EXTRACTED]
- [[test_execution_stability.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests