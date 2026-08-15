---
source_file: "tests/test_settlement_monitor.py"
type: "rationale"
community: "METAR Settlement Monitoring"
location: "L99"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/METAR_Settlement_Monitoring
---

# Signals older than max_age_minutes are filtered out.

## Connections
- [[dot-test_signals_expire_after_window()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/METAR_Settlement_Monitoring