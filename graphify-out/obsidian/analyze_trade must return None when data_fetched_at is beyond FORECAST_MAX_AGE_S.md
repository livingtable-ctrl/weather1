---
source_file: "tests/test_data_freshness.py"
type: "rationale"
community: "Module: tests"
location: "L85"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# analyze_trade must return None when data_fetched_at is beyond FORECAST_MAX_AGE_S

## Connections
- [[test_analyze_trade_rejects_stale_data()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests