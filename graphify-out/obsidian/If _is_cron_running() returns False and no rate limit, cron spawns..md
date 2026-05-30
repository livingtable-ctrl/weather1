---
source_file: "tests/test_p0_16_cron_endpoint.py"
type: "rationale"
community: "Module: tests"
location: "L44"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# If _is_cron_running() returns False and no rate limit, cron spawns.

## Connections
- [[.test_starts_successfully_when_no_cron_running()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests