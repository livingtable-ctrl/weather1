---
type: community
cohesion: 0.33
members: 6
---

# Community 524

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_past_days_computed_from_utc_today_not_local_date()]] - code - tests/test_tracker.py
- [[dot-test_past_days_ge_5_proceeds_past_the_guard()]] - code - tests/test_tracker.py
- [[Mock utc_today() to a date BEFORE target_date, so the fixed function's own…]] - rationale - tests/test_tracker.py
- [[Sanity check the guard's positive case still works when utc_today() is well…]] - rationale - tests/test_tracker.py
- [[TestFetchPreviousRunDailyUsesUtcToday]] - code - tests/test_tracker.py
- [[backlog.txt utils.utc_today() SAYS 'USE EVERYWHERE INSTEAD OF date.today()' --…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_524
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestFetchPreviousRunDailyUsesUtcToday]] - degree 4, connects to 1 community