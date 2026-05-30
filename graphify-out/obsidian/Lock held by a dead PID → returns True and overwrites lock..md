---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Module: tests"
location: "L66"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Lock held by a dead PID → returns True and overwrites lock.

## Connections
- [[.test_overrides_dead_pid_lock()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests