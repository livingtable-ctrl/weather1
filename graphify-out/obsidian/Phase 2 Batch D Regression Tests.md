---
source_file: "tests/test_phase2_batch_d.py"
type: "code"
community: "METAR Settlement Monitoring"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/METAR_Settlement_Monitoring
---

# Phase 2 Batch D Regression Tests

## Connections
- [[ForecastCache]] - `imports` [EXTRACTED]
- [[Phase 2 Batch D regression tests P2-6, P2-15.]] - `rationale_for` [EXTRACTED]
- [[Phase 2 Batch J Regression Tests]] - `shares_data_with` [INFERRED]
- [[TestBetweenLockInDynamicConfidence]] - `contains` [EXTRACTED]
- [[TestGetLivePrecipObs]] - `contains` [EXTRACTED]
- [[ZoneInfo]] - `imports_from` [EXTRACTED]
- [[_dynamic_lock_in_confidence()]] - `calls` [EXTRACTED]
- [[_metar_lock_in()]] - `calls` [EXTRACTED]
- [[_reset_nws_cb()]] - `contains` [EXTRACTED]
- [[get_live_precip_obs()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/METAR_Settlement_Monitoring