---
type: community
cohesion: 0.18
members: 15
---

# Community 223

**Cohesion:** 0.18 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-test_exception_returns_empty_no_halt()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_halt_thresholds_exported()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_is_halt_level_consecutive_losses_at_threshold()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_is_halt_level_consecutive_losses_below_threshold()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_is_halt_level_edge_decay_halt()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_is_halt_level_edge_decay_no_halt()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_is_halt_level_win_rate_above_threshold()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_is_halt_level_win_rate_below_threshold()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_no_anomalies_no_halt()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_return_type_is_tuple()]] - code - tests/test_phase2_batch_l.py
- [[On exception, return (error_msg, True) — fail-closed (R6).]] - rationale - tests/test_phase2_batch_l.py
- [[Return True when an alert message crosses the halt threshold.]] - rationale - alerts.py
- [[TestRunAnomalyCheckReturnsTuple]] - code - tests/test_phase2_batch_l.py
- [[_is_halt_level()]] - code - alerts.py
- [[run_anomaly_check must return (liststr, bool) and halt selectively.]] - rationale - tests/test_phase2_batch_l.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_223
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 417]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Community 200]]
- 1 edge to [[_COMMUNITY_Community 194]]
- 1 edge to [[_COMMUNITY_Community 94]]

## Top bridge nodes
- [[_is_halt_level()]] - degree 12, connects to 5 communities
- [[TestRunAnomalyCheckReturnsTuple]] - degree 13, connects to 2 communities
- [[dot-test_exception_returns_empty_no_halt()]] - degree 3, connects to 1 community
- [[dot-test_no_anomalies_no_halt()]] - degree 2, connects to 1 community
- [[dot-test_return_type_is_tuple()]] - degree 2, connects to 1 community