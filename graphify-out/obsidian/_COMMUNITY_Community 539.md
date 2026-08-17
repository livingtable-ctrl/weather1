---
type: community
cohesion: 0.33
members: 6
---

# Community 539

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[Grade Audit Module Doc nws.py]] - document - docs/grade_audit/modules/nws.md
- [[NWS Sigma Ladder (days_out-based)]] - document - docs/grade_audit/modules/nws.md
- [[Tests for obs_weight_used and local_hour DB columns (Phase 6.0).]] - rationale - tests/test_obs_weight.py
- [[predictions table must have obs_weight_used and local_hour columns.]] - rationale - tests/test_obs_weight.py
- [[test_obs_weight.py]] - code - tests/test_obs_weight.py
- [[test_predictions_table_has_obs_weight_and_local_hour_columns()]] - code - tests/test_obs_weight.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_539
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 6]]

## Top bridge nodes
- [[Grade Audit Module Doc nws.py]] - degree 4, connects to 2 communities
- [[test_obs_weight.py]] - degree 4, connects to 1 community