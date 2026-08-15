---
type: community
cohesion: 0.33
members: 6
---

# Community 525

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_signal_values_absent_stores_null()]] - code - tests/test_tracker.py
- [[dot-test_signal_values_empty_dict_stores_valid_empty_json_not_null()]] - code - tests/test_tracker.py
- [[dot-test_signal_values_round_trip_through_upsert()]] - code - tests/test_tracker.py
- [[dot-test_signal_values_updates_on_reupsert()]] - code - tests/test_tracker.py
- [[TestLogPredictionSignalValues]] - code - tests/test_tracker.py
- [[log_prediction() must persist `signals` (backlog.txt SIGNAL GRADUATION IS A…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_525
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestLogPredictionSignalValues]] - degree 6, connects to 1 community