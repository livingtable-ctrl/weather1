---
type: community
cohesion: 0.16
members: 15
---

# Community 231

**Cohesion:** 0.16 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-test_default_threshold_does_not_trigger_same_shift()]] - code - tests/test_early_exits.py
- [[dot-test_edge_gone_threshold_is_negative()]] - code - tests/test_early_exits.py
- [[dot-test_get_weather_markets_called_once_for_multiple_trades()]] - code - tests/test_early_exits.py
- [[dot-test_lowering_threshold_triggers_previously_subthreshold_shift()]] - code - tests/test_early_exits.py
- [[dot-test_minimum_hold_time_prevents_early_exit()]] - code - tests/test_early_exits.py
- [[dot-test_model_flipped_requires_10pct_net_edge()]] - code - tests/test_early_exits.py
- [[MODEL_EXIT_SHIFT_PP replaced a hardcoded 0.25 literal in both…]] - rationale - tests/test_early_exits.py
- [[P1-20 get_weather_markets must be called once regardless of N open trades.]] - rationale - tests/test_early_exits.py
- [[Sanity companion to the above the same 0.23 shift must NOT exit under the real…]] - rationale - tests/test_early_exits.py
- [[TestCheckModelExitsThresholds]] - code - tests/test_early_exits.py
- [[TestModelExitShiftPpIsConfigurable]] - code - tests/test_early_exits.py
- [[_make_trade()_1]] - code - tests/test_early_exits.py
- [[check_model_exits model_flipped must require net_edge  -0.10 (not -0.05).]] - rationale - tests/test_early_exits.py
- [[check_model_exits must NOT exit a trade whose edge merely dropped from 8% to…]] - rationale - tests/test_early_exits.py
- [[check_model_exits must not exit a trade entered less than 12 hours ago.]] - rationale - tests/test_early_exits.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_231
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 272]]
- 3 edges to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Community 333]]

## Top bridge nodes
- [[_make_trade()_1]] - degree 9, connects to 2 communities
- [[TestCheckModelExitsThresholds]] - degree 4, connects to 1 community
- [[dot-test_edge_gone_threshold_is_negative()]] - degree 4, connects to 1 community
- [[dot-test_minimum_hold_time_prevents_early_exit()]] - degree 4, connects to 1 community
- [[dot-test_model_flipped_requires_10pct_net_edge()]] - degree 4, connects to 1 community