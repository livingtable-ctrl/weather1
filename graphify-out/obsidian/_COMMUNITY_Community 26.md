---
type: community
cohesion: 0.05
members: 53
---

# Community 26

**Cohesion:** 0.05 - loosely connected
**Members:** 53 nodes

## Members
- [[28 Return the current ENSO phase 'el_nino', 'la_nina', or 'neutral'. Uses…]] - rationale - weather_markets.py
- [[dot-test_all_summer_months_use_lower_ecmwf()]] - code - tests/test_weather_markets.py
- [[dot-test_all_winter_months_use_high_ecmwf()]] - code - tests/test_weather_markets.py
- [[dot-test_city_weights_used_when_available()]] - code - tests/test_phase4.py
- [[dot-test_dynamic_weights_override_learned()]] - code - tests/test_phase4.py
- [[dot-test_ecmwf_weight_summer()]] - code - tests/test_weather.py
- [[dot-test_ecmwf_weight_winter()]] - code - tests/test_weather.py
- [[dot-test_el_nino_boosts_ecmwf_above_neutral()]] - code - tests/test_phase4.py
- [[dot-test_el_nino_boosts_ecmwf_in_winter()]] - code - tests/test_forecasting.py
- [[dot-test_el_nino_returns_correct_label()]] - code - tests/test_forecasting.py
- [[dot-test_get_enso_phase_returns_valid_phase()]] - code - tests/test_phase4.py
- [[dot-test_gfs_and_icon_constant()]] - code - tests/test_weather.py
- [[dot-test_gfs_and_icon_weights_are_constant()]] - code - tests/test_weather_markets.py
- [[dot-test_la_nina_boosts_ecmwf_above_neutral()]] - code - tests/test_phase4.py
- [[dot-test_la_nina_returns_correct_label()]] - code - tests/test_forecasting.py
- [[dot-test_neutral_returns_correct_label()]] - code - tests/test_forecasting.py
- [[dot-test_neutral_winter_ecmwf_weight()]] - code - tests/test_forecasting.py
- [[dot-test_no_city_falls_back_to_seasonal()]] - code - tests/test_phase4.py
- [[dot-test_no_enso_boost_in_summer()]] - code - tests/test_phase4.py
- [[dot-test_none_oni_returns_neutral()]] - code - tests/test_forecasting.py
- [[dot-test_partial_tracker_weights_backfilled_from_baseline()]] - code - tests/test_forecasting.py
- [[dot-test_returns_dict_with_expected_keys()]] - code - tests/test_weather_markets.py
- [[dot-test_seasonal_fallback_when_no_tracker_rows()]] - code - tests/test_forecasting.py
- [[dot-test_tracker_weights_used_when_available()]] - code - tests/test_forecasting.py
- [[dot-test_winter_month_boosts_ecmwf_weight()]] - code - tests/test_weather_markets.py
- [[All summer months (Apr-Sep) should use the lower ECMWF weight.]] - rationale - tests/test_weather_markets.py
- [[All winter months (Oct-Mar) should use the elevated ECMWF weight.…]] - rationale - tests/test_weather_markets.py
- [[Dynamic tracker weights take priority over learned_weights.json.]] - rationale - tests/test_phase4.py
- [[ECMWF should have weight 1.5 in summer months (Apr–Sep).]] - rationale - tests/test_weather.py
- [[ECMWF should have weight 2.5 in winter months (Oct–Mar), ENSO-neutral.]] - rationale - tests/test_weather.py
- [[ECMWF weight should be higher in winter than summer. month=1 is winter, so…]] - rationale - tests/test_weather_markets.py
- [[ENSO should not affect summer weights (not winter).]] - rationale - tests/test_phase4.py
- [[El Niño winter should give ECMWF higher weight than neutral.]] - rationale - tests/test_phase4.py
- [[GFS and ICON weights should be 1.0 year-round.]] - rationale - tests/test_weather.py
- [[GFS and ICON weights should be 1.0 year-round. Loops every month, including…]] - rationale - tests/test_weather_markets.py
- [[La Niña winter should give ECMWF higher weight than neutral.]] - rationale - tests/test_phase4.py
- [[No city → seasonal fallback (no learned weights lookup).]] - rationale - tests/test_phase4.py
- [[Seasonal model weights for the daily forecast blend. ECMWF is the most accurate…]] - rationale - weather_markets.py
- [[TestEnsoPhase]] - code - tests/test_forecasting.py
- [[TestEnsoPhase_1]] - code - tests/test_phase4.py
- [[TestForecastModelWeights]] - code - tests/test_weather_markets.py
- [[TestForecastModelWeights_1]] - code - tests/test_weather.py
- [[TestForecastModelWeightsTrackerIntegration]] - code - tests/test_forecasting.py
- [[TestPerCityLearnedWeights]] - code - tests/test_phase4.py
- [[When learned_weights.json has NYC weights, they're returned for NYC.]] - rationale - tests/test_phase4.py
- [[When tracker data covers only some models (e.g. ECMWF has zero rows for this…]] - rationale - tests/test_forecasting.py
- [[When tracker has 10+ model rows, _forecast_model_weights returns tracker…]] - rationale - tests/test_forecasting.py
- [[When tracker has no rows (empty dict), _forecast_model_weights falls back to…]] - rationale - tests/test_forecasting.py
- [[_forecast_model_weights gives ECMWF +0.5 extra during El NiÃ±o winter.]] - rationale - tests/test_forecasting.py
- [[_forecast_model_weights()]] - code - weather_markets.py
- [[_get_enso_phase always returns one of three valid values.]] - rationale - tests/test_phase4.py
- [[_get_enso_phase()]] - code - weather_markets.py
- [[month=1 is winter, so _forecast_model_weights hits the same live-network…]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_26
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 4]]
- 5 edges to [[_COMMUNITY_Community 5]]
- 4 edges to [[_COMMUNITY_Community 38]]
- 2 edges to [[_COMMUNITY_Community 9]]
- 2 edges to [[_COMMUNITY_Community 11]]
- 2 edges to [[_COMMUNITY_Community 396]]
- 1 edge to [[_COMMUNITY_Community 417]]
- 1 edge to [[_COMMUNITY_Community 89]]
- 1 edge to [[_COMMUNITY_Community 165]]

## Top bridge nodes
- [[_forecast_model_weights()]] - degree 33, connects to 8 communities
- [[_get_enso_phase()]] - degree 12, connects to 3 communities
- [[TestEnsoPhase]] - degree 8, connects to 2 communities
- [[TestForecastModelWeightsTrackerIntegration]] - degree 5, connects to 2 communities
- [[TestForecastModelWeights]] - degree 8, connects to 1 community