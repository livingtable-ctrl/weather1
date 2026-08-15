---
type: community
cohesion: 0.29
members: 7
---

# Community 488

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_market_dict_feeds_a_real_price_to_the_breaker()]] - code - tests/test_trade_validation.py
- [[dot-test_no_market_dict_does_not_crash()]] - code - tests/test_trade_validation.py
- [[dot-test_ws_cached_price_is_preferred_over_market_dict()]] - code - tests/test_trade_validation.py
- [[A fresher WebSocket-cached mid-price should win over the REST-derived one.]] - rationale - tests/test_trade_validation.py
- [[Callers that genuinely have no market dict (market=None, the default) must not…]] - rationale - tests/test_trade_validation.py
- [[F3 the flash-crash circuit breaker read opp.get(yes_bid)opp.get(yes_ask)…]] - rationale - tests/test_trade_validation.py
- [[TestFlashCrashPriceFeed]] - code - tests/test_trade_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_488
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 85]]

## Top bridge nodes
- [[TestFlashCrashPriceFeed]] - degree 5, connects to 1 community
- [[dot-test_no_market_dict_does_not_crash()]] - degree 4, connects to 1 community
- [[dot-test_ws_cached_price_is_preferred_over_market_dict()]] - degree 4, connects to 1 community
- [[dot-test_market_dict_feeds_a_real_price_to_the_breaker()]] - degree 3, connects to 1 community