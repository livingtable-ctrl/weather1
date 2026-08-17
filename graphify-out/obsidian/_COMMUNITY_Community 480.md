---
type: community
cohesion: 0.25
members: 8
---

# Community 480

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_fee_adjusted_kelly_less_than_fee_free()]] - code - tests/test_weather_markets.py
- [[dot-test_fee_adjusted_never_exceeds_fee_free_across_probs()]] - code - tests/test_weather_markets.py
- [[dot-test_kelly_default_equals_kalshi_fee_rate()]] - code - tests/test_weather_markets.py
- [[Default kelly_fraction() must use KALSHI_FEE_RATE, not 0. P2-8 fix the old…]] - rationale - tests/test_weather_markets.py
- [[Fee-adjusted Kelly must be strictly less than fee-free Kelly for any positive…]] - rationale - tests/test_weather_markets.py
- [[L2-B for all valid (prob, price) pairs, fee-adjusted Kelly ≤ fee-free Kelly.…]] - rationale - tests/test_weather_markets.py
- [[L2-B kelly_fraction must always be called with an explicit fee_rate, never…]] - rationale - tests/test_weather_markets.py
- [[TestKellyFeeRate]] - code - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_480
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 126]]
- 1 edge to [[_COMMUNITY_Community 11]]

## Top bridge nodes
- [[TestKellyFeeRate]] - degree 5, connects to 1 community
- [[dot-test_fee_adjusted_kelly_less_than_fee_free()]] - degree 3, connects to 1 community
- [[dot-test_fee_adjusted_never_exceeds_fee_free_across_probs()]] - degree 3, connects to 1 community
- [[dot-test_kelly_default_equals_kalshi_fee_rate()]] - degree 3, connects to 1 community