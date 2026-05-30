---
source_file: "tests/test_phase2_batch_l.py"
type: "rationale"
community: "Module: tests"
location: "L199"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Soft anomaly (should_halt=False) must NOT stop the cron cycle.

## Connections
- [[.test_cron_halts_only_on_should_halt_true()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests