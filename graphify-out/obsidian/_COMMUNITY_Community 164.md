---
type: community
cohesion: 0.15
members: 20
---

# Community 164

**Cohesion:** 0.15 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-test_cents_string_normalized()]] - code - tests/test_p9_p10.py
- [[dot-test_dollar_float_passed_through()]] - code - tests/test_p9_p10.py
- [[dot-test_dollar_string_passed_through()]] - code - tests/test_p9_p10.py
- [[dot-test_falls_back_to_second_key_when_first_absent()]] - code - tests/test_p9_p10.py
- [[dot-test_first_key_wins_when_both_present()]] - code - tests/test_p9_p10.py
- [[dot-test_key_constants_match_expected_field_names()]] - code - tests/test_p9_p10.py
- [[dot-test_legacy_cents_int_normalized()]] - code - tests/test_p9_p10.py
- [[dot-test_no_keys_present_defaults_to_zero()]] - code - tests/test_p9_p10.py
- [[dot-test_one_cent_int_normalized_not_misread_as_one_dollar()]] - code - tests/test_p9_p10.py
- [[dot-test_order_executor_uses_the_shared_helper_not_a_local_copy()]] - code - tests/test_p9_p10.py
- [[dot-test_unparseable_string_raises()]] - code - tests/test_p9_p10.py
- [[dot-test_zero_bid_not_bypassed_by_falsy_check()]] - code - tests/test_p9_p10.py
- [[A genuine 0-valued field (0¢ bid) must not be skipped in favor of a later…]] - rationale - tests/test_p9_p10.py
- [[A string price  1.0 is the legacy cents-as-string format.]] - rationale - tests/test_p9_p10.py
- [[Deliberately unguarded -- order_executor.py's live reprice loop and…]] - rationale - tests/test_p9_p10.py
- [[Regression guard for the consolidation itself order_executor.py must no longer…]] - rationale - tests/test_p9_p10.py
- [[Return the first present field as a 0.0-1.0 decimal, trying each key in order.…]] - rationale - utils.py
- [[TestCoalesceMarketPrice]] - code - tests/test_p9_p10.py
- [[The exact edge case that diverged across the 3 original copies an integer…]] - rationale - tests/test_p9_p10.py
- [[coalesce_market_price()]] - code - utils.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_164
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 50]]
- 2 edges to [[_COMMUNITY_Black Swan Halt State]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Community 67]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 144]]
- 1 edge to [[_COMMUNITY_Community 458]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 96]]

## Top bridge nodes
- [[coalesce_market_price()]] - degree 26, connects to 10 communities
- [[TestCoalesceMarketPrice]] - degree 13, connects to 1 community