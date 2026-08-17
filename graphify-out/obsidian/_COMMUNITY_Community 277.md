---
type: community
cohesion: 0.15
members: 13
---

# Community 277

**Cohesion:** 0.15 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-test_forecast_model_weights_falls_back_to_seasonal()]] - code - tests/test_forecasting.py
- [[dot-test_forecast_model_weights_uses_learned_per_city()]] - code - tests/test_forecasting.py
- [[dot-test_learn_seasonal_weights_returns_dict()]] - code - tests/test_forecasting.py
- [[dot-test_load_learned_weights_handles_non_numeric_value()]] - code - tests/test_forecasting.py
- [[dot-test_save_and_load_learned_weights()]] - code - tests/test_forecasting.py
- [[dot-test_save_learned_weights_rejects_non_numeric_value()]] - code - tests/test_forecasting.py
- [[A manually-corrupted file with a non-numeric weight (e.g. a stray string) must…]] - rationale - tests/test_forecasting.py
- [[A non-numeric weight passed to save_learned_weights() must not crash with a…]] - rationale - tests/test_forecasting.py
- [[Falls back to seasonal weights when no learned data for city.]] - rationale - tests/test_forecasting.py
- [[Round-trip save then load returns identical dict.]] - rationale - tests/test_forecasting.py
- [[TestLearnedWeights]] - code - tests/test_forecasting.py
- [[_forecast_model_weights returns city-specific learned weights as priority-2.]] - rationale - tests/test_forecasting.py
- [[learn_seasonal_weights(city) returns {model weight} from tracker MAE.]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_277
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 38]]

## Top bridge nodes
- [[TestLearnedWeights]] - degree 8, connects to 2 communities
- [[dot-test_learn_seasonal_weights_returns_dict()]] - degree 3, connects to 1 community