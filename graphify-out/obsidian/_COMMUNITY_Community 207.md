---
type: community
cohesion: 0.12
members: 17
---

# Community 207

**Cohesion:** 0.12 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-test_cents_converted_to_decimal()]] - code - tests/test_weather_markets.py
- [[dot-test_implied_prob_is_midpoint()]] - code - tests/test_weather_markets.py
- [[dot-test_l2d_integer_1_converted_to_1_cent()]] - code - tests/test_weather_markets.py
- [[dot-test_l2d_zero_bid_not_bypassed_by_or()]] - code - tests/test_weather_markets.py
- [[dot-test_mid_falls_back_to_yes_bid_when_no_ask()]] - code - tests/test_weather_markets.py
- [[dot-test_missing_fields_fall_back_to_zero()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_dict_with_expected_keys()]] - code - tests/test_weather_markets.py
- [[dot-test_string_prices_parsed()]] - code - tests/test_weather_markets.py
- [[Integer values  1 are treated as cents and divided by 100.]] - rationale - tests/test_weather_markets.py
- [[L2-D a valid 0¢ bid must not be bypassed by the or-fallback. When yes_bid=0…]] - rationale - tests/test_weather_markets.py
- [[L2-D integer value 1 (= 1¢) must be divided by 100, not returned as 1.0. The…]] - rationale - tests/test_weather_markets.py
- [[Missing price fields default to 0.0 without raising.]] - rationale - tests/test_weather_markets.py
- [[Result must be a dict containing the standard price keys.]] - rationale - tests/test_weather_markets.py
- [[String-format prices (e.g. '0.55') are parsed correctly.]] - rationale - tests/test_weather_markets.py
- [[TestParseMarketPrice]] - code - tests/test_weather_markets.py
- [[When yes_ask is 0 the mid falls back to yes_bid.]] - rationale - tests/test_weather_markets.py
- [[implied_prob equals the mid-price of yes_bid and yes_ask.]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_207
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]

## Top bridge nodes
- [[TestParseMarketPrice]] - degree 9, connects to 1 community
- [[dot-test_cents_converted_to_decimal()]] - degree 3, connects to 1 community
- [[dot-test_implied_prob_is_midpoint()]] - degree 3, connects to 1 community
- [[dot-test_l2d_integer_1_converted_to_1_cent()]] - degree 3, connects to 1 community
- [[dot-test_l2d_zero_bid_not_bypassed_by_or()]] - degree 3, connects to 1 community