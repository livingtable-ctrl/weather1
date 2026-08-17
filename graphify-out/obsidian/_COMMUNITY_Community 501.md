---
type: community
cohesion: 0.29
members: 7
---

# Community 501

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_batch_can_set_was_traded_true()]] - code - tests/test_debug_fixes.py
- [[dot-test_batch_does_not_overwrite_was_traded_true()]] - code - tests/test_debug_fixes.py
- [[dot-test_fresh_rows_are_still_inserted()]] - code - tests/test_debug_fixes.py
- [[New rows must still be inserted when there's no conflict.]] - rationale - tests/test_debug_fixes.py
- [[Re-running batch_log_analysis_attempts must not reset was_traded to 0.]] - rationale - tests/test_debug_fixes.py
- [[TestAnalysisAttemptsUpsert]] - code - tests/test_debug_fixes.py
- [[was_traded can go from 0 → 1 via log_analysis_attempt after batch insert.]] - rationale - tests/test_debug_fixes.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_501
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestAnalysisAttemptsUpsert]] - degree 4, connects to 1 community