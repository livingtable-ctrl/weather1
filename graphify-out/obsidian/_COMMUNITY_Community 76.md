---
type: community
cohesion: 0.12
members: 32
---

# Community 76

**Cohesion:** 0.12 - loosely connected
**Members:** 32 nodes

## Members
- [[dot-test_market_dict_feeds_a_real_price_to_the_breaker()]] - code - tests/test_trade_validation.py
- [[dot-test_no_market_dict_does_not_crash()]] - code - tests/test_trade_validation.py
- [[dot-test_ws_cached_price_is_preferred_over_market_dict()]] - code - tests/test_trade_validation.py
- [[A fresher WebSocket-cached mid-price should win over the REST-derived one.]] - rationale - tests/test_trade_validation.py
- [[Both ci_adjusted_kelly and fee_adjusted_kelly present but None must not raise…]] - rationale - tests/test_trade_validation.py
- [[Callers that genuinely have no market dict (market=None, the default) must not…]] - rationale - tests/test_trade_validation.py
- [[F3 the flash-crash circuit breaker read opp.get(yes_bid)opp.get(yes_ask)…]] - rationale - tests/test_trade_validation.py
- [[Missing data_fetched_at should not be treated as stale.]] - rationale - tests/test_trade_validation.py
- [[Pre-execution validation gate for auto-placed trades (P1.1+P1.2). Returns (ok,…]] - rationale - order_executor.py
- [[TestFlashCrashPriceFeed]] - code - tests/test_trade_validation.py
- [[Tests for P1.1+P1.2 — _validate_trade_opportunity() pre-trade gate.]] - rationale - tests/test_trade_validation.py
- [[Without ensemble_spread key, fall back to flat PAPER_MIN_EDGE threshold (0.05).]] - rationale - tests/test_trade_validation.py
- [[_opp()]] - code - tests/test_trade_validation.py
- [[_validate_trade_opportunity()]] - code - order_executor.py
- [[ci_adjusted_kelly present but None must fall back to fee_adjusted_kelly rather…]] - rationale - tests/test_trade_validation.py
- [[ensemble_spread=0.20 (LOW tier) requires edge = 0.10; edge=0.08 should be…]] - rationale - tests/test_trade_validation.py
- [[oppedge present but None (as opposed to simply absent) must not raise…]] - rationale - tests/test_trade_validation.py
- [[oppnet_edge present but None must not raise TypeError from `edge = 0` —…]] - rationale - tests/test_trade_validation.py
- [[test_trade_validation.py]] - code - tests/test_trade_validation.py
- [[test_validate_accepts_good_opportunity()]] - code - tests/test_trade_validation.py
- [[test_validate_low_spread_tier_rejects_edge_below_threshold()]] - code - tests/test_trade_validation.py
- [[test_validate_missing_ensemble_spread_uses_flat_threshold()]] - code - tests/test_trade_validation.py
- [[test_validate_no_fetched_at_accepted()]] - code - tests/test_trade_validation.py
- [[test_validate_none_edge_value_does_not_crash()]] - code - tests/test_trade_validation.py
- [[test_validate_none_kelly_values_both_missing_rejects_without_crash()]] - code - tests/test_trade_validation.py
- [[test_validate_none_kelly_values_fall_back_then_do_not_crash()]] - code - tests/test_trade_validation.py
- [[test_validate_none_net_edge_value_does_not_crash()]] - code - tests/test_trade_validation.py
- [[test_validate_rejects_missing_ticker()]] - code - tests/test_trade_validation.py
- [[test_validate_rejects_negative_edge()]] - code - tests/test_trade_validation.py
- [[test_validate_rejects_stale_data()]] - code - tests/test_trade_validation.py
- [[test_validate_rejects_zero_edge()]] - code - tests/test_trade_validation.py
- [[test_validate_rejects_zero_kelly()]] - code - tests/test_trade_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_76
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 64]]
- 1 edge to [[_COMMUNITY_Community 12]]
- 1 edge to [[_COMMUNITY_Community 163]]
- 1 edge to [[_COMMUNITY_Community 245]]
- 1 edge to [[_COMMUNITY_Community 25]]
- 1 edge to [[_COMMUNITY_Community 30]]
- 1 edge to [[_COMMUNITY_Community 305]]
- 1 edge to [[_COMMUNITY_Community 44]]
- 1 edge to [[_COMMUNITY_Community 672]]
- 1 edge to [[_COMMUNITY_Community 74]]
- 1 edge to [[_COMMUNITY_Community 81]]
- 1 edge to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 86]]

## Top bridge nodes
- [[_validate_trade_opportunity()]] - degree 30, connects to 12 communities
- [[test_trade_validation.py]] - degree 20, connects to 2 communities
- [[_opp()]] - degree 19, connects to 2 communities