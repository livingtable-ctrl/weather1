---
type: community
cohesion: 0.25
members: 8
---

# Community 467

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_detect_brier_drift_detects_degradation()]] - code - tests/test_p9_p10.py
- [[dot-test_detect_brier_drift_improvement_not_flagged()]] - code - tests/test_p9_p10.py
- [[dot-test_detect_brier_drift_insufficient_data()]] - code - tests/test_p9_p10.py
- [[dot-test_detect_brier_drift_no_drift()]] - code - tests/test_p9_p10.py
- [[Early Brier=0.12, recent Brier=0.22 → delta=0.10  threshold=0.05 → drifting.]] - rationale - tests/test_p9_p10.py
- [[If Brier improves (negative delta) it is not flagged as drift.]] - rationale - tests/test_p9_p10.py
- [[Stable Brier over time should not trigger drift.]] - rationale - tests/test_p9_p10.py
- [[TestDriftDetection]] - code - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_467
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 54]]

## Top bridge nodes
- [[TestDriftDetection]] - degree 5, connects to 1 community