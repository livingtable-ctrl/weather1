---
type: community
cohesion: 0.40
members: 5
---

# Community 633

**Cohesion:** 0.40 - moderately connected
**Members:** 5 nodes

## Members
- [[dot-test_purge_old_predictions_keeps_recent()]] - code - tests/test_tracker.py
- [[dot-test_purge_old_predictions_removes_settled()]] - code - tests/test_tracker.py
- [[TestRetentionPolicy]] - code - tests/test_tracker.py
- [[purge_old_predictions keeps predictions within retention_days.]] - rationale - tests/test_tracker.py
- [[purge_old_predictions removes settled predictions older than retention_days.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_633
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 35]]

## Top bridge nodes
- [[TestRetentionPolicy]] - degree 3, connects to 1 community