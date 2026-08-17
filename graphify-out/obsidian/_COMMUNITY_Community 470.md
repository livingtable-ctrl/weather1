---
type: community
cohesion: 0.25
members: 8
---

# Community 470

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_max_log_lines_constant_is_50000()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_prune_called_from_cron_on_monday()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_prune_feature_log_missing_file_returns_zero()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_prune_feature_log_no_op_when_under_limit()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_prune_feature_log_trims_oversized_file()]] - code - tests/test_phase3_batch_d.py
- [[P3-22 prune_feature_log must keep at most _MAX_LOG_LINES entries.]] - rationale - tests/test_phase3_batch_d.py
- [[TestFeatureImportancePruning]] - code - tests/test_phase3_batch_d.py
- [[cron.py must call prune_feature_log() in the Monday weekly sweep.]] - rationale - tests/test_phase3_batch_d.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_470
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestFeatureImportancePruning]] - degree 7, connects to 1 community