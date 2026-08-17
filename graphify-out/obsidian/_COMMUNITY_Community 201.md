---
type: community
cohesion: 0.12
members: 17
---

# Community 201

**Cohesion:** 0.12 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-test_dead_comment_subscribe_variable_never_existed()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_no_hardcoded_subscribe_comment_in_cron()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_no_start_with_empty_market_list()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_subscribe_after_start_raises()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_subscribe_called_before_start()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_subscribe_receives_market_tickers()]] - code - tests/test_phase2_batch_e.py
- [[If the market list is empty, subscribe is skipped but start still fires.]] - rationale - tests/test_phase2_batch_e.py
- [[P2-5 subscribe() must be called before start(), with real market tickers.]] - rationale - tests/test_phase2_batch_e.py
- [[Phase 2 Batch E regression tests P2-5 (WebSocket dead-code fix).]] - rationale - tests/test_phase2_batch_e.py
- [[TestWebSocketSubscribeOrder]] - code - tests/test_phase2_batch_e.py
- [[The dead ' _ws.subscribe(active_tickers)' comment must be gone.]] - rationale - tests/test_phase2_batch_e.py
- [[The subscribe call in cron must pass tickers from the market list, not an empty…]] - rationale - tests/test_phase2_batch_e.py
- [[active_tickers was never defined in cron — the old commented line could not…]] - rationale - tests/test_phase2_batch_e.py
- [[kalshi_ws.KalshiWebSocket]] - code - kalshi_ws.py
- [[subscribe() must precede start() — reversed order raises RuntimeError.]] - rationale - tests/test_phase2_batch_e.py
- [[subscribe() raises RuntimeError if called after start() — validates ordering…]] - rationale - tests/test_phase2_batch_e.py
- [[test_phase2_batch_e.py]] - code - tests/test_phase2_batch_e.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_201
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 227]]
- 2 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 31]]

## Top bridge nodes
- [[test_phase2_batch_e.py]] - degree 6, connects to 2 communities
- [[TestWebSocketSubscribeOrder]] - degree 9, connects to 1 community
- [[kalshi_ws.KalshiWebSocket]] - degree 2, connects to 1 community