---
type: community
cohesion: 0.03
members: 104
---

# Forecasting Persistence Model Tests

**Cohesion:** 0.03 - loosely connected
**Members:** 104 nodes

## Members
- [[26 Persistence baseline — models tomorrow's temperature as N(current_value,…]] - rationale - climatology.py
- [[28 Return the current ENSO phase 'el_nino', 'la_nina', or 'neutral'. Uses…]] - rationale - weather_markets.py
- [[dot-test_above_condition()]] - code - tests/test_forecasting.py
- [[dot-test_above_threshold_high_current()]] - code - tests/test_phase4.py
- [[dot-test_above_threshold_low_current()]] - code - tests/test_phase4.py
- [[dot-test_all_summer_months_use_lower_ecmwf()]] - code - tests/test_weather_markets.py
- [[dot-test_all_winter_months_use_high_ecmwf()]] - code - tests/test_weather_markets.py
- [[dot-test_analyze_trade_blends_persistence_for_short_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_below_condition()]] - code - tests/test_forecasting.py
- [[dot-test_below_threshold_low_current()]] - code - tests/test_phase4.py
- [[dot-test_between_condition()]] - code - tests/test_forecasting.py
- [[dot-test_between_returns_reasonable_value()]] - code - tests/test_phase4.py
- [[dot-test_city_weights_used_when_available()]] - code - tests/test_phase4.py
- [[dot-test_dynamic_weights_override_learned()]] - code - tests/test_phase4.py
- [[dot-test_ecmwf_weight_summer()]] - code - tests/test_weather.py
- [[dot-test_ecmwf_weight_winter()]] - code - tests/test_weather.py
- [[dot-test_el_nino_boosts_ecmwf_above_neutral()]] - code - tests/test_phase4.py
- [[dot-test_el_nino_boosts_ecmwf_in_winter()]] - code - tests/test_forecasting.py
- [[dot-test_el_nino_returns_correct_label()]] - code - tests/test_forecasting.py
- [[dot-test_empty_tracker_returns_none()]] - code - tests/test_phase4.py
- [[dot-test_fetch_hrrr_temp_negative_caches_failure()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_hrrr_temp_returns_float_or_none()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_hrrr_temp_returns_max_of_hourly()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_hrrr_temp_returns_none_for_unknown_city()]] - code - tests/test_forecasting.py
- [[dot-test_get_enso_phase_returns_valid_phase()]] - code - tests/test_phase4.py
- [[dot-test_gfs_and_icon_constant()]] - code - tests/test_weather.py
- [[dot-test_gfs_and_icon_weights_are_constant()]] - code - tests/test_weather_markets.py
- [[dot-test_high_mae_model_gets_low_weight()]] - code - tests/test_phase4.py
- [[dot-test_invalid_std_dev_returns_none()]] - code - tests/test_phase4.py
- [[dot-test_la_nina_boosts_ecmwf_above_neutral()]] - code - tests/test_phase4.py
- [[dot-test_la_nina_returns_correct_label()]] - code - tests/test_forecasting.py
- [[dot-test_neutral_returns_correct_label()]] - code - tests/test_forecasting.py
- [[dot-test_neutral_winter_ecmwf_weight()]] - code - tests/test_forecasting.py
- [[dot-test_no_city_falls_back_to_seasonal()]] - code - tests/test_phase4.py
- [[dot-test_no_enso_boost_in_summer()]] - code - tests/test_phase4.py
- [[dot-test_no_tracker_data_returns_none()]] - code - tests/test_phase4.py
- [[dot-test_none_oni_returns_neutral()]] - code - tests/test_forecasting.py
- [[dot-test_partial_tracker_weights_backfilled_from_baseline()]] - code - tests/test_forecasting.py
- [[dot-test_returns_dict_with_expected_keys()_1]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_for_zero_std()]] - code - tests/test_forecasting.py
- [[dot-test_returns_none_when_city_is_none()]] - code - tests/test_forecasting.py
- [[dot-test_returns_none_when_no_tracker_rows()]] - code - tests/test_forecasting.py
- [[dot-test_returns_softmax_weights_from_tracker()]] - code - tests/test_forecasting.py
- [[dot-test_seasonal_fallback_when_no_tracker_rows()]] - code - tests/test_forecasting.py
- [[dot-test_tracker_weights_used_when_available()]] - code - tests/test_forecasting.py
- [[dot-test_unknown_condition_returns_none()]] - code - tests/test_phase4.py
- [[dot-test_used_as_first_priority_in_forecast_model_weights()]] - code - tests/test_forecasting.py
- [[dot-test_winter_month_boosts_ecmwf_weight()]] - code - tests/test_weather_markets.py
- [[A failed fetch must be negative-cached -- a second call within the TTL must not…_1]] - rationale - tests/test_forecasting.py
- [[All summer months (Apr-Sep) should use the lower ECMWF weight.]] - rationale - tests/test_weather_markets.py
- [[All winter months (Oct-Mar) should use the elevated ECMWF weight.…]] - rationale - tests/test_weather_markets.py
- [[Between condition with current value in range → decent probability.]] - rationale - tests/test_phase4.py
- [[City is None → returns None without calling tracker.]] - rationale - tests/test_phase4.py
- [[Current value well above threshold → probability  0.5.]] - rationale - tests/test_phase4.py
- [[Current value well below threshold → probability  0.5.]] - rationale - tests/test_phase4.py
- [[Current value well below threshold → probability  0.5._1]] - rationale - tests/test_phase4.py
- [[Derive per-model blend weights from tracker softmax-MAE data via…]] - rationale - weather_markets.py
- [[Dynamic tracker weights take priority over learned_weights.json.]] - rationale - tests/test_phase4.py
- [[ECMWF should have weight 1.5 in summer months (Apr–Sep).]] - rationale - tests/test_weather.py
- [[ECMWF should have weight 2.5 in winter months (Oct–Mar), ENSO-neutral.]] - rationale - tests/test_weather.py
- [[ECMWF weight should be higher in winter than summer. month=1 is winter, so…]] - rationale - tests/test_weather_markets.py
- [[ENSO should not affect summer weights (not winter).]] - rationale - tests/test_phase4.py
- [[El Niño winter should give ECMWF higher weight than neutral.]] - rationale - tests/test_phase4.py
- [[Empty dict from get_model_weights (no rows) → returns None.]] - rationale - tests/test_phase4.py
- [[Fetch HRRR-derived hourly temperature and return the daily max or min. Uses…]] - rationale - weather_markets.py
- [[GFS and ICON weights should be 1.0 year-round.]] - rationale - tests/test_weather.py
- [[GFS and ICON weights should be 1.0 year-round. Loops every month, including…]] - rationale - tests/test_weather_markets.py
- [[La Niña winter should give ECMWF higher weight than neutral.]] - rationale - tests/test_phase4.py
- [[No city → seasonal fallback (no learned weights lookup).]] - rationale - tests/test_phase4.py
- [[P(N(70, 5)  72) â‰ˆ 0.345.]] - rationale - tests/test_forecasting.py
- [[Phase 4 Improvement Tests]] - code - tests/test_phase4.py
- [[Returns None immediately when city is None (no tracker call needed).]] - rationale - tests/test_forecasting.py
- [[Returns None when get_model_weights returns empty dict (no rows).]] - rationale - tests/test_forecasting.py
- [[Returns get_model_weights result when non-empty.]] - rationale - tests/test_forecasting.py
- [[Seasonal model weights for the daily forecast blend. ECMWF is the most accurate…]] - rationale - weather_markets.py
- [[TestDynamicModelWeights]] - code - tests/test_forecasting.py
- [[TestDynamicModelWeights_1]] - code - tests/test_phase4.py
- [[TestEnsoPhase]] - code - tests/test_forecasting.py
- [[TestEnsoPhase_1]] - code - tests/test_phase4.py
- [[TestForecastModelWeights_1]] - code - tests/test_weather_markets.py
- [[TestForecastModelWeights]] - code - tests/test_weather.py
- [[TestForecastModelWeightsTrackerIntegration]] - code - tests/test_forecasting.py
- [[TestHRRR]] - code - tests/test_forecasting.py
- [[TestPerCityLearnedWeights]] - code - tests/test_phase4.py
- [[TestPersistenceProb]] - code - tests/test_forecasting.py
- [[TestPersistenceProb_1]] - code - tests/test_phase4.py
- [[Tests for Phase 4 improvements (tasks 21, 25, 26, 28, 29, 33, 37, 122,…]] - rationale - tests/test_phase4.py
- [[When learned_weights.json has NYC weights, they're returned for NYC.]] - rationale - tests/test_phase4.py
- [[When tracker data covers only some models (e.g. ECMWF has zero rows for this…]] - rationale - tests/test_forecasting.py
- [[When tracker has 10+ model rows, _forecast_model_weights returns tracker…]] - rationale - tests/test_forecasting.py
- [[When tracker has no rows (empty dict), _forecast_model_weights falls back to…]] - rationale - tests/test_forecasting.py
- [[_dynamic_model_weights()]] - code - weather_markets.py
- [[_fetch_hrrr_temp()]] - code - weather_markets.py
- [[_forecast_model_weights gives ECMWF +0.5 extra during El NiÃ±o winter.]] - rationale - tests/test_forecasting.py
- [[_forecast_model_weights uses _dynamic_model_weights as first priority, falling…]] - rationale - tests/test_forecasting.py
- [[_forecast_model_weights()]] - code - weather_markets.py
- [[_get_enso_phase always returns one of three valid values.]] - rationale - tests/test_phase4.py
- [[_get_enso_phase()]] - code - weather_markets.py
- [[analyze_trade includes persistence at 15% weight when days_out = 2.]] - rationale - tests/test_forecasting.py
- [[get_model_weights result is passed through higher-weight model wins.]] - rationale - tests/test_phase4.py
- [[month=1 is winter, so _forecast_model_weights hits the same live-network…]] - rationale - tests/test_weather_markets.py
- [[persistence_prob()]] - code - climatology.py
- [[test_data_freshness.py (referenced, not in this chunk)]] - code - tests/test_data_freshness.py
- [[test_forecasting.py]] - code - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Forecasting_Persistence_Model_Tests
SORT file.name ASC
```

## Connections to other communities
- 14 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 10 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 6 edges to [[_COMMUNITY_Community 51]]
- 5 edges to [[_COMMUNITY_Community 82]]
- 4 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 4 edges to [[_COMMUNITY_Community 70]]
- 3 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 2 edges to [[_COMMUNITY_Community 26]]
- 2 edges to [[_COMMUNITY_Community 52]]
- 2 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Community 59]]
- 1 edge to [[_COMMUNITY_Community 211]]
- 1 edge to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 146]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Community 423]]
- 1 edge to [[_COMMUNITY_Community 303]]
- 1 edge to [[_COMMUNITY_Community 504]]
- 1 edge to [[_COMMUNITY_Community 545]]
- 1 edge to [[_COMMUNITY_Community 424]]
- 1 edge to [[_COMMUNITY_Community 464]]
- 1 edge to [[_COMMUNITY_Community 276]]
- 1 edge to [[_COMMUNITY_Community 572]]
- 1 edge to [[_COMMUNITY_Community 169]]
- 1 edge to [[_COMMUNITY_Community 275]]
- 1 edge to [[_COMMUNITY_Community 170]]
- 1 edge to [[_COMMUNITY_Community 394]]
- 1 edge to [[_COMMUNITY_Forecast Persistent Cache]]
- 1 edge to [[_COMMUNITY_Kelly Sizing Property-Based Tests]]
- 1 edge to [[_COMMUNITY_Community 142]]
- 1 edge to [[_COMMUNITY_Community 388]]
- 1 edge to [[_COMMUNITY_Community 595]]
- 1 edge to [[_COMMUNITY_Community 407]]
- 1 edge to [[_COMMUNITY_Backtest Engine & Atomic Writes]]

## Top bridge nodes
- [[test_forecasting.py]] - degree 49, connects to 25 communities
- [[Phase 4 Improvement Tests]] - degree 20, connects to 9 communities
- [[_forecast_model_weights()]] - degree 33, connects to 6 communities
- [[_dynamic_model_weights()]] - degree 15, connects to 4 communities
- [[persistence_prob()]] - degree 17, connects to 3 communities