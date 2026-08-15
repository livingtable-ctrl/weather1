---
type: community
cohesion: 0.33
members: 6
---

# Community 500

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[Live Order Executor Module]] - code - order_executor.py
- [[Record a micro live fill for slippage tracking (P10.4).]] - rationale - tracker.py
- [[_auto_place_trades Function]] - code - order_executor.py
- [[log_live_fill()]] - code - tracker.py
- [[portfolio_var Function]] - code - monte_carlo.py
- [[update_orderbook_cache Function]] - code - kalshi_ws.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_500
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Community 36]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 568]]

## Top bridge nodes
- [[log_live_fill()]] - degree 7, connects to 4 communities
- [[portfolio_var Function]] - degree 3, connects to 1 community
- [[_auto_place_trades Function]] - degree 3, connects to 1 community