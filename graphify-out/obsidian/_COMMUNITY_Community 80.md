---
type: community
cohesion: 0.12
members: 31
---

# Community 80

**Cohesion:** 0.12 - loosely connected
**Members:** 31 nodes

## Members
- [[dot-_call()_2]] - code - tests/test_phase2_batch_l.py
- [[dot-_valid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_alias_field_names_validated()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_ask_100_cents_accepted()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_ask_above_100_cents_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_bid_zero_accepted()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_cent_integer_prices_valid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_decimal_prices_valid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_equal_bid_ask_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_inverted_spread_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_missing_ticker_invalid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_missing_yes_bid_invalid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_tiny_nonzero_equal_bid_ask_still_rejected()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_valid_market_passes()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_validate_market_accepts_one_cent_bid()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_validate_market_survives_unparseable_price_without_crashing()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_zero_bid_zero_ask_accepted()]] - code - tests/test_phase2_batch_l.py
- [[A genuinely malformed price string must be caught and rejected (ok=False), not…]] - rationale - tests/test_phase2_batch_l.py
- [[End-to-end a market with yes_bid=1 (1 cent) must now be VALID (0.01 is within…]] - rationale - tests/test_phase2_batch_l.py
- [[Integer cent prices (1–99) must pass after normalisation.]] - rationale - tests/test_phase2_batch_l.py
- [[Only the exact (0.0, 0.0) pair is exempt -- any other equal or crossed pair…]] - rationale - tests/test_phase2_batch_l.py
- [[Prices already in decimal (0–1) must pass.]] - rationale - tests/test_phase2_batch_l.py
- [[TestValidateMarketPriceRange]] - code - tests/test_phase2_batch_l.py
- [[bid == ask is an inverted spread.]] - rationale - tests/test_phase2_batch_l.py
- [[bid = ask must be rejected.]] - rationale - tests/test_phase2_batch_l.py
- [[bid=0.00 AND ask=0.00 together means no resting quote at all (an…]] - rationale - tests/test_phase2_batch_l.py
- [[validate_market must reject out-of-range and inverted prices.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_ask=100 (= 1.0) means no resting sell order below par — normal.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_ask=150 normalizes to 1.5 — out of range.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_bid=0 (0¢) means no resting buy order — a normal illiquid quote.]] - rationale - tests/test_phase2_batch_l.py
- [[yes_bid_dollars  yes_ask_dollars alias names are also validated.]] - rationale - tests/test_phase2_batch_l.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_80
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 458]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Community 86]]
- 1 edge to [[_COMMUNITY_Community 417]]

## Top bridge nodes
- [[TestValidateMarketPriceRange]] - degree 22, connects to 3 communities
- [[dot-_call()_2]] - degree 17, connects to 1 community