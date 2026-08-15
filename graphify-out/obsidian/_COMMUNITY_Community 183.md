---
type: community
cohesion: 0.15
members: 18
---

# Community 183

**Cohesion:** 0.15 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-test_client_error_falls_back_to_zero()]] - code - tests/test_prelog.py
- [[dot-test_explicit_live_config_is_respected()]] - code - tests/test_prelog.py
- [[dot-test_fetches_real_balance_from_client()]] - code - tests/test_prelog.py
- [[dot-test_missing_balance_key_falls_back_to_zero()]] - code - tests/test_prelog.py
- [[dot-test_none_live_config_loads_real_config()]] - code - tests/test_prelog.py
- [[0.0 signals 'use the paper balance' to the caller — must not raise or block…]] - rationale - tests/test_prelog.py
- [[F2 micro-live's daily-loss limit was silently disabled because it only ever…]] - rationale - tests/test_prelog.py
- [[F4 live_config never has a balance key, so the CR-4 override for live Kelly…]] - rationale - tests/test_prelog.py
- [[Fetch the real Kalshi balance (dollars) for live Kelly sizing. F4 live_config…]] - rationale - order_executor.py
- [[P0-6 execution log entry must be written BEFORE the live order is placed.]] - rationale - tests/test_prelog.py
- [[Resolve the config micro-live enforces its daily-loss limit against. F2 micro-…]] - rationale - order_executor.py
- [[TestResolveLiveBalance]] - code - tests/test_prelog.py
- [[TestResolveMicroLiveConfig]] - code - tests/test_prelog.py
- [[_place_live_order()_poll_pending_orders()_auto_place_trades()]] - code - main.py
- [[_resolve_live_balance()]] - code - order_executor.py
- [[_resolve_micro_live_config()]] - code - order_executor.py
- [[execution_log.py_1]] - code - execution_log.py
- [[test_prelog.py]] - code - tests/test_prelog.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_183
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 40]]
- 3 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 1 edge to [[_COMMUNITY_Community 225]]
- 1 edge to [[_COMMUNITY_Community 111]]
- 1 edge to [[_COMMUNITY_Community 219]]

## Top bridge nodes
- [[_place_live_order()_poll_pending_orders()_auto_place_trades()]] - degree 7, connects to 5 communities
- [[_resolve_micro_live_config()]] - degree 8, connects to 4 communities
- [[_resolve_live_balance()]] - degree 8, connects to 3 communities
- [[test_prelog.py]] - degree 9, connects to 2 communities
- [[execution_log.py_1]] - degree 4, connects to 2 communities