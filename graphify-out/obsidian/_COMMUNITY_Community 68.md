---
type: community
cohesion: 0.08
members: 33
---

# Community 68

**Cohesion:** 0.08 - loosely connected
**Members:** 33 nodes

## Members
- [[31 _blend_weights scaled by inverse ensemble variance.]] - rationale - weather_markets.py
- [[dot-test_analyze_precip_trade_does_not_set_time_risk()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_analyze_snow_trade_does_not_set_time_risk()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_high_ens_std_reduces_ensemble_weight()]] - code - tests/test_forecasting.py
- [[dot-test_low_ens_std_increases_ensemble_weight()]] - code - tests/test_forecasting.py
- [[dot-test_none_ens_std_returns_base_weights()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_long_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_medium_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_redistributed_when_unavailable()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_short_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_weights_sum_to_one()_3]] - code - tests/test_forecasting.py
- [[dot-test_weights_sum_to_one()_4]] - code - tests/test_forecasting.py
- [[Decay NWS weight at longer horizons; preserve calibrated weights at days_out=1.…]] - rationale - weather_markets.py
- [[Phase 2 Batch K regression tests P2-24P2-26P2-36P2-39P2-45 —…]] - rationale - tests/test_phase2_batch_k.py
- [[Return (w_ensemble, w_climatology, w_nws). Priority regime override (highest,…]] - rationale - weather_markets.py
- [[TestBlendWeights]] - code - tests/test_forecasting.py
- [[TestConfidenceScaledBlendWeights]] - code - tests/test_forecasting.py
- [[TestPrecipSnowOmitTimeRisk]] - code - tests/test_phase2_batch_k.py
- [[When NWS unavailable, its weight redistributed to ens+clim.]] - rationale - tests/test_forecasting.py
- [[_analyze_precip_trade_analyze_snow_trade must NOT set their own time_risk --…]] - rationale - tests/test_phase2_batch_k.py
- [[_blend_weights()]] - code - weather_markets.py
- [[_confidence_scaled_blend_weights()]] - code - weather_markets.py
- [[_nws_days_out_scale()]] - code - weather_markets.py
- [[days_out 4-7 NWS weight must be 0.25.]] - rationale - tests/test_forecasting.py
- [[days_out = 3 NWS weight must be 0.35.]] - rationale - tests/test_forecasting.py
- [[days_out  7 NWS weight must be 0.10.]] - rationale - tests/test_forecasting.py
- [[ens_std = 2Â°F (tight spread) must increase w_ens vs baseline.]] - rationale - tests/test_forecasting.py
- [[ens_std  8Â°F (high uncertainty) must reduce w_ens vs baseline.]] - rationale - tests/test_forecasting.py
- [[ens_std=None â†’ identical result to _blend_weights.]] - rationale - tests/test_forecasting.py
- [[test_ensemble_confidence_scale_clamped()]] - code - tests/test_weather_markets.py
- [[test_ensemble_confidence_scale_high_std_reduces_ens_weight()]] - code - tests/test_weather_markets.py
- [[test_ensemble_confidence_scale_no_std_unchanged()]] - code - tests/test_weather_markets.py
- [[test_phase2_batch_k.py]] - code - tests/test_phase2_batch_k.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_68
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 5]]
- 5 edges to [[_COMMUNITY_Community 11]]
- 4 edges to [[_COMMUNITY_Community 38]]
- 3 edges to [[_COMMUNITY_Community 77]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 89]]
- 2 edges to [[_COMMUNITY_Community 218]]
- 2 edges to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 387]]
- 1 edge to [[_COMMUNITY_Community 183]]

## Top bridge nodes
- [[test_phase2_batch_k.py]] - degree 13, connects to 6 communities
- [[_confidence_scaled_blend_weights()]] - degree 19, connects to 5 communities
- [[_blend_weights()]] - degree 18, connects to 4 communities
- [[TestBlendWeights]] - degree 7, connects to 2 communities
- [[TestConfidenceScaledBlendWeights]] - degree 6, connects to 2 communities