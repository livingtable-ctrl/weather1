---
source_file: "tests/test_execution_stability.py"
type: "rationale"
community: "Module: tests"
location: "L220"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# _acquire_cron_lock() returns False when a live PID holds the lock.

## Connections
- [[.test_lock_denied_when_fresh_file_exists()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests