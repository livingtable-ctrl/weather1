---
type: community
cohesion: 0.06
members: 51
---

# Community 33

**Cohesion:** 0.06 - loosely connected
**Members:** 51 nodes

## Members
- [[dot-__init__()_4]] - code - ab_test.py
- [[dot-pick_variant()]] - code - ab_test.py
- [[dot-record_outcome()]] - code - ab_test.py
- [[dot-summary()]] - code - ab_test.py
- [[dot-test_auto_disable_low_performer()]] - code - tests/test_ab_test.py
- [[dot-test_get_active_variant_fallback()]] - code - tests/test_ab_test.py
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
- [[Any_1]] - code
- [[Convenience load a named test from disk and pick the active variant. Returns…]] - rationale - ab_test.py
- [[L4-A get_active_variant must return the variant value, not None. Previously…]] - rationale - tests/test_ab_test.py
- [[L4-A variant value must round-trip through disk (JSON serializedeserialize).…]] - rationale - tests/test_ab_test.py
- [[Pick an active variant (round-robin among non-disabled, non-exhausted variants).]] - rationale - ab_test.py
- [[Record a trade outcome for the given variant.]] - rationale - ab_test.py
- [[Redirect all ab_test state IO to a temp directory for test isolation.]] - rationale - tests/test_ab_test.py
- [[Return summary statistics for all variants.]] - rationale - ab_test.py
- [[Return summary stats for all tests found on disk.]] - rationale - ab_test.py
- [[Simple bandit-style AB test across strategy parameter variants. Tracks wins,…]] - rationale - ab_test.py
- [[TestABTest]] - code - tests/test_ab_test.py
- [[Tests for ab_test.py — AB experiment framework.]] - rationale - tests/test_ab_test.py
- [[Variant with win_rate 20pp below best is auto-disabled after max_trades.]] - rationale - tests/test_ab_test.py
- [[When all variants are exhausted, pick_variant falls back to 'control'.]] - rationale - tests/test_ab_test.py
- [[_load_test_state()]] - code - ab_test.py
- [[_patch_ab_dir()]] - code - tests/test_ab_test.py
- [[_save_test_state()]] - code - ab_test.py
- [[ab_test.ABTest]] - code - ab_test.py
- [[ab_test.py]] - code - ab_test.py
- [[ab_test.py — Simple AB testing framework for strategy parameter variants.…]] - rationale - ab_test.py
- [[fixture_7]] - code
- [[get_active_variant picks the least-traded active variant from disk state.]] - rationale - tests/test_ab_test.py
- [[get_active_variant returns ('control', None) for unknown test name.]] - rationale - tests/test_ab_test.py
- [[get_active_variant()]] - code - ab_test.py
- [[list_all_summaries includes tests that have been persisted to disk.]] - rationale - tests/test_ab_test.py
- [[list_all_summaries returns a dict (empty if no tests on disk).]] - rationale - tests/test_ab_test.py
- [[list_all_summaries()]] - code - ab_test.py
- [[pick_variant favours the variant with fewest trades.]] - rationale - tests/test_ab_test.py
- [[pick_variant returns a name that is in the variants dict.]] - rationale - tests/test_ab_test.py
- [[record_outcome increments trades count; wins only on won=True.]] - rationale - tests/test_ab_test.py
- [[record_outcome with an unknown variant name does nothing (no crash).]] - rationale - tests/test_ab_test.py
- [[summary() returns win_rate, avg_edge, trades, disabled per variant.]] - rationale - tests/test_ab_test.py
- [[test_ab_test.py]] - code - tests/test_ab_test.py
- [[test_l4a_get_active_variant_returns_value()]] - code - tests/test_ab_test.py
- [[test_l4a_get_active_variant_value_survives_reload()]] - code - tests/test_ab_test.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_33
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 59]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 454]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]

## Top bridge nodes
- [[ABTest]] - degree 23, connects to 4 communities
- [[ab_test.py]] - degree 12, connects to 3 communities
- [[get_active_variant()]] - degree 10, connects to 1 community