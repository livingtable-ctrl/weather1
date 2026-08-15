---
type: community
cohesion: 0.02
members: 127
---

# Ensemble Weight Blending Tests

**Cohesion:** 0.02 - loosely connected
**Members:** 127 nodes

## Members
- [[31 _blend_weights scaled by inverse ensemble variance.]] - rationale - weather_markets.py
- [[34 Convert snow threshold (inches) to liquid water equivalent.]] - rationale - weather_markets.py
- [[34 Empirical SLR from wet-bulb temp (NOAA operational). 32°F → 0 (rain),…]] - rationale - weather_markets.py
- [[34 Stull (2011) wet-bulb temperature approximation.]] - rationale - weather_markets.py
- [[dot-_fake_acc()]] - code - tests/test_weather_markets.py
- [[dot-test_20_to_28_range()]] - code - tests/test_forecasting.py
- [[dot-test_28_to_32_range()]] - code - tests/test_forecasting.py
- [[dot-test_above_freezing_returns_zero()]] - code - tests/test_forecasting.py
- [[dot-test_analyze_precip_trade_does_not_set_time_risk()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_analyze_snow_trade_does_not_set_time_risk()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_analyze_trade_returns_adjusted_edge_key()]] - code - tests/test_weather_markets.py
- [[dot-test_below_20_returns_20()]] - code - tests/test_forecasting.py
- [[dot-test_different_buckets_get_separate_cache_entries()]] - code - tests/test_weather_markets.py
- [[dot-test_falls_through_to_pirate_when_nbm_and_weatherapi_fail()]] - code - tests/test_weather_markets.py
- [[dot-test_fetches_member_vote_fraction_probability()]] - code - tests/test_weather_markets.py
- [[dot-test_gem_presence_does_not_change_baseline_models_weights()]] - code - tests/test_weather_markets.py
- [[dot-test_gem_ukmo_cached_but_excluded_from_blend()]] - code - tests/test_weather_markets.py
- [[dot-test_high_ens_std_reduces_ensemble_weight()]] - code - tests/test_forecasting.py
- [[dot-test_liquid_equiv_conversion()]] - code - tests/test_forecasting.py
- [[dot-test_logs_info_when_open_under_24h()]] - code - tests/test_weather_markets.py
- [[dot-test_logs_warning_when_open_over_24h()]] - code - tests/test_weather_markets.py
- [[dot-test_low_ens_std_increases_ensemble_weight()]] - code - tests/test_forecasting.py
- [[dot-test_no_warning_when_circuit_closed()]] - code - tests/test_weather_markets.py
- [[dot-test_none_ens_std_returns_base_weights()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_long_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_medium_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_redistributed_when_unavailable()]] - code - tests/test_forecasting.py
- [[dot-test_nws_weight_short_horizon()]] - code - tests/test_forecasting.py
- [[dot-test_per_model_cache_raw_but_blend_corrected()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_when_fewer_than_five_members()_1]] - code - tests/test_weather_markets.py
- [[dot-test_tier1_before_sleep_tier2_after()]] - code - tests/test_weather_markets.py
- [[dot-test_tier2_skipped_when_circuit_trips_during_tier1()]] - code - tests/test_weather_markets.py
- [[dot-test_uses_nbm_when_open_meteo_fails()]] - code - tests/test_weather_markets.py
- [[dot-test_weights_sum_to_one()_1]] - code - tests/test_forecasting.py
- [[dot-test_weights_sum_to_one()]] - code - tests/test_forecasting.py
- [[dot-test_wet_bulb_temp_midpoint()]] - code - tests/test_forecasting.py
- [[20Â°F  wet_bulb = 28Â°F â†’ SLR 15]] - rationale - tests/test_forecasting.py
- [[28Â°F  wet_bulb = 32Â°F â†’ SLR 10]] - rationale - tests/test_forecasting.py
- [[A forecast dict without a precip_in key (e.g. an older cache entry, or a…]] - rationale - tests/test_weather_markets.py
- [[Decay NWS weight at longer horizons; preserve calibrated weights at days_out=1.…]] - rationale - weather_markets.py
- [[Open-Meteo's free ensemble-api endpoint enforces an undocumented rolling-~60s…]] - rationale - tests/test_weather_markets.py
- [[Opus review finding on the GENERALIZED PER-MODEL ACCURACY TRACKING Pass 2 diff…_1]] - rationale - tests/test_weather_markets.py
- [[Phase 2 Batch K Regression Tests]] - code - tests/test_phase2_batch_k.py
- [[Phase 2 Batch K regression tests P2-24P2-26P2-36P2-39P2-45 —…]] - rationale - tests/test_phase2_batch_k.py
- [[Result dict must contain adjusted_edge and edge_confidence_factor.]] - rationale - tests/test_weather_markets.py
- [[Return (w_ensemble, w_climatology, w_nws). Priority regime override (highest,…]] - rationale - weather_markets.py
- [[Same bug class as test_metar_locked_trade_has_ecmwf_forecast_mean_keys above,…]] - rationale - tests/test_weather_markets.py
- [[Shared enriched-market fixture for the ecmwf_consensus_gap_prob tests below --…]] - rationale - tests/test_weather_markets.py
- [[TestAdjustedEdgeInAnalyzeTrade]] - code - tests/test_weather_markets.py
- [[TestBatchPrewarmEnsembleBiasCorrection]] - code - tests/test_weather_markets.py
- [[TestBatchPrewarmEnsembleRateLimitTiering]] - code - tests/test_weather_markets.py
- [[TestBatchPrewarmEnsembleTrackingOnlyModels]] - code - tests/test_weather_markets.py
- [[TestBlendWeights]] - code - tests/test_forecasting.py
- [[TestCheckEnsembleCircuitHealth]] - code - tests/test_weather_markets.py
- [[TestConfidenceScaledBlendWeights]] - code - tests/test_forecasting.py
- [[TestConsensusCacheKeyBetween]] - code - tests/test_weather_markets.py
- [[TestGetEcmwfAifsProb]] - code - tests/test_weather_markets.py
- [[TestGetWeatherForecastFallbackChain]] - code - tests/test_weather_markets.py
- [[TestPrecipSnowOmitTimeRisk]] - code - tests/test_phase2_batch_k.py
- [[TestSnowLiquidRatio]] - code - tests/test_forecasting.py
- [[TestWeightsFromMaeExcludesTrackingOnlyModels]] - code - tests/test_weather_markets.py
- [[The METAR-locked branch (same-day observation override) skips the model path…]] - rationale - tests/test_weather_markets.py
- [[Two between-markets with different lowerupper produce distinct keys.]] - rationale - tests/test_weather_markets.py
- [[Unit tests for key functions in weather_markets.py and utils.py.]] - rationale - tests/test_weather_markets.py
- [[Verify disagreement flag fires when NWS and ensemble differ by more than 8°F.]] - rationale - tests/test_weather_markets.py
- [[When NWS unavailable, its weight redistributed to ens+clim.]] - rationale - tests/test_forecasting.py
- [[_analyze_precip_trade_analyze_snow_trade must NOT set their own time_risk --…]] - rationale - tests/test_phase2_batch_k.py
- [[_blend_weights()]] - code - weather_markets.py
- [[_confidence_scaled_blend_weights()]] - code - weather_markets.py
- [[_ecmwf_gap_test_enriched()]] - code - tests/test_weather_markets.py
- [[_get_consensus_probs cache key must include lowerupper for between-markets.…]] - rationale - tests/test_weather_markets.py
- [[_get_ecmwf_aifs_prob failing must not abort the trade -- mirrors the existing…]] - rationale - tests/test_weather_markets.py
- [[_get_gem_ukmo_means failing must not abort the trade -- mirrors the existing…]] - rationale - tests/test_weather_markets.py
- [[_nws_days_out_scale()]] - code - weather_markets.py
- [[_om_rate_limit ensures at least the per-endpoint interval between calls.]] - rationale - tests/test_weather_markets.py
- [[_stub_ecmwf_gap_common()]] - code - tests/test_weather_markets.py
- [[analyze_trade does NOT filter out today's or future markets.]] - rationale - tests/test_weather_markets.py
- [[analyze_trade must return None when target_date is in the past. Kalshi keeps…]] - rationale - tests/test_weather_markets.py
- [[analyze_trade result includes model_consensus bool when it returns a result.]] - rationale - tests/test_weather_markets.py
- [[analyze_trade() must return both raw net_edge and adjusted_edge (63).]] - rationale - tests/test_weather_markets.py
- [[backlog.txt FORECAST-CONDITION COVARIATES FOR SIGMA precip_in is already…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt '3-WAY MODEL_CONSENSUS CHECK' _get_ecmwf_aifs_prob must return…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt '3-WAY MODEL_CONSENSUS CHECK' analyze_trade must compute…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2 analyze_trade…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2…_1]] - rationale - tests/test_weather_markets.py
- [[backlog.txt 'TRACK ECMWF FORECAST ACCURACY' analyze_trade must surface BOTH…]] - rationale - tests/test_weather_markets.py
- [[batch_prewarm_ensemble is the actual production path (the ENS batch lines…]] - rationale - tests/test_weather_markets.py
- [[check_ensemble_circuit_health() warns when circuit has been open 24h.]] - rationale - tests/test_weather_markets.py
- [[days_out 4-7 NWS weight must be 0.25.]] - rationale - tests/test_forecasting.py
- [[days_out = 3 NWS weight must be 0.35.]] - rationale - tests/test_forecasting.py
- [[days_out  7 NWS weight must be 0.10.]] - rationale - tests/test_forecasting.py
- [[ecmwf_aifs_prob going None (e.g. below the 5-member floor) must leave…]] - rationale - tests/test_weather_markets.py
- [[ens_std = 2Â°F (tight spread) must increase w_ens vs baseline.]] - rationale - tests/test_forecasting.py
- [[ens_std  8Â°F (high uncertainty) must reduce w_ens vs baseline.]] - rationale - tests/test_forecasting.py
- [[ens_std=None â†’ identical result to _blend_weights.]] - rationale - tests/test_forecasting.py
- [[get_weather_forecast() should try NBM + weatherapi before Pirate Weather.]] - rationale - tests/test_weather_markets.py
- [[liquid_equiv_of_snow_threshold()]] - code - weather_markets.py
- [[model_consensus is False when ICON and GFS differ by more than 8pp.]] - rationale - tests/test_weather_markets.py
- [[snow_liquid_ratio()]] - code - weather_markets.py
- [[test_analyze_trade_accepts_today_and_future()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_captures_ecmwf_forecast_means()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_captures_gem_ukmo_forecast_means()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_computes_ecmwf_consensus_gap_prob()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_ecmwf_consensus_gap_prob_none_when_ecmwf_prob_missing()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_has_model_consensus_field()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_precip_sum_in_none_when_key_missing()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_surfaces_precip_sum_in()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_returns_none_for_past_date_market()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_survives_ecmwf_aifs_prob_fetch_exception()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_survives_gem_ukmo_fetch_exception()]] - code - tests/test_weather_markets.py
- [[test_ensemble_confidence_scale_clamped()]] - code - tests/test_weather_markets.py
- [[test_ensemble_confidence_scale_high_std_reduces_ens_weight()]] - code - tests/test_weather_markets.py
- [[test_ensemble_confidence_scale_no_std_unchanged()]] - code - tests/test_weather_markets.py
- [[test_metar_locked_trade_has_ecmwf_forecast_mean_keys()]] - code - tests/test_weather_markets.py
- [[test_metar_locked_trade_has_nbm_quantile_prob_key()]] - code - tests/test_weather_markets.py
- [[test_model_consensus_false_when_models_disagree()]] - code - tests/test_weather_markets.py
- [[test_model_disagreement_computation()]] - code - tests/test_weather_markets.py
- [[test_om_rate_limit_enforces_interval()]] - code - tests/test_weather_markets.py
- [[test_snow_prob_uses_slr_not_1_to_10()]] - code - tests/test_weather_markets.py
- [[test_snow_to_liquid_ratio_above_freezing()]] - code - tests/test_weather_markets.py
- [[test_snow_to_liquid_ratio_borderline()]] - code - tests/test_weather_markets.py
- [[test_snow_to_liquid_ratio_dry_cold()]] - code - tests/test_weather_markets.py
- [[test_weather_markets.py]] - code - tests/test_weather_markets.py
- [[test_wet_bulb_temp_approximation()]] - code - tests/test_weather_markets.py
- [[wet_bulb = 20Â°F â†’ SLR 20]] - rationale - tests/test_forecasting.py
- [[wet_bulb_temp returns reasonable value for known input.]] - rationale - tests/test_forecasting.py
- [[wet_bulb_temp()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Ensemble_Weight_Blending_Tests
SORT file.name ASC
```

## Connections to other communities
- 32 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 10 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 7 edges to [[_COMMUNITY_Community 131]]
- 5 edges to [[_COMMUNITY_Community 206]]
- 4 edges to [[_COMMUNITY_Community 64]]
- 3 edges to [[_COMMUNITY_Community 51]]
- 3 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 3 edges to [[_COMMUNITY_Community 160]]
- 3 edges to [[_COMMUNITY_Kelly Sizing Property-Based Tests]]
- 3 edges to [[_COMMUNITY_Community 59]]
- 2 edges to [[_COMMUNITY_Community 214]]
- 2 edges to [[_COMMUNITY_Community 282]]
- 2 edges to [[_COMMUNITY_Community 269]]
- 2 edges to [[_COMMUNITY_Community 191]]
- 2 edges to [[_COMMUNITY_Community 348]]
- 2 edges to [[_COMMUNITY_Community 190]]
- 2 edges to [[_COMMUNITY_Community 221]]
- 2 edges to [[_COMMUNITY_Community 70]]
- 2 edges to [[_COMMUNITY_Community 178]]
- 2 edges to [[_COMMUNITY_Community 222]]
- 2 edges to [[_COMMUNITY_Community 137]]
- 2 edges to [[_COMMUNITY_Community 82]]
- 1 edge to [[_COMMUNITY_Community 372]]
- 1 edge to [[_COMMUNITY_Community 173]]
- 1 edge to [[_COMMUNITY_Community 151]]
- 1 edge to [[_COMMUNITY_Community 268]]
- 1 edge to [[_COMMUNITY_Community 446]]
- 1 edge to [[_COMMUNITY_Community 116]]
- 1 edge to [[_COMMUNITY_Community 241]]
- 1 edge to [[_COMMUNITY_Community 414]]
- 1 edge to [[_COMMUNITY_Community 528]]
- 1 edge to [[_COMMUNITY_Community 447]]
- 1 edge to [[_COMMUNITY_Community 558]]
- 1 edge to [[_COMMUNITY_Community 531]]
- 1 edge to [[_COMMUNITY_Community 559]]
- 1 edge to [[_COMMUNITY_Community 321]]
- 1 edge to [[_COMMUNITY_Community 529]]
- 1 edge to [[_COMMUNITY_Community 267]]
- 1 edge to [[_COMMUNITY_Community 349]]
- 1 edge to [[_COMMUNITY_Community 291]]
- 1 edge to [[_COMMUNITY_Community 102]]
- 1 edge to [[_COMMUNITY_Community 561]]
- 1 edge to [[_COMMUNITY_Community 322]]
- 1 edge to [[_COMMUNITY_Community 207]]
- 1 edge to [[_COMMUNITY_Community 490]]
- 1 edge to [[_COMMUNITY_Community 530]]
- 1 edge to [[_COMMUNITY_Community 491]]
- 1 edge to [[_COMMUNITY_Community 560]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 119]]

## Top bridge nodes
- [[test_weather_markets.py]] - degree 112, connects to 42 communities
- [[Phase 2 Batch K Regression Tests]] - degree 11, connects to 6 communities
- [[_blend_weights()]] - degree 19, connects to 4 communities
- [[_confidence_scaled_blend_weights()]] - degree 19, connects to 4 communities
- [[snow_liquid_ratio()]] - degree 12, connects to 2 communities