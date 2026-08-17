---
type: community
cohesion: 0.15
members: 13
---

# Community 274

**Cohesion:** 0.15 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-test_breakeven_trades_excluded_from_win_rate_denominator()]] - code - tests/test_alerts_side.py
- [[dot-test_brier_check_still_runs_when_trades_is_empty()]] - code - tests/test_alerts_side.py
- [[dot-test_daily_loss_condition_works_without_balance_param()]] - code - tests/test_alerts_side.py
- [[dot-test_kill_switch_path_matches_canonical_paths_module()]] - code - tests/test_alerts_side.py
- [[dot-test_none_settled_at_does_not_crash_daily_loss_condition()]] - code - tests/test_alerts_side.py
- [[dot-test_unrecognized_anomaly_message_logs_a_warning()]] - code - tests/test_alerts_side.py
- [[Deep-review followup an early `if not trades return triggered` used to skip…]] - rationale - tests/test_alerts_side.py
- [[Deep-review followup breakeven (pnl == 0) trades were counted in the win-rate…]] - rationale - tests/test_alerts_side.py
- [[Deep-review followup t.get(settled_at, ) only covers a MISSING key -- a…_2]] - rationale - tests/test_alerts_side.py
- [[Regression tests for the lower-severity Fable findings fixed alongside the…]] - rationale - tests/test_alerts_side.py
- [[TestGroupCFixes]] - code - tests/test_alerts_side.py
- [[alerts.py's kill-switchblack-swan paths must be the same worktree-safe paths…]] - rationale - tests/test_alerts_side.py
- [[balance isn't actually used in the daily-loss math (only peak_balance is) — the…]] - rationale - tests/test_alerts_side.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_274
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 108]]
- 3 edges to [[_COMMUNITY_Community 170]]
- 1 edge to [[_COMMUNITY_Community 359]]
- 1 edge to [[_COMMUNITY_Community 142]]

## Top bridge nodes
- [[TestGroupCFixes]] - degree 10, connects to 2 communities
- [[dot-test_breakeven_trades_excluded_from_win_rate_denominator()]] - degree 3, connects to 1 community
- [[dot-test_brier_check_still_runs_when_trades_is_empty()]] - degree 3, connects to 1 community
- [[dot-test_daily_loss_condition_works_without_balance_param()]] - degree 3, connects to 1 community
- [[dot-test_none_settled_at_does_not_crash_daily_loss_condition()]] - degree 3, connects to 1 community