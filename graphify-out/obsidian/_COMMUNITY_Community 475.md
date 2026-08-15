---
type: community
cohesion: 0.29
members: 7
---

# Community 475

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_insufficient_weeks_no_alert()]] - code - tests/test_p9_p10.py
- [[dot-test_one_bad_week_does_not_trigger()]] - code - tests/test_p9_p10.py
- [[dot-test_two_bad_weeks_triggers_alert()]] - code - tests/test_p9_p10.py
- [[Both recent weeks above threshold → alert should fire.]] - rationale - tests/test_p9_p10.py
- [[Fewer than 2 weeks → no alert check.]] - rationale - tests/test_p9_p10.py
- [[Only one of the two recent weeks above threshold → no alert.]] - rationale - tests/test_p9_p10.py
- [[TestWeeklyBrierAlert]] - code - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_475
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 50]]

## Top bridge nodes
- [[TestWeeklyBrierAlert]] - degree 4, connects to 1 community