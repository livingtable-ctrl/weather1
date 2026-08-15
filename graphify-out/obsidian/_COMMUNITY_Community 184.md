---
type: community
cohesion: 0.13
members: 18
---

# Community 184

**Cohesion:** 0.13 - loosely connected
**Members:** 18 nodes

## Members
- [[A real client.get_market() response has no series_ticker field at all…]] - rationale - tracker.py
- [[Bulk-insert OHLC candlesticks for a market. Idempotent — re-running for the…]] - rationale - tracker.py
- [[Bulk-insert public trade-flow history for a market. Idempotent -- re-running…]] - rationale - tracker.py
- [[Check settled markets in the DB against Kalshi and record outcomes. Returns…]] - rationale - tracker.py
- [[One-off recovery pass for price_history rows lost to the real series_ticker bug…]] - rationale - tracker.py
- [[Parse a FixedPointCount string (e.g. 10.00 contracts) into a float.]] - rationale - tracker.py
- [[Parse a nullable fixed-point-dollar string (e.g. 0.55) from a candlestick…]] - rationale - tracker.py
- [[Record the outcome for a settled trade. F4 Uses append-only writes to avoid…]] - rationale - feature_importance.py
- [[Record whether a market settled YES or NO. Returns True if newly recorded,…]] - rationale - tracker.py
- [[_candle_dollars()]] - code - tracker.py
- [[_derive_series_ticker()]] - code - tracker.py
- [[_fp_count()]] - code - tracker.py
- [[backfill_price_history()]] - code - tracker.py
- [[log_outcome()]] - code - tracker.py
- [[log_price_candles()]] - code - tracker.py
- [[log_trades()]] - code - tracker.py
- [[sync_outcomes()]] - code - tracker.py
- [[update_outcome()]] - code - feature_importance.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_184
SORT file.name ASC
```

## Connections to other communities
- 15 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 11 edges to [[_COMMUNITY_Black Swan Halt State]]
- 6 edges to [[_COMMUNITY_Community 36]]
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 78]]
- 1 edge to [[_COMMUNITY_Community 162]]
- 1 edge to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 1 edge to [[_COMMUNITY_Community 96]]
- 1 edge to [[_COMMUNITY_Community 52]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[sync_outcomes()]] - degree 24, connects to 8 communities
- [[backfill_price_history()]] - degree 9, connects to 4 communities
- [[log_outcome()]] - degree 7, connects to 3 communities
- [[log_price_candles()]] - degree 8, connects to 2 communities
- [[log_trades()]] - degree 7, connects to 2 communities