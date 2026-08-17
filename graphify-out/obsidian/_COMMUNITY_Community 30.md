---
type: community
cohesion: 0.06
members: 52
---

# Community 30

**Cohesion:** 0.06 - loosely connected
**Members:** 52 nodes

## Members
- [[dot-test_cache_missing_returns_empty()]] - code - tests/test_kalshi_ws.py
- [[dot-test_delta_message_does_not_feed_flash_crash_breaker()]] - code - tests/test_kalshi_ws.py
- [[dot-test_orderbook_delta_does_not_refresh_mid_price_timestamp()]] - code - tests/test_kalshi_ws.py
- [[dot-test_parse_empty_msg_returns_none()]] - code - tests/test_kalshi_ws.py
- [[dot-test_parse_snapshot_message()]] - code - tests/test_kalshi_ws.py
- [[dot-test_parse_ticker_message()]] - code - tests/test_kalshi_ws.py
- [[dot-test_parse_unknown_type_returns_none()]] - code - tests/test_kalshi_ws.py
- [[dot-test_stop_cancels_task_and_thread_exits_cleanly()]] - code - tests/test_kalshi_ws.py
- [[dot-test_subscribe_message_structure()]] - code - tests/test_kalshi_ws.py
- [[dot-test_ticker_message_feeds_flash_crash_breaker()]] - code - tests/test_kalshi_ws.py
- [[dot-test_update_and_read_cache()]] - code - tests/test_kalshi_ws.py
- [[2026-07-12 a 'ticker'-type message must feed flash_crash_cb.check() on every…]] - rationale - tests/test_kalshi_ws.py
- [[A delta message must not bump `ts` (or touch mid_price) -- only a ticker-type…]] - rationale - tests/test_kalshi_ws.py
- [[An orderbook_delta carries no real mid_price -- it must not reach…]] - rationale - tests/test_kalshi_ws.py
- [[Async WebSocket listener. Connects, authenticates, subscribes to tickers, and…]] - rationale - kalshi_ws.py
- [[Build a Kalshi WebSocket subscribe command payload.]] - rationale - kalshi_ws.py
- [[Kalshi WebSocket client — real-time order book and ticker data. Runs as a…]] - rationale - kalshi_ws.py
- [[KalshiWebSocket class  get_ws_health()]] - code - kalshi_ws.py
- [[Parse a Kalshi WebSocket message into a normalized dict. Returns None for…]] - rationale - kalshi_ws.py
- [[Read the current order book cache from disk.]] - rationale - kalshi_ws.py
- [[Return the cached ticker-type message for a ticker if fresh, else None.…]] - rationale - kalshi_ws.py
- [[Return the cached mid-price for a ticker, or None if not cached or stale.]] - rationale - kalshi_ws.py
- [[Return {yes_bid, yes_ask, mid_price} for a ticker from the live WS…]] - rationale - kalshi_ws.py
- [[TestBuildSubscribeMessage]] - code - tests/test_kalshi_ws.py
- [[TestKalshiWebSocketLifecycle]] - code - tests/test_kalshi_ws.py
- [[TestOrderbookCache]] - code - tests/test_kalshi_ws.py
- [[TestParseOrderbookMessage]] - code - tests/test_kalshi_ws.py
- [[Tests for Kalshi WebSocket client.]] - rationale - tests/test_kalshi_ws.py
- [[Unknown message types return None (ignored).]] - rationale - tests/test_kalshi_ws.py
- [[Update in-memory and on-disk cache for a ticker.]] - rationale - kalshi_ws.py
- [[_get_fresh_ticker_entry()]] - code - kalshi_ws.py
- [[_is_fresh()]] - code - kalshi_ws.py
- [[_record_ws_message()]] - code - kalshi_ws.py
- [[_set_ws_alive()]] - code - kalshi_ws.py
- [[_ws_listener()]] - code - kalshi_ws.py
- [[build_subscribe_message returns a valid Kalshi WS subscribe payload.]] - rationale - tests/test_kalshi_ws.py
- [[build_subscribe_message()]] - code - kalshi_ws.py
- [[flash_crash_cb (FlashCrashCB instance)]] - code - circuit_breaker.py
- [[get_cached_book()]] - code - kalshi_ws.py
- [[get_cached_mid_price()]] - code - kalshi_ws.py
- [[kalshi_ws.py]] - code - kalshi_ws.py
- [[kalshi_ws.py File Grade median 710, 3 RF1 violations]] - document - docs/grade_audit/outputs/kalshi_ws.py.md
- [[kalshi_ws.py Grade Audit]] - document - docs/grade_audit/outputs/kalshi_ws.py.md
- [[parse_message extracts mid-price from ticker message.]] - rationale - tests/test_kalshi_ws.py
- [[parse_message returns structured snapshot from orderbook_snapshot type.]] - rationale - tests/test_kalshi_ws.py
- [[parse_message()]] - code - kalshi_ws.py
- [[read_orderbook_cache returns {} if file does not exist.]] - rationale - tests/test_kalshi_ws.py
- [[read_orderbook_cache()]] - code - kalshi_ws.py
- [[stop() must cancel the running task (not just stop the loop) so the async-with-…]] - rationale - tests/test_kalshi_ws.py
- [[test_kalshi_ws.py]] - code - tests/test_kalshi_ws.py
- [[update_orderbook_cache writes and read_orderbook_cache reads back.]] - rationale - tests/test_kalshi_ws.py
- [[update_orderbook_cache()]] - code - kalshi_ws.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_30
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 1]]
- 3 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 227]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 406]]
- 2 edges to [[_COMMUNITY_Community 171]]
- 1 edge to [[_COMMUNITY_Community 507]]
- 1 edge to [[_COMMUNITY_Community 618]]
- 1 edge to [[_COMMUNITY_Community 64]]
- 1 edge to [[_COMMUNITY_Community 76]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 12]]
- 1 edge to [[_COMMUNITY_Community 148]]
- 1 edge to [[_COMMUNITY_Community 7]]

## Top bridge nodes
- [[kalshi_ws.py]] - degree 27, connects to 6 communities
- [[update_orderbook_cache()]] - degree 13, connects to 4 communities
- [[test_kalshi_ws.py]] - degree 17, connects to 3 communities
- [[_ws_listener()]] - degree 9, connects to 2 communities
- [[get_cached_book()]] - degree 5, connects to 2 communities