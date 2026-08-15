---
type: community
cohesion: 0.06
members: 53
---

# Kelly Sizing Property-Based Tests

**Cohesion:** 0.06 - loosely connected
**Members:** 53 nodes

## Members
- [[dot-test_default_fee_rate_equals_kalshi_fee_rate()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_default_smaller_than_zero_fee()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_fee_adjusted_kelly_less_than_fee_free()]] - code - tests/test_weather_markets.py
- [[dot-test_fee_adjusted_never_exceeds_fee_free_across_probs()]] - code - tests/test_weather_markets.py
- [[dot-test_fee_reduces_kelly()]] - code - tests/test_weather.py
- [[dot-test_fee_wipes_small_edge()]] - code - tests/test_weather.py
- [[dot-test_half_kelly()]] - code - tests/test_weather.py
- [[dot-test_kelly_default_equals_kalshi_fee_rate()]] - code - tests/test_weather_markets.py
- [[dot-test_kelly_fraction_caps_at_kelly_cap()]] - code - tests/test_weather_markets.py
- [[dot-test_negative_edge_returns_zero()]] - code - tests/test_weather.py
- [[dot-test_no_edge_returns_zero()]] - code - tests/test_weather.py
- [[dot-test_positive_edge()]] - code - tests/test_weather.py
- [[dot-test_zero_fee_still_callable_explicitly()]] - code - tests/test_phase2_batch_a.py
- [[A tiny edge that is negative after fees should return 0.]] - rationale - tests/test_weather.py
- [[Callers can still pass fee_rate=0.0 explicitly for comparisons.]] - rationale - tests/test_phase2_batch_a.py
- [[Default kelly_fraction() must use KALSHI_FEE_RATE, not 0. P2-8 fix the old…]] - rationale - tests/test_weather_markets.py
- [[Fee-adjusted Kelly must be strictly less than fee-free Kelly for any positive…]] - rationale - tests/test_weather_markets.py
- [[Fee-adjusted Kelly must be strictly smaller than fee-free Kelly.]] - rationale - tests/test_phase2_batch_a.py
- [[Higher our_prob → higher or equal Kelly fraction (monotone).]] - rationale - tests/test_kelly_property.py
- [[KELLY_CAP constant]] - code - utils.py
- [[Kelly with fee should be strictly less than fee-free Kelly.]] - rationale - tests/test_weather.py
- [[L2-B for all valid (prob, price) pairs, fee-adjusted Kelly ≤ fee-free Kelly.…]] - rationale - tests/test_weather_markets.py
- [[L2-B kelly_fraction must always be called with an explicit fee_rate, never…]] - rationale - tests/test_weather_markets.py
- [[P2-8 kelly_fraction default fee_rate must equal KALSHI_FEE_RATE, not 0.]] - rationale - tests/test_phase2_batch_a.py
- [[P3-3 kelly_bet_dollars  drawdown_scaling_factor must never exceed current…]] - rationale - tests/test_kelly_property.py
- [[Property-based tests for Kelly sizing using Hypothesis.]] - rationale - tests/test_kelly_property.py
- [[Quarter-Kelly criterion for a binary prediction market. price = cost per…]] - rationale - weather_markets.py
- [[Quarter-Kelly never exceeds KELLY_CAP=0.25 (full_kelly4 tops out just under…]] - rationale - tests/test_weather_markets.py
- [[Result should be quarter of full Kelly (fee-free formula verification).]] - rationale - tests/test_weather.py
- [[Strong positive edge should give a positive Kelly fraction.]] - rationale - tests/test_weather.py
- [[TestKellyCap]] - code - tests/test_weather_markets.py
- [[TestKellyFeeRate]] - code - tests/test_weather_markets.py
- [[TestKellyFraction]] - code - tests/test_weather.py
- [[TestKellyFractionFeeDefault]] - code - tests/test_phase2_batch_a.py
- [[Verify kelly_fraction hard cap is KELLY_CAP=0.25 (P3-13 unified from 0.33).]] - rationale - tests/test_weather_markets.py
- [[We should never bet when edge is negative.]] - rationale - tests/test_weather.py
- [[When market price exceeds our_prob (negative edge), Kelly = 0.]] - rationale - tests/test_kelly_property.py
- [[When our probability matches market price, Kelly = 0.]] - rationale - tests/test_weather.py
- [[When our_prob significantly beats price (positive edge), Kelly  0.]] - rationale - tests/test_kelly_property.py
- [[given]] - code
- [[kelly_fraction always returns a non-negative value.]] - rationale - tests/test_kelly_property.py
- [[kelly_fraction never exceeds the hard cap (KELLY_CAP = 0.25).]] - rationale - tests/test_kelly_property.py
- [[kelly_fraction()]] - code - weather_markets.py
- [[kelly_quantity cost (qty  price) never exceeds current balance.]] - rationale - tests/test_kelly_property.py
- [[settings]] - code
- [[test_kelly_bet_dollars_never_exceeds_balance()]] - code - tests/test_kelly_property.py
- [[test_kelly_fraction_never_exceeds_cap()]] - code - tests/test_kelly_property.py
- [[test_kelly_fraction_never_negative()]] - code - tests/test_kelly_property.py
- [[test_kelly_monotone_in_prob()]] - code - tests/test_kelly_property.py
- [[test_kelly_negative_edge_gives_zero_fraction()]] - code - tests/test_kelly_property.py
- [[test_kelly_positive_edge_gives_nonzero_fraction()]] - code - tests/test_kelly_property.py
- [[test_kelly_property.py]] - code - tests/test_kelly_property.py
- [[test_kelly_quantity_cost_never_exceeds_balance()]] - code - tests/test_kelly_property.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Kelly_Sizing_Property-Based_Tests
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 4 edges to [[_COMMUNITY_Community 59]]
- 3 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 2 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 2 edges to [[_COMMUNITY_Community 168]]
- 2 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 36]]
- 1 edge to [[_COMMUNITY_Community 58]]

## Top bridge nodes
- [[kelly_fraction()]] - degree 39, connects to 9 communities
- [[test_kelly_property.py]] - degree 12, connects to 2 communities
- [[TestKellyFraction]] - degree 7, connects to 1 community
- [[TestKellyFractionFeeDefault]] - degree 5, connects to 1 community
- [[TestKellyFeeRate]] - degree 5, connects to 1 community