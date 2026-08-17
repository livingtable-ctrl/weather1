---
type: community
cohesion: 0.11
members: 24
---

# Community 126

**Cohesion:** 0.11 - loosely connected
**Members:** 24 nodes

## Members
- [[dot-test_default_fee_rate_equals_kalshi_fee_rate()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_default_smaller_than_zero_fee()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_fee_reduces_kelly()]] - code - tests/test_weather.py
- [[dot-test_fee_wipes_small_edge()]] - code - tests/test_weather.py
- [[dot-test_half_kelly()]] - code - tests/test_weather.py
- [[dot-test_negative_edge_returns_zero()]] - code - tests/test_weather.py
- [[dot-test_no_edge_returns_zero()]] - code - tests/test_weather.py
- [[dot-test_positive_edge()]] - code - tests/test_weather.py
- [[dot-test_zero_fee_still_callable_explicitly()]] - code - tests/test_phase2_batch_a.py
- [[A tiny edge that is negative after fees should return 0.]] - rationale - tests/test_weather.py
- [[Callers can still pass fee_rate=0.0 explicitly for comparisons.]] - rationale - tests/test_phase2_batch_a.py
- [[Fee-adjusted Kelly must be strictly smaller than fee-free Kelly.]] - rationale - tests/test_phase2_batch_a.py
- [[Kelly with fee should be strictly less than fee-free Kelly.]] - rationale - tests/test_weather.py
- [[P2-8 kelly_fraction default fee_rate must equal KALSHI_FEE_RATE, not 0.]] - rationale - tests/test_phase2_batch_a.py
- [[Quarter-Kelly criterion for a binary prediction market. price = cost per…]] - rationale - weather_markets.py
- [[Result should be quarter of full Kelly (fee-free formula verification).]] - rationale - tests/test_weather.py
- [[Strong positive edge should give a positive Kelly fraction.]] - rationale - tests/test_weather.py
- [[TestKellyCap (P3-13)]] - code - tests/test_weather_markets.py
- [[TestKellyFeeRate (L2-B)]] - code - tests/test_weather_markets.py
- [[TestKellyFraction]] - code - tests/test_weather.py
- [[TestKellyFractionFeeDefault]] - code - tests/test_phase2_batch_a.py
- [[We should never bet when edge is negative.]] - rationale - tests/test_weather.py
- [[When our probability matches market price, Kelly = 0.]] - rationale - tests/test_weather.py
- [[kelly_fraction()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_126
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 173]]
- 4 edges to [[_COMMUNITY_Community 89]]
- 3 edges to [[_COMMUNITY_Community 480]]
- 2 edges to [[_COMMUNITY_Community 15]]
- 2 edges to [[_COMMUNITY_Community 396]]
- 2 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 657]]
- 1 edge to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 78]]
- 1 edge to [[_COMMUNITY_Community 11]]
- 1 edge to [[_COMMUNITY_Community 6]]
- 1 edge to [[_COMMUNITY_Community 142]]
- 1 edge to [[_COMMUNITY_Community 1]]

## Top bridge nodes
- [[kelly_fraction()]] - degree 37, connects to 13 communities
- [[TestKellyFraction]] - degree 7, connects to 1 community
- [[TestKellyFractionFeeDefault]] - degree 5, connects to 1 community