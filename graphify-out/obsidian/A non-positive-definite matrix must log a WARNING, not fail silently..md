---
source_file: "tests/test_phase2_batch_f.py"
type: "rationale"
community: "Module: tests"
location: "L80"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# A non-positive-definite matrix must log a WARNING, not fail silently.

## Connections
- [[.test_cholesky_failure_logs_warning()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests