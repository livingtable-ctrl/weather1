---
source_file: "tests/test_phase4.py"
type: "rationale"
community: "Module: tests"
location: "L144"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# temp=38, humidity=90 → result < 38 (moist-cold penalty).

## Connections
- [[.test_cold_high_humidity_below_actual()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests