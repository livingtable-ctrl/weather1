---
source_file: "tests/test_weather_markets.py"
type: "rationale"
community: "Module: tests"
location: "L1325"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# save_learned_weights must not write when any model weight is near zero.

## Connections
- [[.test_save_rejects_near_zero_weights()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests