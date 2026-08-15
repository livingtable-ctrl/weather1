---
type: community
cohesion: 0.18
members: 16
---

# Community 208

**Cohesion:** 0.18 - loosely connected
**Members:** 16 nodes

## Members
- [[dot-test_mixed_sides_correct_win_count()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_consecutive_losses_trigger()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_losses_trigger_collapse()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_wins_not_counted_as_consec_losses()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_wins_not_counted_as_losses()]] - code - tests/test_alerts_side.py
- [[ALERT_HALT_THRESHOLDS]] - code - alerts.py
- [[Detect anomalous patterns in recent trade history. Returns a list of alert…]] - rationale - alerts.py
- [[P1-14 5 yes-wins + 5 no-wins = 100% win rate, no alert.]] - rationale - tests/test_alerts_side.py
- [[P1-14 6 consecutive NO-side losses (outcome='yes') must trigger alert.]] - rationale - tests/test_alerts_side.py
- [[P1-14 6 consecutive NO-side wins must not trigger consecutive-loss alert.]] - rationale - tests/test_alerts_side.py
- [[P1-14 8 losing NO-side trades (outcome='yes') must trigger collapse.]] - rationale - tests/test_alerts_side.py
- [[P1-14 8 winning NO-side trades must not trigger win-rate collapse.]] - rationale - tests/test_alerts_side.py
- [[TestCheckAnomaliesNoSideConsecutiveLoss]] - code - tests/test_alerts_side.py
- [[TestCheckAnomaliesNoSideWinRate]] - code - tests/test_alerts_side.py
- [[_make_trade()]] - code - tests/test_alerts_side.py
- [[check_anomalies()]] - code - alerts.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_208
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 194]]
- 3 edges to [[_COMMUNITY_Community 200]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 167]]
- 1 edge to [[_COMMUNITY_Community 94]]
- 1 edge to [[_COMMUNITY_Community 565]]

## Top bridge nodes
- [[check_anomalies()]] - degree 16, connects to 5 communities
- [[_make_trade()]] - degree 10, connects to 3 communities
- [[TestCheckAnomaliesNoSideWinRate]] - degree 4, connects to 1 community
- [[TestCheckAnomaliesNoSideConsecutiveLoss]] - degree 3, connects to 1 community