---
type: community
cohesion: 0.25
members: 8
---

# Community 432

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-_make_db()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_prune_api_requests_exported()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_prune_deletes_old_rows()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_prune_returns_zero_when_nothing_old()]] - code - tests/test_phase2_batch_c.py
- [[P2-13 prune_api_requests must delete old rows and leave recent ones.]] - rationale - tests/test_phase2_batch_c.py
- [[Path_18]] - code
- [[TestPruneApiRequests]] - code - tests/test_phase2_batch_c.py
- [[prune_api_requests must be importable from tracker.]] - rationale - tests/test_phase2_batch_c.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_432
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 119]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]

## Top bridge nodes
- [[TestPruneApiRequests]] - degree 7, connects to 2 communities
- [[dot-test_prune_api_requests_exported()]] - degree 3, connects to 1 community