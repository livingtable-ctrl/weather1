---
type: community
cohesion: 0.11
members: 25
---

# Community 116

**Cohesion:** 0.11 - loosely connected
**Members:** 25 nodes

## Members
- [[dot-summary()]] - code - ab_test.py
- [[dot-test_auto_disable_low_performer()]] - code - tests/test_ab_test.py
- [[dot-test_get_active_variant_returns_least_traded()]] - code - tests/test_ab_test.py
- [[dot-test_list_all_summaries_includes_saved_test()]] - code - tests/test_ab_test.py
- [[dot-test_list_all_summaries_returns_dict()]] - code - tests/test_ab_test.py
- [[dot-test_pick_variant_all_exhausted_falls_back_to_control()]] - code - tests/test_ab_test.py
- [[dot-test_pick_variant_returns_valid_variant()]] - code - tests/test_ab_test.py
- [[dot-test_pick_variant_round_robins_to_least_traded()]] - code - tests/test_ab_test.py
- [[dot-test_record_outcome_increments_trades_and_wins()]] - code - tests/test_ab_test.py
- [[dot-test_record_outcome_unknown_variant_is_noop()]] - code - tests/test_ab_test.py
- [[dot-test_summary_has_required_keys()]] - code - tests/test_ab_test.py
- [[ABTest]] - code - ab_test.py
- [[Return summary statistics for all variants.]] - rationale - ab_test.py
- [[Simple bandit-style AB test across strategy parameter variants. Tracks wins,…]] - rationale - ab_test.py
- [[TestABTest]] - code - tests/test_ab_test.py
- [[Variant with win_rate 20pp below best is auto-disabled after max_trades.]] - rationale - tests/test_ab_test.py
- [[When all variants are exhausted, pick_variant falls back to 'control'.]] - rationale - tests/test_ab_test.py
- [[get_active_variant picks the least-traded active variant from disk state.]] - rationale - tests/test_ab_test.py
- [[list_all_summaries includes tests that have been persisted to disk.]] - rationale - tests/test_ab_test.py
- [[list_all_summaries returns a dict (empty if no tests on disk).]] - rationale - tests/test_ab_test.py
- [[pick_variant favours the variant with fewest trades.]] - rationale - tests/test_ab_test.py
- [[pick_variant returns a name that is in the variants dict.]] - rationale - tests/test_ab_test.py
- [[record_outcome increments trades count; wins only on won=True.]] - rationale - tests/test_ab_test.py
- [[record_outcome with an unknown variant name does nothing (no crash).]] - rationale - tests/test_ab_test.py
- [[summary() returns win_rate, avg_edge, trades, disabled per variant.]] - rationale - tests/test_ab_test.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_116
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 140]]
- 2 edges to [[_COMMUNITY_Community 1]]
- 2 edges to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 6]]
- 1 edge to [[_COMMUNITY_Community 12]]
- 1 edge to [[_COMMUNITY_Community 336]]
- 1 edge to [[_COMMUNITY_Community 368]]
- 1 edge to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 312]]

## Top bridge nodes
- [[ABTest]] - degree 27, connects to 9 communities
- [[TestABTest]] - degree 13, connects to 1 community
- [[dot-test_get_active_variant_returns_least_traded()]] - degree 4, connects to 1 community
- [[dot-test_list_all_summaries_includes_saved_test()]] - degree 4, connects to 1 community
- [[dot-test_list_all_summaries_returns_dict()]] - degree 3, connects to 1 community