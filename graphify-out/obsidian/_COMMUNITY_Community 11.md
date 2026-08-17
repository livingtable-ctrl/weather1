---
type: community
cohesion: 0.03
members: 80
---

# Community 11

**Cohesion:** 0.03 - loosely connected
**Members:** 80 nodes

## Members
- [[34 Convert snow threshold (inches) to liquid water equivalent.]] - rationale - weather_markets.py
- [[34 Empirical SLR from wet-bulb temp (NOAA operational). 32°F → 0 (rain),…]] - rationale - weather_markets.py
- [[34 Stull (2011) wet-bulb temperature approximation.]] - rationale - weather_markets.py
- [[dot-test_20_to_28_range()]] - code - tests/test_forecasting.py
- [[dot-test_28_to_32_range()]] - code - tests/test_forecasting.py
- [[dot-test_above_freezing_returns_zero()]] - code - tests/test_forecasting.py
- [[dot-test_below_20_returns_20()]] - code - tests/test_forecasting.py
- [[dot-test_falls_through_to_pirate_when_nbm_and_weatherapi_fail()]] - code - tests/test_weather_markets.py
- [[dot-test_fetches_member_vote_fraction_probability()]] - code - tests/test_weather_markets.py
- [[dot-test_gem_ukmo_cached_but_excluded_from_blend()]] - code - tests/test_weather_markets.py
- [[dot-test_liquid_equiv_conversion()]] - code - tests/test_forecasting.py
- [[dot-test_loader_exception_does_not_crash_analyze_trade()]] - code - tests/test_weather_markets.py
- [[dot-test_per_model_cache_raw_but_blend_corrected()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_none_when_fewer_than_five_members()]] - code - tests/test_weather_markets.py
- [[dot-test_tier1_before_sleep_tier2_after()]] - code - tests/test_weather_markets.py
- [[dot-test_tier2_skipped_when_circuit_trips_during_tier1()]] - code - tests/test_weather_markets.py
- [[dot-test_uses_nbm_when_open_meteo_fails()]] - code - tests/test_weather_markets.py
- [[dot-test_wet_bulb_temp_midpoint()]] - code - tests/test_forecasting.py
- [[20Â°F  wet_bulb = 28Â°F â†’ SLR 15]] - rationale - tests/test_forecasting.py
- [[28Â°F  wet_bulb = 32Â°F â†’ SLR 10]] - rationale - tests/test_forecasting.py
- [[A calibration model on disk must actually correct a METAR-locked above-market…]] - rationale - tests/test_weather_markets.py
- [[A correction whose shift exceeds _ML_CORRECTION_LIMIT (0.30) must be skipped…]] - rationale - tests/test_weather_markets.py
- [[A forecast dict without a precip_in key (e.g. an older cache entry, or a…]] - rationale - tests/test_weather_markets.py
- [[Between markets share the same METAR lock-in formula but weren't part of the…]] - rationale - tests/test_weather_markets.py
- [[If _load_metar_calibration itself raises unexpectedly (bug, not just a bad…]] - rationale - tests/test_weather_markets.py
- [[Minimal enriched dict that reaches analyze_trade's metar_locked branch -- same…]] - rationale - tests/test_weather_markets.py
- [[No calibration file yet (fresh install, or below the 30-row floor) must leave…]] - rationale - tests/test_weather_markets.py
- [[Open-Meteo's free ensemble-api endpoint enforces an undocumented rolling-~60s…]] - rationale - tests/test_weather_markets.py
- [[Regression test for a HIGH finding from both opus reviews (2026-08-16) the…]] - rationale - tests/test_weather_markets.py
- [[Regression test for a HIGH finding from two independent opus reviews…]] - rationale - tests/test_weather_markets.py
- [[TestBatchPrewarmEnsembleBiasCorrection]] - code - tests/test_weather_markets.py
- [[TestBatchPrewarmEnsembleRateLimitTiering]] - code - tests/test_weather_markets.py
- [[TestBatchPrewarmEnsembleTrackingOnlyModels]] - code - tests/test_weather_markets.py
- [[TestGetEcmwfAifsProb]] - code - tests/test_weather_markets.py
- [[TestGetWeatherForecastFallbackChain]] - code - tests/test_weather_markets.py
- [[TestSnowLiquidRatio]] - code - tests/test_forecasting.py
- [[Unit tests for key functions in weather_markets.py and utils.py.]] - rationale - tests/test_weather_markets.py
- [[Verify disagreement flag fires when NWS and ensemble differ by more than 8°F.]] - rationale - tests/test_weather_markets.py
- [[When no calibration model exists, bias_correction must stay 0.0 (not…]] - rationale - tests/test_weather_markets.py
- [[_get_gem_ukmo_means failing must not abort the trade -- mirrors the existing…]] - rationale - tests/test_weather_markets.py
- [[_metar_locked_enriched()]] - code - tests/test_weather_markets.py
- [[_om_rate_limit ensures at least the per-endpoint interval between calls.]] - rationale - tests/test_weather_markets.py
- [[analyze_trade does NOT filter out today's or future markets.]] - rationale - tests/test_weather_markets.py
- [[analyze_trade result includes model_consensus bool when it returns a result.]] - rationale - tests/test_weather_markets.py
- [[backlog.txt FORECAST-CONDITION COVARIATES FOR SIGMA precip_in is already…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt '3-WAY MODEL_CONSENSUS CHECK' _get_ecmwf_aifs_prob must return…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2 analyze_trade…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt 'GENERALIZED PER-MODEL ACCURACY TRACKING' Pass 2…]] - rationale - tests/test_weather_markets.py
- [[backlog.txt 'TRACK ECMWF FORECAST ACCURACY' analyze_trade must surface BOTH…]] - rationale - tests/test_weather_markets.py
- [[batch_prewarm_ensemble is the actual production path (the ENS batch lines…]] - rationale - tests/test_weather_markets.py
- [[get_weather_forecast() should try NBM + weatherapi before Pirate Weather.]] - rationale - tests/test_weather_markets.py
- [[liquid_equiv_of_snow_threshold()]] - code - weather_markets.py
- [[model_consensus is False when ICON and GFS differ by more than 8pp.]] - rationale - tests/test_weather_markets.py
- [[snow_liquid_ratio()]] - code - weather_markets.py
- [[test_analyze_trade_accepts_today_and_future()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_captures_ecmwf_forecast_means()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_captures_gem_ukmo_forecast_means()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_has_model_consensus_field()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_precip_sum_in_none_when_key_missing()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_surfaces_precip_sum_in()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_survives_gem_ukmo_fetch_exception()]] - code - tests/test_weather_markets.py
- [[test_metar_calibration_applied_for_above_market()]] - code - tests/test_weather_markets.py
- [[test_metar_calibration_bias_correction_zero_when_uncorrected()]] - code - tests/test_weather_markets.py
- [[test_metar_calibration_magnitude_capped()]] - code - tests/test_weather_markets.py
- [[test_metar_calibration_no_lock_correction_survives_the_cap()]] - code - tests/test_weather_markets.py
- [[test_metar_calibration_noop_when_no_model_on_disk()]] - code - tests/test_weather_markets.py
- [[test_metar_calibration_records_raw_prob_via_bias_correction()]] - code - tests/test_weather_markets.py
- [[test_metar_calibration_skipped_for_between_market()]] - code - tests/test_weather_markets.py
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
TABLE source_file, type FROM #community/Community_11
SORT file.name ASC
```

## Connections to other communities
- 24 edges to [[_COMMUNITY_Community 5]]
- 6 edges to [[_COMMUNITY_Community 38]]
- 6 edges to [[_COMMUNITY_Community 326]]
- 5 edges to [[_COMMUNITY_Community 213]]
- 5 edges to [[_COMMUNITY_Community 442]]
- 5 edges to [[_COMMUNITY_Community 68]]
- 4 edges to [[_COMMUNITY_Community 53]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 127]]
- 2 edges to [[_COMMUNITY_Community 159]]
- 2 edges to [[_COMMUNITY_Community 174]]
- 2 edges to [[_COMMUNITY_Community 175]]
- 2 edges to [[_COMMUNITY_Community 183]]
- 2 edges to [[_COMMUNITY_Community 185]]
- 2 edges to [[_COMMUNITY_Community 198]]
- 2 edges to [[_COMMUNITY_Community 214]]
- 2 edges to [[_COMMUNITY_Community 26]]
- 2 edges to [[_COMMUNITY_Community 264]]
- 2 edges to [[_COMMUNITY_Community 353]]
- 2 edges to [[_COMMUNITY_Community 405]]
- 2 edges to [[_COMMUNITY_Community 65]]
- 2 edges to [[_COMMUNITY_Community 81]]
- 1 edge to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 122]]
- 1 edge to [[_COMMUNITY_Community 123]]
- 1 edge to [[_COMMUNITY_Community 242]]
- 1 edge to [[_COMMUNITY_Community 262]]
- 1 edge to [[_COMMUNITY_Community 263]]
- 1 edge to [[_COMMUNITY_Community 295]]
- 1 edge to [[_COMMUNITY_Community 327]]
- 1 edge to [[_COMMUNITY_Community 328]]
- 1 edge to [[_COMMUNITY_Community 354]]
- 1 edge to [[_COMMUNITY_Community 402]]
- 1 edge to [[_COMMUNITY_Community 443]]
- 1 edge to [[_COMMUNITY_Community 479]]
- 1 edge to [[_COMMUNITY_Community 480]]
- 1 edge to [[_COMMUNITY_Community 531]]
- 1 edge to [[_COMMUNITY_Community 532]]
- 1 edge to [[_COMMUNITY_Community 586]]
- 1 edge to [[_COMMUNITY_Community 587]]
- 1 edge to [[_COMMUNITY_Community 588]]
- 1 edge to [[_COMMUNITY_Community 589]]
- 1 edge to [[_COMMUNITY_Community 638]]
- 1 edge to [[_COMMUNITY_Community 639]]
- 1 edge to [[_COMMUNITY_Community 640]]
- 1 edge to [[_COMMUNITY_Community 641]]
- 1 edge to [[_COMMUNITY_Community 642]]
- 1 edge to [[_COMMUNITY_Community 653]]
- 1 edge to [[_COMMUNITY_Community 655]]
- 1 edge to [[_COMMUNITY_Community 656]]
- 1 edge to [[_COMMUNITY_Community 657]]
- 1 edge to [[_COMMUNITY_Community 126]]
- 1 edge to [[_COMMUNITY_Community 15]]
- 1 edge to [[_COMMUNITY_Community 737]]
- 1 edge to [[_COMMUNITY_Community 6]]

## Top bridge nodes
- [[test_weather_markets.py]] - degree 122, connects to 54 communities
- [[snow_liquid_ratio()]] - degree 12, connects to 2 communities
- [[TestSnowLiquidRatio]] - degree 8, connects to 2 communities
- [[liquid_equiv_of_snow_threshold()]] - degree 7, connects to 2 communities
- [[wet_bulb_temp()]] - degree 7, connects to 2 communities