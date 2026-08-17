---
type: community
cohesion: 0.17
members: 12
---

# Community 311

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[-10°F threshold must also pass the gate.]] - rationale - tests/test_phase2_batch_j.py
- [[dot-test_above_below_are_the_only_gated_types()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_condition_missing_threshold_is_none()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_condition_zero_is_not_none()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_negative_threshold_is_not_none()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_source_uses_is_not_none()]] - code - tests/test_phase2_batch_j.py
- [[Freeze markets (threshold=0°F) must not silently skip METAR lock-in.]] - rationale - tests/test_phase2_batch_j.py
- [[Missing threshold must be None — the gate correctly blocks it.]] - rationale - tests/test_phase2_batch_j.py
- [[Only 'above' and 'between' types are gated — 'range' with threshold=0 works.]] - rationale - tests/test_phase2_batch_j.py
- [[Source code must use 'is not None', not a bare truthiness check.]] - rationale - tests/test_phase2_batch_j.py
- [[TestMetarLockInZeroThreshold]] - code - tests/test_phase2_batch_j.py
- [[threshold=0.0 must pass the 'is not None' gate.]] - rationale - tests/test_phase2_batch_j.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_311
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 303]]

## Top bridge nodes
- [[TestMetarLockInZeroThreshold]] - degree 7, connects to 1 community