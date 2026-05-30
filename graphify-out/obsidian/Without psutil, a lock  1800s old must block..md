---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Module: tests"
location: "L97"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Without psutil, a lock < 1800s old must block.

## Connections
- [[.test_blocks_when_lock_is_fresh_without_psutil()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests