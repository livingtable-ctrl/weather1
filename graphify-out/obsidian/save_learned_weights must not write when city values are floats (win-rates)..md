---
source_file: "tests/test_weather_markets.py"
type: "rationale"
community: "Module: tests"
location: "L1306"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# save_learned_weights must not write when city values are floats (win-rates).

## Connections
- [[.test_save_rejects_float_city_values()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests