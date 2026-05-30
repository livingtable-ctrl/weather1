---
source_file: "tests/test_weather_markets.py"
type: "rationale"
community: "Module: tests"
location: "L602"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Many zeros (>5% censored at 0) → result > raw mean (pulled toward 0.5).

## Connections
- [[.test_censoring_at_zero_shrinks_toward_half()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests