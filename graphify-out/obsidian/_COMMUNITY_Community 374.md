---
type: community
cohesion: 0.20
members: 10
---

# Community 374

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_cron_source_no_exact_hour_check()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_retrain_fires_when_marker_old()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_retrain_fires_when_no_marker()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_retrain_skipped_when_marker_recent()]] - code - tests/test_phase2_batch_m.py
- [[Marker file 6 days old → should retrain.]] - rationale - tests/test_phase2_batch_m.py
- [[Marker file less than 6 days old → should NOT retrain.]] - rationale - tests/test_phase2_batch_m.py
- [[TestMlRetrainMarkerFile]] - code - tests/test_phase2_batch_m.py
- [[When marker file is absent, retrain should be attempted.]] - rationale - tests/test_phase2_batch_m.py
- [[cron retrain block must use .last_ml_retrain marker, not exact UTC hour.]] - rationale - tests/test_phase2_batch_m.py
- [[cron._cmd_cron_body must NOT use exact-hour retrain logic.]] - rationale - tests/test_phase2_batch_m.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_374
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[TestMlRetrainMarkerFile]] - degree 7, connects to 2 communities