---
source_file: "tests/test_main_cron_smoke.py"
type: "rationale"
community: "Module: tests"
location: "L14"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Patch every external call cmd_cron makes so it can run without network.

## Connections
- [[minimal_mocks()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests