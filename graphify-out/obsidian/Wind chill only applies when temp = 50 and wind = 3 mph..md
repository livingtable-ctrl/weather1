---
source_file: "tests/test_weather_markets.py"
type: "rationale"
community: "Module: tests"
location: "L47"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Wind chill only applies when temp <= 50 and wind >= 3 mph.

## Connections
- [[.test_boundary_wind_chill_threshold()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests