---
type: community
cohesion: 0.16
members: 17
---

# Community 194

**Cohesion:** 0.16 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-test_missing_side_defaults_to_yes()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_no_outcome_is_win()]] - code - tests/test_alerts_side.py
- [[dot-test_no_side_yes_outcome_is_loss()]] - code - tests/test_alerts_side.py
- [[dot-test_yes_side_no_outcome_is_loss()]] - code - tests/test_alerts_side.py
- [[dot-test_yes_side_yes_outcome_is_win()]] - code - tests/test_alerts_side.py
- [[apianomaly-status endpoint]] - code - web_app.py
- [[Return True if the trade was a net loss (pnl  0). Breakeven (pnl == 0) is…]] - rationale - alerts.py
- [[Return True if the trade was profitable (pnl  0). Matches paper.py's…]] - rationale - alerts.py
- [[Return the `limit` most recently settled trades, sorted by settled_at. Pass…]] - rationale - alerts.py
- [[Return the exact win-rate window check_anomalies()'s WIN RATE COLLAPSE gate…]] - rationale - alerts.py
- [[TestTradeWon]] - code - tests/test_alerts_side.py
- [[Tests for P1-14 — alerts winloss side confusion fix.]] - rationale - tests/test_alerts_side.py
- [[_recent_settled()]] - code - alerts.py
- [[_trade_lost()]] - code - alerts.py
- [[_trade_won()]] - code - alerts.py
- [[get_win_rate_window()]] - code - alerts.py
- [[test_alerts_side.py]] - code - tests/test_alerts_side.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_194
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 208]]
- 4 edges to [[_COMMUNITY_Community 167]]
- 4 edges to [[_COMMUNITY_Community 94]]
- 1 edge to [[_COMMUNITY_Community 200]]
- 1 edge to [[_COMMUNITY_Community 223]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 109]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[test_alerts_side.py]] - degree 15, connects to 8 communities
- [[_trade_lost()]] - degree 6, connects to 3 communities
- [[_recent_settled()]] - degree 5, connects to 3 communities
- [[get_win_rate_window()]] - degree 7, connects to 2 communities
- [[_trade_won()]] - degree 10, connects to 1 community