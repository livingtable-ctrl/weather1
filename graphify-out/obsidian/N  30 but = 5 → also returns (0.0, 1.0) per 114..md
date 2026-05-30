---
source_file: "tests/test_weather_markets.py"
type: "rationale"
community: "Module: tests"
location: "L555"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# N < 30 but >= 5 → also returns (0.0, 1.0) per #114.

## Connections
- [[.test_small_n_under_30_returns_wide_ci()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests