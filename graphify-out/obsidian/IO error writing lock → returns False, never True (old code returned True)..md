---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Module: tests"
location: "L158"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# I/O error writing lock → returns False, never True (old code returned True).

## Connections
- [[.test_fails_closed_on_io_error()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests