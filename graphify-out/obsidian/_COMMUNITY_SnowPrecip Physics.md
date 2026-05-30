---
type: community
cohesion: 0.05
members: 52
---

# Snow/Precip Physics

**Cohesion:** 0.05 - loosely connected
**Members:** 52 nodes

## Members
- [[34 Convert snow threshold (inches) to liquid water equivalent.]] - rationale - weather_markets.py
- [[34 Empirical SLR from wet-bulb temp (NOAA operational).     32°F → 0 (rain),]] - rationale - weather_markets.py
- [[34 Stull (2011) wet-bulb temperature approximation.]] - rationale - weather_markets.py
- [[.test_20_to_28_range()]] - code - tests/test_forecasting.py
- [[.test_28_to_32_range()]] - code - tests/test_forecasting.py
- [[.test_above_freezing_returns_zero()]] - code - tests/test_forecasting.py
- [[.test_analyze_trade_returns_adjusted_edge_key()]] - code - tests/test_weather_markets.py
- [[.test_below_20_returns_20()]] - code - tests/test_forecasting.py
- [[.test_different_buckets_get_separate_cache_entries()]] - code - tests/test_weather_markets.py
- [[.test_falls_through_to_pirate_when_nbm_and_weatherapi_fail()]] - code - tests/test_weather_markets.py
- [[.test_liquid_equiv_conversion()]] - code - tests/test_forecasting.py
- [[.test_logs_info_when_open_under_24h()]] - code - tests/test_weather_markets.py
- [[.test_logs_warning_when_open_over_24h()]] - code - tests/test_weather_markets.py
- [[.test_no_warning_when_circuit_closed()]] - code - tests/test_weather_markets.py
- [[.test_uses_nbm_when_open_meteo_fails()]] - code - tests/test_weather_markets.py
- [[.test_wet_bulb_temp_midpoint()]] - code - tests/test_forecasting.py
- [[20°F  wet_bulb = 28°F → SLR 15]] - rationale - tests/test_forecasting.py
- [[28°F  wet_bulb = 32°F → SLR 10]] - rationale - tests/test_forecasting.py
- [[Result dict must contain adjusted_edge and edge_confidence_factor.]] - rationale - tests/test_weather_markets.py
- [[TestAdjustedEdgeInAnalyzeTrade]] - code - tests/test_weather_markets.py
- [[TestCheckEnsembleCircuitHealth]] - code - tests/test_weather_markets.py
- [[TestConsensusCacheKeyBetween]] - code - tests/test_weather_markets.py
- [[TestGetWeatherForecastFallbackChain]] - code - tests/test_weather_markets.py
- [[TestSnowLiquidRatio]] - code - tests/test_forecasting.py
- [[Two between-markets with different lowerupper produce distinct keys.]] - rationale - tests/test_weather_markets.py
- [[Unit tests for key functions in weather_markets.py and utils.py.]] - rationale - tests/test_weather_markets.py
- [[_get_consensus_probs cache key must include lowerupper for between-markets.]] - rationale - tests/test_weather_markets.py
- [[_om_rate_limit ensures at least the per-endpoint interval between calls.]] - rationale - tests/test_weather_markets.py
- [[analyze_trade does NOT filter out today's or future markets.]] - rationale - tests/test_weather_markets.py
- [[analyze_trade must return None when target_date is in the past.      Kalshi ke]] - rationale - tests/test_weather_markets.py
- [[analyze_trade result includes model_consensus bool when it returns a result.]] - rationale - tests/test_weather_markets.py
- [[analyze_trade() must return both raw net_edge and adjusted_edge (63).]] - rationale - tests/test_weather_markets.py
- [[check_ensemble_circuit_health() warns when circuit has been open 24h.]] - rationale - tests/test_weather_markets.py
- [[get_weather_forecast() should try NBM + weatherapi before Pirate Weather.]] - rationale - tests/test_weather_markets.py
- [[liquid_equiv_of_snow_threshold()]] - code - weather_markets.py
- [[model_consensus is False when ICON and GFS differ by more than 8pp.]] - rationale - tests/test_weather_markets.py
- [[snow_liquid_ratio()]] - code - weather_markets.py
- [[test_analyze_trade_accepts_today_and_future()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_has_model_consensus_field()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_returns_none_for_past_date_market()]] - code - tests/test_weather_markets.py
- [[test_ensemble_confidence_scale_high_std_reduces_ens_weight()]] - code - tests/test_weather_markets.py
- [[test_model_consensus_false_when_models_disagree()]] - code - tests/test_weather_markets.py
- [[test_om_rate_limit_enforces_interval()]] - code - tests/test_weather_markets.py
- [[test_snow_prob_uses_slr_not_1_to_10()]] - code - tests/test_weather_markets.py
- [[test_snow_to_liquid_ratio_above_freezing()]] - code - tests/test_weather_markets.py
- [[test_snow_to_liquid_ratio_borderline()]] - code - tests/test_weather_markets.py
- [[test_snow_to_liquid_ratio_dry_cold()]] - code - tests/test_weather_markets.py
- [[test_weather_markets.py]] - code - tests/test_weather_markets.py
- [[test_wet_bulb_temp_approximation()]] - code - tests/test_weather_markets.py
- [[wet_bulb = 20°F → SLR 20]] - rationale - tests/test_forecasting.py
- [[wet_bulb_temp returns reasonable value for known input.]] - rationale - tests/test_forecasting.py
- [[wet_bulb_temp()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Snow/Precip_Physics
SORT file.name ASC
```

## Connections to other communities
- 21 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 6 edges to [[_COMMUNITY_Model Weights & Ensemble Blend]]
- 3 edges to [[_COMMUNITY_Kelly Criterion Sizing]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_AB Testing System]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]

## Top bridge nodes
- [[test_weather_markets.py]] - degree 57, connects to 21 communities
- [[snow_liquid_ratio()]] - degree 14, connects to 2 communities
- [[liquid_equiv_of_snow_threshold()]] - degree 9, connects to 2 communities
- [[wet_bulb_temp()]] - degree 8, connects to 2 communities
- [[TestSnowLiquidRatio]] - degree 7, connects to 1 community