---
type: community
cohesion: 0.13
members: 29
---

# Community 85

**Cohesion:** 0.13 - loosely connected
**Members:** 29 nodes

## Members
- [[dot-test_live_placement_appends_to_open_trades_list()]] - code - tests/test_live_execution.py
- [[Both ci_adjusted_kelly and fee_adjusted_kelly present but None must not raise…]] - rationale - tests/test_trade_validation.py
- [[Missing data_fetched_at should not be treated as stale.]] - rationale - tests/test_trade_validation.py
- [[Pre-execution validation gate for auto-placed trades (P1.1+P1.2). Returns (ok,…]] - rationale - order_executor.py
- [[Tests for P1.1+P1.2 — _validate_trade_opportunity() pre-trade gate.]] - rationale - tests/test_trade_validation.py
- [[Without ensemble_spread key, fall back to flat PAPER_MIN_EDGE threshold (0.05).]] - rationale - tests/test_trade_validation.py
- [[_opp()]] - code - tests/test_trade_validation.py
- [[_validate_trade_opportunity()]] - code - order_executor.py
- [[_validate_trade_opportunity() (as imported from main)]] - code - main.py
- [[ci_adjusted_kelly present but None must fall back to fee_adjusted_kelly rather…]] - rationale - tests/test_trade_validation.py
- [[circuit_breaker.py_2]] - code - circuit_breaker.py
- [[ensemble_spread=0.20 (LOW tier) requires edge = 0.10; edge=0.08 should be…]] - rationale - tests/test_trade_validation.py
- [[oppedge present but None (as opposed to simply absent) must not raise…]] - rationale - tests/test_trade_validation.py
- [[oppnet_edge present but None must not raise TypeError from `edge = 0` —…]] - rationale - tests/test_trade_validation.py
- [[system_health.py_1]] - code - system_health.py
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
TABLE source_file, type FROM #community/Community_85
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 488]]
- 3 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 95]]
- 1 edge to [[_COMMUNITY_Community 198]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 67]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 296]]
- 1 edge to [[_COMMUNITY_Community 252]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 248]]
- 1 edge to [[_COMMUNITY_Community 42]]
- 1 edge to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 596]]
- 1 edge to [[_COMMUNITY_Community 347]]

## Top bridge nodes
- [[_validate_trade_opportunity()]] - degree 32, connects to 14 communities
- [[test_trade_validation.py]] - degree 21, connects to 3 communities
- [[_opp()]] - degree 19, connects to 2 communities
- [[dot-test_live_placement_appends_to_open_trades_list()]] - degree 2, connects to 1 community