---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Module: tests"
location: "L22"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# No existing lock → returns True and writes lock file.

## Connections
- [[.test_acquires_when_no_lock_exists()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests