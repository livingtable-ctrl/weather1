---
type: community
cohesion: 0.15
members: 20
---

# Community 159

**Cohesion:** 0.15 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-test_falls_back_to_legacy_volume_when_volume_fp_is_zero()]] - code - tests/test_weather_markets.py
- [[dot-test_illiquid_market_all_zeros()]] - code - tests/test_weather_markets.py
- [[dot-test_illiquid_market_empty_dict()]] - code - tests/test_weather_markets.py
- [[dot-test_liquid_market_with_no_bid_only()]] - code - tests/test_weather_markets.py
- [[dot-test_liquid_market_with_quotes_and_volume()]] - code - tests/test_weather_markets.py
- [[dot-test_liquid_market_with_volume_fp_only()]] - code - tests/test_weather_markets.py
- [[dot-test_liquid_market_with_volume_only()]] - code - tests/test_weather_markets.py
- [[dot-test_liquid_market_with_yes_bid_only()]] - code - tests/test_weather_markets.py
- [[dot-test_string_volume_fp_with_no_quotes_does_not_crash()]] - code - tests/test_weather_markets.py
- [[dot-test_volume_fp_takes_precedence_over_legacy_when_both_nonzero()]] - code - tests/test_weather_markets.py
- [[A market with both-sided quotes and volume is liquid.]] - rationale - tests/test_weather_markets.py
- [[Empty market dict has no liquidity.]] - rationale - tests/test_weather_markets.py
- [[Market with no quotes and zero volume is not liquid.]] - rationale - tests/test_weather_markets.py
- [[Market with no quotes but nonzero volume counts as liquid.]] - rationale - tests/test_weather_markets.py
- [[Market with only a no_bid  0 qualifies as liquid.]] - rationale - tests/test_weather_markets.py
- [[Market with only a yes_bid  0 qualifies as liquid.]] - rationale - tests/test_weather_markets.py
- [[TestIsLiquid]] - code - tests/test_weather_markets.py
- [[True if the market has real two-sided quotes (not just 00). A market with no…]] - rationale - weather_markets.py
- [[backlog.txt is_liquid() only reads legacy volumeopen_interest field names]] - document - backlog.txt
- [[is_liquid()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_159
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 0]]
- 3 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 11]]
- 2 edges to [[_COMMUNITY_Community 81]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 5]]

## Top bridge nodes
- [[is_liquid()]] - degree 23, connects to 6 communities
- [[TestIsLiquid]] - degree 13, connects to 1 community