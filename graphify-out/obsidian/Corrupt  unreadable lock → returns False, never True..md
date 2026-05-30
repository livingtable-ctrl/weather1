---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Module: tests"
location: "L145"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Corrupt / unreadable lock → returns False, never True.

## Connections
- [[.test_fails_closed_on_corrupt_lock_file()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests