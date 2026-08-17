---
type: community
cohesion: 0.22
members: 9
---

# Community 424

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_locked_above_threshold_after_2pm()]] - code - tests/test_metar.py
- [[dot-test_locked_below_threshold_after_2pm()]] - code - tests/test_metar.py
- [[dot-test_not_locked_before_2pm()]] - code - tests/test_metar.py
- [[dot-test_not_locked_within_margin()]] - code - tests/test_metar.py
- [[At 5 PM local with current temp 80°F, threshold 65°F 'above' → locked IN (it…]] - rationale - tests/test_metar.py
- [[At 5 PM local with temp 10°C (50°F), threshold 65°F 'above' → locked OUT (it…]] - rationale - tests/test_metar.py
- [[Before 2 PM local, never lock in regardless of temperature.]] - rationale - tests/test_metar.py
- [[Temperature within margin_f of threshold is too close to lock in.]] - rationale - tests/test_metar.py
- [[TestCheckMetarLockout]] - code - tests/test_metar.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_424
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[TestCheckMetarLockout]] - degree 6, connects to 2 communities