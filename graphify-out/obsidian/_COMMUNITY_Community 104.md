---
type: community
cohesion: 0.10
members: 27
---

# Community 104

**Cohesion:** 0.10 - loosely connected
**Members:** 27 nodes

## Members
- [[dot-test_default_threshold_does_not_trigger_same_shift()]] - code - tests/test_early_exits.py
- [[dot-test_edge_gone_threshold_is_negative()]] - code - tests/test_early_exits.py
- [[dot-test_get_weather_markets_called_once_for_multiple_trades()]] - code - tests/test_early_exits.py
- [[dot-test_get_weather_markets_not_called_when_no_open_trades()]] - code - tests/test_early_exits.py
- [[dot-test_lowering_threshold_triggers_previously_subthreshold_shift()]] - code - tests/test_early_exits.py
- [[dot-test_minimum_hold_time_prevents_early_exit()]] - code - tests/test_early_exits.py
- [[dot-test_model_flipped_requires_10pct_net_edge()]] - code - tests/test_early_exits.py
- [[dot-test_new_trade_not_exited_by_probability_shift()]] - code - tests/test_early_exits.py
- [[MODEL_EXIT_SHIFT_PP replaced a hardcoded 0.25 literal in both…]] - rationale - tests/test_early_exits.py
- [[P1-20 get_weather_markets must be called once regardless of N open trades.]] - rationale - tests/test_early_exits.py
- [[P1-20 no API call at all when there are no open trades.]] - rationale - tests/test_early_exits.py
- [[Sanity companion to the above the same 0.23 shift must NOT exit under the real…]] - rationale - tests/test_early_exits.py
- [[TestCheckEarlyExitsApiCallCount]] - code - tests/test_early_exits.py
- [[TestCheckEarlyExitsHoldTime]] - code - tests/test_early_exits.py
- [[TestCheckModelExitsThresholds]] - code - tests/test_early_exits.py
- [[TestModelExitShiftPpIsConfigurable]] - code - tests/test_early_exits.py
- [[Tests for early exit threshold and hold-time guards.]] - rationale - tests/test_early_exits.py
- [[_check_early_exits must not exit a trade entered less than 12 hours ago.]] - rationale - tests/test_early_exits.py
- [[_make_trade()]] - code - tests/test_early_exits.py
- [[check_model_exits model_flipped must require net_edge  -0.10 (not -0.05).]] - rationale - tests/test_early_exits.py
- [[check_model_exits must NOT exit a trade whose edge merely dropped from 8% to…]] - rationale - tests/test_early_exits.py
- [[check_model_exits must not exit a trade entered less than 12 hours ago.]] - rationale - tests/test_early_exits.py
- [[order_executor.MODEL_EXIT_SHIFT_PP]] - code - order_executor.py
- [[paper._passes_exit_gates]] - code - paper.py
- [[paper.check_breakeven_stops]] - code - paper.py
- [[test_early_exits.py]] - code - tests/test_early_exits.py
- [[utils.BREAKEVEN_TRIGGER_PCT]] - code - utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_104
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 0]]
- 3 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 340]]
- 2 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 161]]
- 1 edge to [[_COMMUNITY_Community 502]]
- 1 edge to [[_COMMUNITY_Community 12]]
- 1 edge to [[_COMMUNITY_Community 236]]

## Top bridge nodes
- [[test_early_exits.py]] - degree 19, connects to 7 communities
- [[_make_trade()]] - degree 9, connects to 1 community
- [[dot-test_edge_gone_threshold_is_negative()]] - degree 4, connects to 1 community
- [[dot-test_minimum_hold_time_prevents_early_exit()]] - degree 4, connects to 1 community
- [[dot-test_model_flipped_requires_10pct_net_edge()]] - degree 4, connects to 1 community