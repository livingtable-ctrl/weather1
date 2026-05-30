---
source_file: "tests/test_metar.py"
type: "rationale"
community: "Module: tests"
location: "L166"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# P1-2: temperature below -80°F → None (physically impossible).

## Connections
- [[.test_returns_none_for_implausible_low_temp()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests