---
source_file: "tests/test_execution_stability.py"
type: "rationale"
community: "Community 49"
location: "L306"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Community_49
---

# cmd_cron must call sys.exit(1) when _acquire_cron_lock() returns False.

## Connections
- [[dot-test_cmd_cron_exits_early_when_lock_denied()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Community_49