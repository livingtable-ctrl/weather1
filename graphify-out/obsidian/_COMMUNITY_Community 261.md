---
type: community
cohesion: 0.14
members: 14
---

# Community 261

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_dead_comment_subscribe_variable_never_existed()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_no_hardcoded_subscribe_comment_in_cron()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_no_start_with_empty_market_list()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_subscribe_after_start_raises()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_subscribe_called_before_start()]] - code - tests/test_phase2_batch_e.py
- [[dot-test_subscribe_receives_market_tickers()]] - code - tests/test_phase2_batch_e.py
- [[If the market list is empty, subscribe is skipped but start still fires.]] - rationale - tests/test_phase2_batch_e.py
- [[P2-5 subscribe() must be called before start(), with real market tickers.]] - rationale - tests/test_phase2_batch_e.py
- [[TestWebSocketSubscribeOrder]] - code - tests/test_phase2_batch_e.py
- [[The dead ' _ws.subscribe(active_tickers)' comment must be gone.]] - rationale - tests/test_phase2_batch_e.py
- [[The subscribe call in cron must pass tickers from the market list, not an empty…]] - rationale - tests/test_phase2_batch_e.py
- [[active_tickers was never defined in cron — the old commented line could not…]] - rationale - tests/test_phase2_batch_e.py
- [[subscribe() must precede start() — reversed order raises RuntimeError.]] - rationale - tests/test_phase2_batch_e.py
- [[subscribe() raises RuntimeError if called after start() — validates ordering…]] - rationale - tests/test_phase2_batch_e.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_261
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 245]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[TestWebSocketSubscribeOrder]] - degree 9, connects to 2 communities