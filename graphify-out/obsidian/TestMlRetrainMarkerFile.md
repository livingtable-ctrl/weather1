---
source_file: "tests/test_phase2_batch_m.py"
type: "code"
community: "Module: tests"
location: "L13"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# TestMlRetrainMarkerFile

## Connections
- [[.test_cron_source_no_exact_hour_check()]] - `method` [EXTRACTED]
- [[.test_retrain_fires_when_marker_old()]] - `method` [EXTRACTED]
- [[.test_retrain_fires_when_no_marker()]] - `method` [EXTRACTED]
- [[.test_retrain_skipped_when_marker_recent()]] - `method` [EXTRACTED]
- [[ForecastCache]] - `uses` [INFERRED]
- [[cron retrain block must use .last_ml_retrain marker, not exact UTC hour.]] - `rationale_for` [EXTRACTED]
- [[test_phase2_batch_m.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests