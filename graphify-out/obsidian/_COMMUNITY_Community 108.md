---
type: community
cohesion: 0.10
members: 26
---

# Community 108

**Cohesion:** 0.10 - loosely connected
**Members:** 26 nodes

## Members
- [[dot-test_brier_check_failure_fails_closed()]] - code - tests/test_alerts_side.py
- [[dot-test_days_out_none_does_not_crash()]] - code - tests/test_alerts_side.py
- [[dot-test_mixed_sides_correct_win_count()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_consecutive_losses_trigger()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_losses_trigger_collapse()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_wins_not_counted_as_consec_losses()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_wins_not_counted_as_losses()]] - code - tests/test_alerts_side.py
- [[A Brier-check exception (e.g. a locked tracker.db) must be treated as…]] - rationale - tests/test_alerts_side.py
- [[A trade record with days_out=None (key present, not absent) must not TypeError…]] - rationale - tests/test_alerts_side.py
- [[ALERT_HALT_THRESHOLDS]] - code - alerts.py
- [[Detect anomalous patterns in recent trade history. Returns a list of alert…]] - rationale - alerts.py
- [[P1-14 5 yes-wins + 5 no-wins = 100% win rate, no alert.]] - rationale - tests/test_alerts_side.py
- [[P1-14 6 consecutive NO-side losses (outcome='yes') must trigger alert.]] - rationale - tests/test_alerts_side.py
- [[P1-14 6 consecutive NO-side wins must not trigger consecutive-loss alert.]] - rationale - tests/test_alerts_side.py
- [[P1-14 8 losing NO-side trades (outcome='yes') must trigger collapse.]] - rationale - tests/test_alerts_side.py
- [[P1-14 8 winning NO-side trades must not trigger win-rate collapse.]] - rationale - tests/test_alerts_side.py
- [[Return True if the trade was a net loss (pnl  0). Breakeven (pnl == 0) is…]] - rationale - alerts.py
- [[Return the `limit` most recently settled trades, sorted by settled_at. Pass…]] - rationale - alerts.py
- [[Return the exact win-rate window check_anomalies()'s WIN RATE COLLAPSE gate…]] - rationale - alerts.py
- [[TestCheckAnomaliesNoSideConsecutiveLoss]] - code - tests/test_alerts_side.py
- [[TestCheckAnomaliesNoSideWinRate]] - code - tests/test_alerts_side.py
- [[_make_trade()_1]] - code - tests/test_alerts_side.py
- [[_recent_settled()]] - code - alerts.py
- [[_trade_lost()]] - code - alerts.py
- [[check_anomalies()]] - code - alerts.py
- [[get_win_rate_window()]] - code - alerts.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_108
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Community 359]]
- 6 edges to [[_COMMUNITY_Community 170]]
- 4 edges to [[_COMMUNITY_Community 8]]
- 3 edges to [[_COMMUNITY_Community 274]]
- 3 edges to [[_COMMUNITY_Community 142]]

## Top bridge nodes
- [[check_anomalies()]] - degree 16, connects to 4 communities
- [[_trade_lost()]] - degree 6, connects to 3 communities
- [[_make_trade()_1]] - degree 10, connects to 2 communities
- [[get_win_rate_window()]] - degree 6, connects to 2 communities
- [[_recent_settled()]] - degree 5, connects to 2 communities