---
type: community
cohesion: 0.29
members: 7
---

# Community 518

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_restore_default_raises()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_restore_snapshots_existing_data()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_restore_with_confirm_proceeds()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_restore_without_confirm_raises()]] - code - tests/test_phase2_batch_g.py
- [[P2-47 restore_data must require confirm=True to prevent silent overwrites.]] - rationale - tests/test_phase2_batch_g.py
- [[TestRestoreDataConfirm]] - code - tests/test_phase2_batch_g.py
- [[restore_data must snapshot current data before overwriting.]] - rationale - tests/test_phase2_batch_g.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_518
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 221]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestRestoreDataConfirm]] - degree 6, connects to 1 community
- [[dot-test_restore_snapshots_existing_data()]] - degree 3, connects to 1 community
- [[dot-test_restore_with_confirm_proceeds()]] - degree 2, connects to 1 community