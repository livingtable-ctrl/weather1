---
source_file: "tests/test_weather_markets.py"
type: "rationale"
community: "Module: tests"
location: "L1417"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# load_learned_weights must return {} when any weight is <= 0.

## Connections
- [[.test_load_rejects_non_positive_weights()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests