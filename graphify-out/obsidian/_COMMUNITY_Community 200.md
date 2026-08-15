---
type: community
cohesion: 0.12
members: 17
---

# Community 200

**Cohesion:** 0.12 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-test_breakeven_trades_excluded_from_win_rate_denominator()]] - code - tests/test_alerts_side.py
- [[dot-test_brier_check_failure_fails_closed()]] - code - tests/test_alerts_side.py
- [[dot-test_brier_check_still_runs_when_trades_is_empty()]] - code - tests/test_alerts_side.py
- [[dot-test_daily_loss_condition_works_without_balance_param()]] - code - tests/test_alerts_side.py
- [[dot-test_days_out_none_does_not_crash()]] - code - tests/test_alerts_side.py
- [[dot-test_kill_switch_path_matches_canonical_paths_module()]] - code - tests/test_alerts_side.py
- [[dot-test_none_settled_at_does_not_crash_daily_loss_condition()]] - code - tests/test_alerts_side.py
- [[dot-test_unrecognized_anomaly_message_logs_a_warning()]] - code - tests/test_alerts_side.py
- [[A Brier-check exception (e.g. a locked tracker.db) must be treated as…]] - rationale - tests/test_alerts_side.py
- [[A trade record with days_out=None (key present, not absent) must not TypeError…]] - rationale - tests/test_alerts_side.py
- [[Deep-review followup an early `if not trades return triggered` used to skip…]] - rationale - tests/test_alerts_side.py
- [[Deep-review followup breakeven (pnl == 0) trades were counted in the win-rate…]] - rationale - tests/test_alerts_side.py
- [[Deep-review followup t.get(settled_at, ) only covers a MISSING key -- a…]] - rationale - tests/test_alerts_side.py
- [[Regression tests for the lower-severity Fable findings fixed alongside the…]] - rationale - tests/test_alerts_side.py
- [[TestGroupCFixes]] - code - tests/test_alerts_side.py
- [[alerts.py's kill-switchblack-swan paths must be the same worktree-safe paths…]] - rationale - tests/test_alerts_side.py
- [[balance isn't actually used in the daily-loss math (only peak_balance is) — the…]] - rationale - tests/test_alerts_side.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_200
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 167]]
- 3 edges to [[_COMMUNITY_Community 208]]
- 1 edge to [[_COMMUNITY_Community 194]]
- 1 edge to [[_COMMUNITY_Community 223]]

## Top bridge nodes
- [[dot-test_brier_check_failure_fails_closed()]] - degree 4, connects to 2 communities
- [[dot-test_days_out_none_does_not_crash()]] - degree 4, connects to 2 communities
- [[TestGroupCFixes]] - degree 10, connects to 1 community
- [[dot-test_breakeven_trades_excluded_from_win_rate_denominator()]] - degree 3, connects to 1 community
- [[dot-test_brier_check_still_runs_when_trades_is_empty()]] - degree 3, connects to 1 community