---
type: community
cohesion: 0.17
members: 15
---

# Community 227

**Cohesion:** 0.17 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-test_cache_missing_returns_empty()]] - code - tests/test_kalshi_ws.py
- [[dot-test_delta_message_does_not_feed_flash_crash_breaker()]] - code - tests/test_kalshi_ws.py
- [[dot-test_orderbook_delta_does_not_refresh_mid_price_timestamp()]] - code - tests/test_kalshi_ws.py
- [[dot-test_ticker_message_feeds_flash_crash_breaker()]] - code - tests/test_kalshi_ws.py
- [[dot-test_update_and_read_cache()]] - code - tests/test_kalshi_ws.py
- [[2026-07-12 a 'ticker'-type message must feed flash_crash_cb.check() on every…]] - rationale - tests/test_kalshi_ws.py
- [[A delta message must not bump `ts` (or touch mid_price) -- only a ticker-type…]] - rationale - tests/test_kalshi_ws.py
- [[An orderbook_delta carries no real mid_price -- it must not reach…]] - rationale - tests/test_kalshi_ws.py
- [[Read the current order book cache from disk.]] - rationale - kalshi_ws.py
- [[TestOrderbookCache]] - code - tests/test_kalshi_ws.py
- [[Update in-memory and on-disk cache for a ticker.]] - rationale - kalshi_ws.py
- [[read_orderbook_cache returns {} if file does not exist.]] - rationale - tests/test_kalshi_ws.py
- [[read_orderbook_cache()]] - code - kalshi_ws.py
- [[update_orderbook_cache writes and read_orderbook_cache reads back.]] - rationale - tests/test_kalshi_ws.py
- [[update_orderbook_cache()]] - code - kalshi_ws.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_227
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 198]]
- 3 edges to [[_COMMUNITY_Community 130]]
- 2 edges to [[_COMMUNITY_Community 111]]
- 1 edge to [[_COMMUNITY_Community 95]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Community 40]]

## Top bridge nodes
- [[update_orderbook_cache()]] - degree 13, connects to 6 communities
- [[read_orderbook_cache()]] - degree 6, connects to 2 communities
- [[TestOrderbookCache]] - degree 6, connects to 1 community