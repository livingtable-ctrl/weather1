---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Module: tests"
location: "L120"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Without psutil, a lock > 1800s old must be overridden.

## Connections
- [[.test_overrides_stale_lock_without_psutil()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests