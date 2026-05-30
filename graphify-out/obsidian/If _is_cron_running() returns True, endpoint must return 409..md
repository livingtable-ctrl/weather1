---
source_file: "tests/test_p0_16_cron_endpoint.py"
type: "rationale"
community: "Module: tests"
location: "L30"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# If _is_cron_running() returns True, endpoint must return 409.

## Connections
- [[.test_returns_409_when_cron_already_running()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests