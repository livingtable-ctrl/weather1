---
source_file: "tests/test_p0_16_cron_endpoint.py"
type: "rationale"
community: "Module: tests"
location: "L61"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# 409 must be returned even when the per-IP rate limit is not yet exceeded.

## Connections
- [[.test_concurrent_guard_checked_before_rate_limit()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests