---
source_file: "tests/test_trade_improvements.py"
type: "rationale"
community: "Module: tests"
location: "L136"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# cron.py must skip signals where probability edge < MIN_PROB_EDGE (0.08).

## Connections
- [[TestMinProbEdgeGate]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests