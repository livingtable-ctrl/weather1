---
type: community
cohesion: 0.17
members: 13
---

# Community 272

**Cohesion:** 0.17 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-test_get_weather_markets_not_called_when_no_open_trades()]] - code - tests/test_early_exits.py
- [[dot-test_new_trade_not_exited_by_probability_shift()]] - code - tests/test_early_exits.py
- [[P1-20 no API call at all when there are no open trades.]] - rationale - tests/test_early_exits.py
- [[TestCheckEarlyExitsApiCallCount]] - code - tests/test_early_exits.py
- [[TestCheckEarlyExitsHoldTime]] - code - tests/test_early_exits.py
- [[Tests for early exit threshold and hold-time guards.]] - rationale - tests/test_early_exits.py
- [[_check_early_exits must not exit a trade entered less than 12 hours ago.]] - rationale - tests/test_early_exits.py
- [[main._check_early_exits]] - code - main.py
- [[order_executor.MODEL_EXIT_SHIFT_PP]] - code - order_executor.py
- [[paper._passes_exit_gates]] - code - paper.py
- [[paper.check_breakeven_stops]] - code - paper.py
- [[test_early_exits.py]] - code - tests/test_early_exits.py
- [[utils.BREAKEVEN_TRIGGER_PCT]] - code - utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_272
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 231]]
- 3 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Community 145]]
- 2 edges to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 463]]
- 1 edge to [[_COMMUNITY_Community 333]]
- 1 edge to [[_COMMUNITY_Community 158]]
- 1 edge to [[_COMMUNITY_Community 235]]

## Top bridge nodes
- [[test_early_exits.py]] - degree 19, connects to 8 communities
- [[paper._passes_exit_gates]] - degree 4, connects to 2 communities
- [[paper.check_breakeven_stops]] - degree 3, connects to 1 community
- [[TestCheckEarlyExitsApiCallCount]] - degree 3, connects to 1 community
- [[dot-test_new_trade_not_exited_by_probability_shift()]] - degree 3, connects to 1 community