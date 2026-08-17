---
type: community
cohesion: 0.25
members: 11
---

# Community 340

**Cohesion:** 0.25 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-_shifted_trade_and_analysis()]] - code - tests/test_early_exits.py
- [[dot-test_exit_price_uses_liquidation_not_midpoint_no_side()]] - code - tests/test_early_exits.py
- [[dot-test_exit_price_uses_liquidation_not_midpoint_yes_side()]] - code - tests/test_early_exits.py
- [[dot-test_skips_cycle_on_missing_quote_not_fallback_to_entry_price()]] - code - tests/test_early_exits.py
- [[dot-test_skips_cycle_when_no_side_liquidation_is_exactly_zero()]] - code - tests/test_early_exits.py
- [[A missinginvalid quote must skip this cycle (matching _check_live_model_exits'…]] - rationale - tests/test_early_exits.py
- [[TestEarlyExitPricingConvention]] - code - tests/test_early_exits.py
- [[_check_early_exits must price a model-exit at the realizable bidask…]] - rationale - tests/test_early_exits.py
- [[liquidation_price() returns 0.0 (NOT None) for a NO position when yes_ask=100c…]] - rationale - tests/test_early_exits.py
- [[yes_bid=20cyes_ask=40c liquidation (realizable) = 0.20 (the bid). The old…]] - rationale - tests/test_early_exits.py
- [[yes_bid=60cyes_ask=80c, held side NO liquidation (realizable) = 1 - yes_ask =…]] - rationale - tests/test_early_exits.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_340
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 104]]

## Top bridge nodes
- [[TestEarlyExitPricingConvention]] - degree 7, connects to 1 community
- [[dot-_shifted_trade_and_analysis()]] - degree 6, connects to 1 community