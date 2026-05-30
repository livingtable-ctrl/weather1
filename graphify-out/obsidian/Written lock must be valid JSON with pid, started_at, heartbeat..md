---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Module: tests"
location: "L28"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Written lock must be valid JSON with pid, started_at, heartbeat.

## Connections
- [[.test_lock_file_contains_pid_and_timestamps()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests