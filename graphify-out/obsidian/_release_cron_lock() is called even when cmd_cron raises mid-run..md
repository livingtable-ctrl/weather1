---
source_file: "tests/test_execution_stability.py"
type: "rationale"
community: "Module: tests"
location: "L324"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# _release_cron_lock() is called even when cmd_cron raises mid-run.

## Connections
- [[.test_lock_released_in_finally()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests