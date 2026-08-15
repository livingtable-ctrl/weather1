---
type: community
cohesion: 0.16
members: 17
---

# Community 198

**Cohesion:** 0.16 - loosely connected
**Members:** 17 nodes

## Members
- [[Async WebSocket listener. Connects, authenticates, subscribes to tickers, and…]] - rationale - kalshi_ws.py
- [[Kalshi WebSocket client — real-time order book and ticker data. Runs as a…]] - rationale - kalshi_ws.py
- [[Return the cached ticker-type message for a ticker if fresh, else None.…]] - rationale - kalshi_ws.py
- [[Return the cached mid-price for a ticker, or None if not cached or stale.]] - rationale - kalshi_ws.py
- [[Return {yes_bid, yes_ask, mid_price} for a ticker from the live WS…]] - rationale - kalshi_ws.py
- [[_get_fresh_ticker_entry()]] - code - kalshi_ws.py
- [[_is_fresh()]] - code - kalshi_ws.py
- [[_record_ws_message()]] - code - kalshi_ws.py
- [[_set_ws_alive()]] - code - kalshi_ws.py
- [[_ws_listener()]] - code - kalshi_ws.py
- [[_ws_listener() Per-Message Parse Error at DEBUG (610)]] - document - docs/grade_audit/outputs/kalshi_ws.py.md
- [[get_cached_book()]] - code - kalshi_ws.py
- [[get_cached_mid_price()]] - code - kalshi_ws.py
- [[kalshi_ws.py]] - code - kalshi_ws.py
- [[kalshi_ws.py File Grade median 710, 3 RF1 violations]] - document - docs/grade_audit/outputs/kalshi_ws.py.md
- [[kalshi_ws.py Grade Audit]] - document - docs/grade_audit/outputs/kalshi_ws.py.md
- [[read_orderbook_cache() RF1 Zero Log on Exception (510)]] - document - docs/grade_audit/outputs/kalshi_ws.py.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_198
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 227]]
- 3 edges to [[_COMMUNITY_Community 195]]
- 2 edges to [[_COMMUNITY_Community 245]]
- 2 edges to [[_COMMUNITY_Community 130]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 352]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 111]]
- 1 edge to [[_COMMUNITY_Community 85]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 32]]

## Top bridge nodes
- [[kalshi_ws.py]] - degree 23, connects to 8 communities
- [[_ws_listener()]] - degree 9, connects to 5 communities
- [[get_cached_book()]] - degree 5, connects to 2 communities
- [[get_cached_mid_price()]] - degree 5, connects to 2 communities
- [[_get_fresh_ticker_entry()]] - degree 6, connects to 1 community