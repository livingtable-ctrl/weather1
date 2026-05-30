---
type: community
cohesion: 0.04
members: 80
---

# Model Weights & Ensemble Blend

**Cohesion:** 0.04 - loosely connected
**Members:** 80 nodes

## Members
- [[28 Return the current ENSO phase 'el_nino', 'la_nina', or 'neutral'.     Use]] - rationale - weather_markets.py
- [[37 Return the current NWP forecast cycle label based on UTC hour.     Cycles]] - rationale - weather_markets.py
- [[.setup_method()_17]] - code - tests/test_phase4.py
- [[.teardown_method()_14]] - code - tests/test_phase4.py
- [[.test_all_summer_months_use_lower_ecmwf()]] - code - tests/test_weather_markets.py
- [[.test_all_winter_months_use_high_ecmwf()]] - code - tests/test_weather_markets.py
- [[.test_city_weights_used_when_available()]] - code - tests/test_phase4.py
- [[.test_dynamic_weights_override_learned()]] - code - tests/test_phase4.py
- [[.test_ecmwf_weight_summer()]] - code - tests/test_weather.py
- [[.test_ecmwf_weight_winter()]] - code - tests/test_weather.py
- [[.test_el_nino_boosts_ecmwf_above_neutral()]] - code - tests/test_phase4.py
- [[.test_el_nino_boosts_ecmwf_in_winter()]] - code - tests/test_forecasting.py
- [[.test_el_nino_returns_correct_label()]] - code - tests/test_forecasting.py
- [[.test_empty_tracker_returns_none()]] - code - tests/test_phase4.py
- [[.test_get_enso_phase_returns_valid_phase()]] - code - tests/test_phase4.py
- [[.test_gfs_and_icon_constant()]] - code - tests/test_weather.py
- [[.test_gfs_and_icon_weights_are_constant()]] - code - tests/test_weather_markets.py
- [[.test_high_mae_model_gets_low_weight()]] - code - tests/test_phase4.py
- [[.test_la_nina_boosts_ecmwf_above_neutral()]] - code - tests/test_phase4.py
- [[.test_la_nina_returns_correct_label()]] - code - tests/test_forecasting.py
- [[.test_neutral_returns_correct_label()]] - code - tests/test_forecasting.py
- [[.test_neutral_winter_ecmwf_weight()]] - code - tests/test_forecasting.py
- [[.test_no_city_falls_back_to_seasonal()]] - code - tests/test_phase4.py
- [[.test_no_enso_boost_in_summer()]] - code - tests/test_phase4.py
- [[.test_no_tracker_data_returns_none()]] - code - tests/test_phase4.py
- [[.test_none_oni_returns_neutral()]] - code - tests/test_forecasting.py
- [[.test_returns_dict_with_expected_keys()_1]] - code - tests/test_weather_markets.py
- [[.test_returns_none_below_threshold()]] - code - tests/test_phase4.py
- [[.test_returns_none_for_unknown_city()]] - code - tests/test_phase4.py
- [[.test_returns_none_when_city_is_none()]] - code - tests/test_forecasting.py
- [[.test_returns_none_when_no_tracker_rows()]] - code - tests/test_forecasting.py
- [[.test_returns_softmax_weights_from_tracker()]] - code - tests/test_forecasting.py
- [[.test_seasonal_fallback_when_no_tracker_rows()]] - code - tests/test_forecasting.py
- [[.test_tracker_weights_used_when_available()]] - code - tests/test_forecasting.py
- [[.test_used_as_first_priority_in_forecast_model_weights()]] - code - tests/test_forecasting.py
- [[.test_winter_month_boosts_ecmwf_weight()]] - code - tests/test_weather_markets.py
- [[All summer months (Apr-Sep) should use the lower ECMWF weight.]] - rationale - tests/test_weather_markets.py
- [[All winter months (Oct-Mar) should use the elevated ECMWF weight.]] - rationale - tests/test_weather_markets.py
- [[City is None → returns None without calling tracker.]] - rationale - tests/test_phase4.py
- [[Derive per-model blend weights from tracker softmax-MAE data via     get_model_]] - rationale - weather_markets.py
- [[Dynamic tracker weights take priority over learned_weights.json.]] - rationale - tests/test_phase4.py
- [[ECMWF should have weight 1.5 in summer months (Apr–Sep).]] - rationale - tests/test_weather.py
- [[ECMWF should have weight 2.5 in winter months (Oct–Mar).]] - rationale - tests/test_weather.py
- [[ECMWF weight should be higher in winter than summer.]] - rationale - tests/test_weather_markets.py
- [[ENSO should not affect summer weights (not winter).]] - rationale - tests/test_phase4.py
- [[El Niño winter should give ECMWF higher weight than neutral.]] - rationale - tests/test_phase4.py
- [[Empty dict from get_model_weights (no rows) → returns None.]] - rationale - tests/test_phase4.py
- [[GFS and ICON weights should be 1.0 year-round._1]] - rationale - tests/test_weather_markets.py
- [[GFS and ICON weights should be 1.0 year-round.]] - rationale - tests/test_weather.py
- [[La Niña winter should give ECMWF higher weight than neutral.]] - rationale - tests/test_phase4.py
- [[Load per-city model weights previously saved by save_learned_weights().     For]] - rationale - weather_markets.py
- [[No city → seasonal fallback (no learned weights lookup).]] - rationale - tests/test_phase4.py
- [[Returns None immediately when city is None (no tracker call needed).]] - rationale - tests/test_forecasting.py
- [[Returns None when get_model_weights returns empty dict (no rows).]] - rationale - tests/test_forecasting.py
- [[Returns get_model_weights result when non-empty.]] - rationale - tests/test_forecasting.py
- [[Seasonal model weights for the daily forecast blend.     ECMWF is the most accu]] - rationale - weather_markets.py
- [[TestDynamicModelWeights]] - code - tests/test_forecasting.py
- [[TestDynamicModelWeights_1]] - code - tests/test_phase4.py
- [[TestEnsoPhase]] - code - tests/test_forecasting.py
- [[TestEnsoPhase_1]] - code - tests/test_phase4.py
- [[TestForecastModelWeights_1]] - code - tests/test_weather_markets.py
- [[TestForecastModelWeights]] - code - tests/test_weather.py
- [[TestForecastModelWeightsTrackerIntegration]] - code - tests/test_forecasting.py
- [[TestGetStationBias]] - code - tests/test_phase4.py
- [[TestPerCityLearnedWeights]] - code - tests/test_phase4.py
- [[Tests for Phase 4 improvements (tasks 21, 25, 26, 28, 29, 33, 37, 122,]] - rationale - tests/test_phase4.py
- [[When learned_weights.json has NYC weights, they're returned for NYC.]] - rationale - tests/test_phase4.py
- [[When tracker has 10+ model rows, _forecast_model_weights returns tracker weights]] - rationale - tests/test_forecasting.py
- [[When tracker has no rows (empty dict), _forecast_model_weights falls back to sea]] - rationale - tests/test_forecasting.py
- [[_current_forecast_cycle()_1]] - code - weather_markets.py
- [[_dynamic_model_weights()]] - code - weather_markets.py
- [[_forecast_model_weights gives ECMWF +0.5 extra during El Niño winter.]] - rationale - tests/test_forecasting.py
- [[_forecast_model_weights uses _dynamic_model_weights as first priority.]] - rationale - tests/test_forecasting.py
- [[_forecast_model_weights()]] - code - weather_markets.py
- [[_get_enso_phase always returns one of three valid values.]] - rationale - tests/test_phase4.py
- [[_get_enso_phase()]] - code - weather_markets.py
- [[get_model_weights result is passed through higher-weight model wins.]] - rationale - tests/test_phase4.py
- [[load_learned_weights()]] - code - weather_markets.py
- [[test_forecasting.py]] - code - tests/test_forecasting.py
- [[test_phase4.py]] - code - tests/test_phase4.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Model_Weights__Ensemble_Blend
SORT file.name ASC
```

## Connections to other communities
- 21 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 6 edges to [[_COMMUNITY_SnowPrecip Physics]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Tracker Analytics (BrierBias)]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]

## Top bridge nodes
- [[test_forecasting.py]] - degree 28, connects to 13 communities
- [[test_phase4.py]] - degree 21, connects to 8 communities
- [[_forecast_model_weights()]] - degree 33, connects to 3 communities
- [[_dynamic_model_weights()]] - degree 15, connects to 2 communities
- [[_get_enso_phase()]] - degree 12, connects to 2 communities