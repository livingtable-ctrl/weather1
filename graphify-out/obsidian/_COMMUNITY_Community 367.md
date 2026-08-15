---
type: community
cohesion: 0.20
members: 10
---

# Community 367

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_confidence_increases_with_clearance()]] - code - tests/test_metar.py
- [[dot-test_confidence_increases_with_hour()]] - code - tests/test_metar.py
- [[dot-test_large_clearance_late_evening_gets_high_confidence()]] - code - tests/test_metar.py
- [[dot-test_near_threshold_early_afternoon_confidence_below_old_hardcoded()]] - code - tests/test_metar.py
- [[Confidence must be strictly higher for a later observation time with the same…]] - rationale - tests/test_metar.py
- [[Confidence must be strictly higher for larger temperature clearance at the same…]] - rationale - tests/test_metar.py
- [[Regression for L6-D 15°F clearance at 10 PM must yield confidence = 0.90.…]] - rationale - tests/test_metar.py
- [[Regression for L6-D 3°F clearance at 2 PM must yield confidence  0.90. Before…]] - rationale - tests/test_metar.py
- [[Regression tests for L6-D METAR lock-in confidence must scale with temperature…]] - rationale - tests/test_metar.py
- [[TestDynamicLockInConfidence]] - code - tests/test_metar.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_367
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 73]]

## Top bridge nodes
- [[TestDynamicLockInConfidence]] - degree 7, connects to 2 communities