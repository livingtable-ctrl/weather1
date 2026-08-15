---
source_file: "tests/test_settlement_monitor.py"
type: "rationale"
community: "METAR Settlement Monitoring"
location: "L185"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/METAR_Settlement_Monitoring
---

# max_temp_f >2°F above the upper edge → locked=True, outcome=no.

## Connections
- [[dot-test_max_temp_cleared_upper_edge_with_margin_locks_no()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/METAR_Settlement_Monitoring