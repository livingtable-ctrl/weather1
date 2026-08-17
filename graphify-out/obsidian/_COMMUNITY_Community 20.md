---
type: community
cohesion: 0.05
members: 60
---

# Community 20

**Cohesion:** 0.05 - loosely connected
**Members:** 60 nodes

## Members
- [[dot-_call()]] - code - tests/test_phase2_batch_l.py
- [[dot-_valid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_alias_field_names_validated()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_ask_100_cents_accepted()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_ask_above_100_cents_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_bid_zero_accepted()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_cent_integer_prices_valid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_cents_string_normalized()]] - code - tests/test_p9_p10.py
- [[dot-test_decimal_prices_valid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_dollar_float_passed_through()]] - code - tests/test_p9_p10.py
- [[dot-test_dollar_string_passed_through()]] - code - tests/test_p9_p10.py
- [[dot-test_equal_bid_ask_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_falls_back_to_second_key_when_first_absent()]] - code - tests/test_p9_p10.py
- [[dot-test_first_key_wins_when_both_present()]] - code - tests/test_p9_p10.py
- [[dot-test_inverted_spread_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_key_constants_match_expected_field_names()]] - code - tests/test_p9_p10.py
- [[dot-test_legacy_cents_int_normalized()]] - code - tests/test_p9_p10.py
- [[dot-test_missing_ticker_invalid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_missing_yes_bid_invalid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_no_keys_present_defaults_to_zero()]] - code - tests/test_p9_p10.py
- [[dot-test_one_cent_int_normalized_not_misread_as_one_dollar()]] - code - tests/test_p9_p10.py
- [[dot-test_order_executor_uses_the_shared_helper_not_a_local_copy()]] - code - tests/test_p9_p10.py
- [[dot-test_price_to_decimal_helper()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_price_to_decimal_one_cent_bug_fixed()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_tiny_nonzero_equal_bid_ask_still_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_unparseable_string_raises()]] - code - tests/test_p9_p10.py
- [[dot-test_valid_market_passes()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_validate_market_accepts_one_cent_bid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_validate_market_survives_unparseable_price_without_crashing()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_zero_bid_not_bypassed_by_falsy_check()]] - code - tests/test_p9_p10.py
- [[dot-test_zero_bid_zero_ask_accepted()]] - code - tests/test_phase2_batch_l.py
- [[A genuine 0-valued field (0¢ bid) must not be skipped in favor of a later…]] - rationale - tests/test_p9_p10.py
- [[A genuinely malformed price string must be caught and rejected (ok=False), not…]] - rationale - tests/test_phase2_batch_l.py
- [[A string price  1.0 is the legacy cents-as-string format.]] - rationale - tests/test_p9_p10.py
- [[Deliberately unguarded -- order_executor.py's live reprice loop and…]] - rationale - tests/test_p9_p10.py
- [[End-to-end a market with yes_bid=1 (1 cent) must now be VALID (0.01 is within…]] - rationale - tests/test_phase2_batch_l.py
- [[Integer cent prices (1–99) must pass after normalisation.]] - rationale - tests/test_phase2_batch_l.py
- [[KALSHI CENTSDOLLARS PRICE NORMALIZATION consolidation bug fix the old…]] - rationale - tests/test_phase2_batch_l.py
- [[Normalize a price value to decimal (0-1) via utils.coalesce_market_price,…]] - rationale - schema_validator.py
- [[Only the exact (0.0, 0.0) pair is exempt -- any other equal or crossed pair…]] - rationale - tests/test_phase2_batch_l.py
- [[Prices already in decimal (0–1) must pass.]] - rationale - tests/test_phase2_batch_l.py
- [[Regression guard for the consolidation itself order_executor.py must no longer…]] - rationale - tests/test_p9_p10.py
- [[Return the first present field as a 0.0-1.0 decimal, trying each key in order.…]] - rationale - utils.py
- [[TestCoalesceMarketPrice]] - code - tests/test_p9_p10.py
- [[TestValidateMarketPriceRange]] - code - tests/test_phase2_batch_l.py
- [[The exact edge case that diverged across the 3 original copies an integer…]] - rationale - tests/test_p9_p10.py
- [[_safe_market_price()]] - code - web_app.py
- [[_safe_price (utils.coalesce_market_price, wrapped fail-soft) normalises int…]] - rationale - tests/test_phase2_batch_l.py
- [[_safe_price()]] - code - schema_validator.py
- [[bid == ask is an inverted spread.]] - rationale - tests/test_phase2_batch_l.py
- [[bid = ask must be rejected.]] - rationale - tests/test_phase2_batch_l.py
- [[bid=0.00 AND ask=0.00 together means no resting quote at all (an…]] - rationale - tests/test_phase2_batch_l.py
- [[coalesce_market_price()]] - code - utils.py
- [[coalesce_market_price(), degrading a malformed price field to 0 (=no quote)…]] - rationale - web_app.py
- [[order_executor.py live reprice loop]] - code - order_executor.py
- [[validate_market must reject out-of-range and inverted prices.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_ask=100 (= 1.0) means no resting sell order below par — normal.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_ask=150 normalizes to 1.5 — out of range.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_bid=0 (0¢) means no resting buy order — a normal illiquid quote.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_bid_dollars  yes_ask_dollars alias names are also validated.]] - rationale - tests/test_phase2_batch_l.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_20
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 6]]
- 3 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 187]]
- 2 edges to [[_COMMUNITY_Community 54]]
- 2 edges to [[_COMMUNITY_Community 0]]
- 2 edges to [[_COMMUNITY_Community 74]]
- 2 edges to [[_COMMUNITY_Community 81]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[coalesce_market_price()]] - degree 27, connects to 9 communities
- [[_safe_price()]] - degree 9, connects to 3 communities
- [[TestValidateMarketPriceRange]] - degree 22, connects to 2 communities
- [[dot-_call()]] - degree 17, connects to 1 community
- [[TestCoalesceMarketPrice]] - degree 13, connects to 1 community