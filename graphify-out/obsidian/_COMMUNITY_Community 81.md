---
type: community
cohesion: 0.08
members: 31
---

# Community 81

**Cohesion:** 0.08 - loosely connected
**Members:** 31 nodes

## Members
- [[dot-test_cents_converted_to_decimal()]] - code - tests/test_weather_markets.py
- [[dot-test_implied_prob_is_midpoint()]] - code - tests/test_weather_markets.py
- [[dot-test_l2d_integer_1_converted_to_1_cent()]] - code - tests/test_weather_markets.py
- [[dot-test_l2d_zero_bid_not_bypassed_by_or()]] - code - tests/test_weather_markets.py
- [[dot-test_mid_falls_back_to_yes_bid_when_no_ask()]] - code - tests/test_weather_markets.py
- [[dot-test_missing_fields_fall_back_to_zero()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_dict_with_expected_keys()_1]] - code - tests/test_weather_markets.py
- [[dot-test_string_prices_parsed()]] - code - tests/test_weather_markets.py
- [[Cross-market consistency checker. For a given city + date, temperature…]] - rationale - consistency.py
- [[Extract yesno bid prices and implied probability from a market. API returns…]] - rationale - weather_markets.py
- [[Fetch the best available price for a ticker+side. Returns None if no live quote…]] - rationale - main.py
- [[Fetch the best available price for a ticker+side. Returns None if no live quote…_1]] - rationale - main.py
- [[Fit a Normal(mean, sigma) to one event's full sibling bracket ladder…]] - rationale - weather_markets.py
- [[Integer values  1 are treated as cents and divided by 100.]] - rationale - tests/test_weather_markets.py
- [[L2-D a valid 0¢ bid must not be bypassed by the or-fallback. When yes_bid=0…]] - rationale - tests/test_weather_markets.py
- [[L2-D integer value 1 (= 1¢) must be divided by 100, not returned as 1.0. The…]] - rationale - tests/test_weather_markets.py
- [[Missing price fields default to 0.0 without raising.]] - rationale - tests/test_weather_markets.py
- [[Result must be a dict containing the standard price keys.]] - rationale - tests/test_weather_markets.py
- [[String-format prices (e.g. '0.55') are parsed correctly.]] - rationale - tests/test_weather_markets.py
- [[TestEntryEdgeVsMidEdge (L7-C)]] - code - tests/test_weather_markets.py
- [[TestParseMarketPrice]] - code - tests/test_weather_markets.py
- [[When yes_ask is 0 the mid falls back to yes_bid.]] - rationale - tests/test_weather_markets.py
- [[_group_markets() No tryexcept Aborts Whole Scan (710)]] - document - docs/grade_audit/outputs/consistency.py.md
- [[_resolve_price()]] - code - main.py
- [[consistency.py]] - code - consistency.py
- [[consistency.py Detect-Only, No Enforcement Path (INFO)]] - document - docs/grade_audit/outputs/consistency.py.md
- [[consistency.py File Grade median 710, no TIER1 promotions]] - document - docs/grade_audit/outputs/consistency.py.md
- [[consistency.py Grade Audit]] - document - docs/grade_audit/outputs/consistency.py.md
- [[fit_market_implied_distribution()]] - code - weather_markets.py
- [[implied_prob equals the mid-price of yes_bid and yes_ask.]] - rationale - tests/test_weather_markets.py
- [[parse_market_price()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_81
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_Community 5]]
- 11 edges to [[_COMMUNITY_Community 1]]
- 9 edges to [[_COMMUNITY_Community 0]]
- 7 edges to [[_COMMUNITY_Community 3]]
- 7 edges to [[_COMMUNITY_Community 6]]
- 2 edges to [[_COMMUNITY_Community 11]]
- 2 edges to [[_COMMUNITY_Community 159]]
- 2 edges to [[_COMMUNITY_Community 20]]
- 2 edges to [[_COMMUNITY_Community 363]]
- 2 edges to [[_COMMUNITY_Community 586]]
- 2 edges to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 17]]
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Community 398]]
- 1 edge to [[_COMMUNITY_Community 406]]
- 1 edge to [[_COMMUNITY_Community 44]]
- 1 edge to [[_COMMUNITY_Community 48]]
- 1 edge to [[_COMMUNITY_Community 76]]
- 1 edge to [[_COMMUNITY_Community 78]]
- 1 edge to [[_COMMUNITY_Community 43]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[parse_market_price()]] - degree 54, connects to 15 communities
- [[consistency.py]] - degree 21, connects to 8 communities
- [[fit_market_implied_distribution()]] - degree 9, connects to 7 communities
- [[_resolve_price()]] - degree 8, connects to 3 communities
- [[TestParseMarketPrice]] - degree 10, connects to 1 community