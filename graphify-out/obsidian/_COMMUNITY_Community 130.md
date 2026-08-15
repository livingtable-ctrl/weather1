---
type: community
cohesion: 0.09
members: 23
---

# Community 130

**Cohesion:** 0.09 - loosely connected
**Members:** 23 nodes

## Members
- [[dot-test_fresh_entry_returns_price()]] - code - tests/test_kalshi_ws.py
- [[dot-test_get_ws_health_initially_not_alive()]] - code - tests/test_kalshi_ws.py
- [[dot-test_get_ws_health_stale_flag()]] - code - tests/test_kalshi_ws.py
- [[dot-test_missing_ts_returns_none()]] - code - tests/test_kalshi_ws.py
- [[dot-test_stale_entry_returns_none()]] - code - tests/test_kalshi_ws.py
- [[dot-test_stop_cancels_task_and_thread_exits_cleanly()]] - code - tests/test_kalshi_ws.py
- [[dot-test_subscribe_message_structure()]] - code - tests/test_kalshi_ws.py
- [[An entry timestamped 15 min ago is returned normally.]] - rationale - tests/test_kalshi_ws.py
- [[An entry timestamped WS_CACHE_TTL_SECS ago returns None.]] - rationale - tests/test_kalshi_ws.py
- [[An entry with no ts field is treated as stale.]] - rationale - tests/test_kalshi_ws.py
- [[Build a Kalshi WebSocket subscribe command payload.]] - rationale - kalshi_ws.py
- [[Fresh import ws not alive, no messages recorded.]] - rationale - tests/test_kalshi_ws.py
- [[KalshiWebSocket class  get_ws_health()]] - code - kalshi_ws.py
- [[TestBuildSubscribeMessage]] - code - tests/test_kalshi_ws.py
- [[TestCacheStaleness]] - code - tests/test_kalshi_ws.py
- [[TestKalshiWebSocketLifecycle]] - code - tests/test_kalshi_ws.py
- [[TestWsHealth]] - code - tests/test_kalshi_ws.py
- [[Tests for Kalshi WebSocket client.]] - rationale - tests/test_kalshi_ws.py
- [[build_subscribe_message returns a valid Kalshi WS subscribe payload.]] - rationale - tests/test_kalshi_ws.py
- [[build_subscribe_message()]] - code - kalshi_ws.py
- [[stale=True when idle  WS_CACHE_TTL_SECS.]] - rationale - tests/test_kalshi_ws.py
- [[stop() must cancel the running task (not just stop the loop) so the async-with-…]] - rationale - tests/test_kalshi_ws.py
- [[test_kalshi_ws.py]] - code - tests/test_kalshi_ws.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_130
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 227]]
- 2 edges to [[_COMMUNITY_Community 352]]
- 2 edges to [[_COMMUNITY_Community 198]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]

## Top bridge nodes
- [[test_kalshi_ws.py]] - degree 13, connects to 3 communities
- [[build_subscribe_message()]] - degree 5, connects to 1 community