---
source_file: "tests/test_phase2_batch_l.py"
type: "rationale"
community: "Module: tests"
location: "L333"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# build_client uses os.getenv at call time, not the stale module constant.

## Connections
- [[.test_build_client_reads_env_at_call_time()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests