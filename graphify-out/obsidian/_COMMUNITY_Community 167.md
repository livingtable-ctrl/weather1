---
type: community
cohesion: 0.12
members: 19
---

# Community 167

**Cohesion:** 0.12 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-test_activate_black_swan_halt_writes_files()]] - code - tests/test_p9_p10.py
- [[dot-test_clear_black_swan_state()]] - code - tests/test_p9_p10.py
- [[dot-test_clear_black_swan_state_no_file()]] - code - tests/test_p9_p10.py
- [[dot-test_consecutive_loss_below_threshold_ok()]] - code - tests/test_p9_p10.py
- [[dot-test_consecutive_loss_triggers()]] - code - tests/test_p9_p10.py
- [[dot-test_get_black_swan_status_none_when_absent()]] - code - tests/test_p9_p10.py
- [[dot-test_get_black_swan_status_returns_data()]] - code - tests/test_p9_p10.py
- [[dot-test_no_conditions_on_clean_trades()]] - code - tests/test_p9_p10.py
- [[dot-test_no_side_consecutive_losses_trigger_black_swan()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_consecutive_wins_not_black_swan()]] - code - tests/test_alerts_side.py
- [[dot-test_run_black_swan_check_triggers_halt()]] - code - tests/test_p9_p10.py
- [[9 consecutive losses should NOT trigger (default threshold=10).]] - rationale - tests/test_p9_p10.py
- [[P1-14 12 consecutive NO-side losses (outcome='yes') trigger black swan.]] - rationale - tests/test_alerts_side.py
- [[P1-14 12 consecutive NO-side wins must not trigger black swan.]] - rationale - tests/test_alerts_side.py
- [[P10.2 Detect extreme abnormal conditions that warrant emergency shutdown.…]] - rationale - alerts.py
- [[TestBlackSwanMode]] - code - tests/test_p9_p10.py
- [[TestCheckBlackSwanNoSide]] - code - tests/test_alerts_side.py
- [[check_black_swan_conditions()]] - code - alerts.py
- [[run_black_swan_check activates kill switch when conditions are met.]] - rationale - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_167
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 200]]
- 4 edges to [[_COMMUNITY_Community 194]]
- 2 edges to [[_COMMUNITY_Community 50]]
- 2 edges to [[_COMMUNITY_Community 208]]
- 1 edge to [[_COMMUNITY_Community 44]]
- 1 edge to [[_COMMUNITY_Community 95]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 71]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 94]]
- 1 edge to [[_COMMUNITY_Community 565]]
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]

## Top bridge nodes
- [[check_black_swan_conditions()]] - degree 23, connects to 11 communities
- [[TestBlackSwanMode]] - degree 10, connects to 1 community
- [[dot-test_no_side_consecutive_losses_trigger_black_swan()]] - degree 4, connects to 1 community
- [[dot-test_no_side_consecutive_wins_not_black_swan()]] - degree 4, connects to 1 community
- [[TestCheckBlackSwanNoSide]] - degree 3, connects to 1 community