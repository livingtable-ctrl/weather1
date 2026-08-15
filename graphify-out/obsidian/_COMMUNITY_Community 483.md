---
type: community
cohesion: 0.29
members: 7
---

# Community 483

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_get_pnl_by_signal_source_groups_correctly()]] - code - tests/test_pnl_attribution.py
- [[dot-test_get_pnl_by_signal_source_has_required_keys()]] - code - tests/test_pnl_attribution.py
- [[dot-test_log_prediction_accepts_signal_source()]] - code - tests/test_pnl_attribution.py
- [[Each entry has brier, n, win_rate keys.]] - rationale - tests/test_pnl_attribution.py
- [[TestPnLAttribution]] - code - tests/test_pnl_attribution.py
- [[get_pnl_by_signal_source returns per-source stats.]] - rationale - tests/test_pnl_attribution.py
- [[log_prediction stores signal_source kwarg.]] - rationale - tests/test_pnl_attribution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_483
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]

## Top bridge nodes
- [[TestPnLAttribution]] - degree 4, connects to 1 community