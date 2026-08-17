---
type: community
cohesion: 0.15
members: 18
---

# Community 196

**Cohesion:** 0.15 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-_open_trade()]] - code - tests/test_web_app.py
- [[dot-test_falls_back_to_sse_cache_when_live_fetch_raises()]] - code - tests/test_web_app.py
- [[dot-test_live_batch_fetch_is_used_when_it_succeeds()]] - code - tests/test_web_app.py
- [[dot-test_live_quote_takes_precedence_over_a_different_sse_value_for_the_same_ticker()]] - code - tests/test_web_app.py
- [[dot-test_malformed_live_price_degrades_to_no_quote_not_a_crash()]] - code - tests/test_web_app.py
- [[dot-test_multiple_open_positions_batch_into_one_call()]] - code - tests/test_web_app.py
- [[dot-test_no_open_positions_skips_the_live_call_entirely()]] - code - tests/test_web_app.py
- [[dot-test_ticker_missing_from_live_batch_falls_back_to_sse_cache()]] - code - tests/test_web_app.py
- [[A live market with an unparseable price field must not 500 the whole endpoint…]] - rationale - tests/test_web_app.py
- [[A networkauth failure on the live batch call must not break apitrades --…]] - rationale - tests/test_web_app.py
- [[A ticker requested in the batch but not returned (e.g. delisted) falls back…]] - rationale - tests/test_web_app.py
- [[A ticker the SSE cache never saw (e.g. its edge already decayed below zero, so…]] - rationale - tests/test_web_app.py
- [[L18015 apitrades' live-quote enrichment used to depend solely on the…]] - rationale - tests/test_web_app.py
- [[N open positions - ONE get_markets(tickers=...) call, not N -- the entire…]] - rationale - tests/test_web_app.py
- [[No open positions - no tickers to batch - get_markets is never even called…]] - rationale - tests/test_web_app.py
- [[PositionsTab component]] - code - weather app site V_3 (3)/src/tabs/PositionsTab.jsx
- [[TestApiTradesLiveQuoteEnrichment]] - code - tests/test_web_app.py
- [[When BOTH sources have data for the same ticker (not just when one is empty),…]] - rationale - tests/test_web_app.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_196
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 358]]
- 1 edge to [[_COMMUNITY_Community 115]]

## Top bridge nodes
- [[TestApiTradesLiveQuoteEnrichment]] - degree 13, connects to 2 communities