---
type: community
cohesion: 0.12
members: 23
---

# Community 137

**Cohesion:** 0.12 - loosely connected
**Members:** 23 nodes

## Members
- [[25118 Derive per-model blend weights from inverse-MAE scores in tracker.…]] - rationale - weather_markets.py
- [[dot-test_falls_back_to_seasonal_baseline()]] - code - tests/test_weather_markets.py
- [[dot-test_learned_weights_backfill_missing_models_from_baseline()]] - code - tests/test_weather_markets.py
- [[dot-test_mae_data_overrides_and_skips_learned_weights_entirely()]] - code - tests/test_weather_markets.py
- [[dot-test_malformed_learned_weights_falls_back_safely()]] - code - tests/test_weather_markets.py
- [[dot-test_stray_tracked_model_never_leaks_into_result()]] - code - tests/test_weather_markets.py
- [[dot-test_tier1_admits_a_model_outside_the_fixed_baseline()]] - code - tests/test_weather_markets.py
- [[dot-test_tier2_admits_a_model_outside_the_fixed_baseline()]] - code - tests/test_weather_markets.py
- [[dot-test_tier3_seasonal_baseline_stays_fixed_to_3_models()]] - code - tests/test_weather_markets.py
- [[dot-test_tracked_but_non_ensemble_model_never_leaks_in()]] - code - tests/test_weather_markets.py
- [[A corrupted (non-dict) learned_weights.json entry for a city must not crash --…]] - rationale - tests/test_weather_markets.py
- [[A stray tracked value (e.g. blended, not a real model) in mae_weights must…]] - rationale - tests/test_weather_markets.py
- [[GRADUATE GEMUKMO generalization a model _weights_from_mae() reports (i.e. it…]] - rationale - tests/test_weather_markets.py
- [[No tracker MAE data, no learned weights → pure seasonal baseline.]] - rationale - tests/test_weather_markets.py
- [[Priority-2 (learned_weights.json) is a partial dict — the model it omits must…]] - rationale - tests/test_weather_markets.py
- [[Return per-model weights for the ensemble blend. Priority order — tier 1 is…]] - rationale - weather_markets.py
- [[Same generalization for tier 2 (learned_weights.json) a previously learned…]] - rationale - tests/test_weather_markets.py
- [[TestModelWeights]] - code - tests/test_weather_markets.py
- [[Tier 3 (pure seasonal fallback, no trackerlearned data at all) must stay…]] - rationale - tests/test_weather_markets.py
- [[When tracker MAE data exists, it blends against the seasonal baseline directly…]] - rationale - tests/test_weather_markets.py
- [[_model_weights()]] - code - weather_markets.py
- [[_weights_from_mae()]] - code - weather_markets.py
- [[ecmwf_ifs025 is real, currently-tracked data (feeds _forecast_model_weights()'s…]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_137
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 4 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 2 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[_model_weights()]] - degree 19, connects to 3 communities
- [[_weights_from_mae()]] - degree 5, connects to 3 communities
- [[TestModelWeights]] - degree 10, connects to 1 community