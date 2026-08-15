---
type: community
cohesion: 0.03
members: 75
---

# Tracker SQLite Storage Tests

**Cohesion:** 0.03 - loosely connected
**Members:** 75 nodes

## Members
- [[55 Log every analyzed market (traded or not) for bias detection.]] - rationale - tracker.py
- [[55 Mean (forecast_prob - outcome) for untraded markets in this city. KNOWN…]] - rationale - tracker.py
- [[55 Record the outcome for a previously logged analysis attempt.]] - rationale - tracker.py
- [[dot-_log_n()]] - code - tests/test_tracker.py
- [[dot-test_calibration_covariate_fields_absent_stores_null_columns()]] - code - tests/test_tracker.py
- [[dot-test_calibration_covariate_fields_round_trip_through_upsert()]] - code - tests/test_tracker.py
- [[dot-test_calibration_covariate_fields_update_on_reupsert()]] - code - tests/test_tracker.py
- [[dot-test_ecmwf_consensus_gap_prob_absent_stores_null()]] - code - tests/test_tracker.py
- [[dot-test_ecmwf_consensus_gap_prob_round_trips_through_upsert()]] - code - tests/test_tracker.py
- [[dot-test_ecmwf_consensus_gap_prob_updates_on_reupsert()]] - code - tests/test_tracker.py
- [[dot-test_empty_dict_returns_none_not_raise()]] - code - tests/test_tracker.py
- [[dot-test_extracts_fields_and_delegates()]] - code - tests/test_tracker.py
- [[dot-test_gem_presence_does_not_change_baseline_models_softmax()]] - code - tests/test_tracker.py
- [[dot-test_liquidity_edge_scale_absent_stores_null_columns()]] - code - tests/test_tracker.py
- [[dot-test_liquidity_edge_scale_round_trips_through_upsert()]] - code - tests/test_tracker.py
- [[dot-test_malformed_target_date_returns_none_not_raise()]] - code - tests/test_tracker.py
- [[dot-test_market_implied_absent_stores_null_columns()]] - code - tests/test_tracker.py
- [[dot-test_market_implied_round_trips_through_upsert()]] - code - tests/test_tracker.py
- [[dot-test_missing_city_returns_none_without_calling_through()]] - code - tests/test_tracker.py
- [[dot-test_nbm_quantile_prob_absent_stores_null()]] - code - tests/test_tracker.py
- [[dot-test_nbm_quantile_prob_round_trips_through_upsert()]] - code - tests/test_tracker.py
- [[dot-test_nbm_quantile_prob_updates_on_reupsert()]] - code - tests/test_tracker.py
- [[dot-test_purge_old_predictions_keeps_recent()]] - code - tests/test_tracker.py
- [[dot-test_purge_old_predictions_removes_settled()]] - code - tests/test_tracker.py
- [[dot-test_run_trend_none_stores_null_columns()]] - code - tests/test_tracker.py
- [[dot-test_run_trend_round_trips_through_upsert()]] - code - tests/test_tracker.py
- [[dot-test_upsert_updates_market_implied_on_conflict()]] - code - tests/test_tracker.py
- [[dot-test_var_defaults_to_max_when_condition_missing_var()]] - code - tests/test_tracker.py
- [[Bug C fix (backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2)…]] - rationale - tests/test_tracker.py
- [[Grade Audit Module Doc tracker.py]] - document - docs/grade_audit/modules/tracker.md
- [[Opus review finding on the GENERALIZED PER-MODEL ACCURACY TRACKING Pass 2 diff…_1]] - rationale - tests/test_tracker.py
- [[Redirect tracker DB to a temp file for pytest-style tests.]] - rationale - tests/test_tracker.py
- [[SQL = NULL never matches, even a NULL column -- settle_analysis_ attempt must…]] - rationale - tests/test_tracker.py
- [[TestGetForecastRunTrendFromAnalysis]] - code - tests/test_tracker.py
- [[TestGetModelWeightsExcludesTrackingOnlyModels]] - code - tests/test_tracker.py
- [[TestLogPredictionCalibrationCovariateFields]] - code - tests/test_tracker.py
- [[TestLogPredictionEcmwfConsensusGap]] - code - tests/test_tracker.py
- [[TestLogPredictionLiquidityEdgeScale]] - code - tests/test_tracker.py
- [[TestLogPredictionMarketImplied]] - code - tests/test_tracker.py
- [[TestLogPredictionNbmQuantileProb]] - code - tests/test_tracker.py
- [[TestLogPredictionRunTrend]] - code - tests/test_tracker.py
- [[TestRetentionPolicy]] - code - tests/test_tracker.py
- [[Unit tests for tracker.py — SQLite prediction logging, bias, and Brier scoring.…]] - rationale - tests/test_tracker.py
- [[_in_memory_conn()]] - code - tests/test_tracker.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 (review-caught) KXRAINM…]] - rationale - tests/test_tracker.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 (review-caught) the…]] - rationale - tests/test_tracker.py
- [[backlog.txt Snow Step 2 (review-caught, the identical gap rain's own Step 2…]] - rationale - tests/test_tracker.py
- [[fixture_15]] - code
- [[get_forecast_run_trend_from_analysis() extracts citytarget_date days_outvar…]] - rationale - tests/test_tracker.py
- [[get_unselected_bias()]] - code - tracker.py
- [[log_analysis_attempt()]] - code - tracker.py
- [[log_prediction() must persist ecmwf_consensus_gap_prob (backlog.txt 3-WAY…]] - rationale - tests/test_tracker.py
- [[log_prediction() must persist ensemble_spread_fmodel_disagreement_f…]] - rationale - tests/test_tracker.py
- [[log_prediction() must persist implied_meanimplied_sigmafit_residual…]] - rationale - tests/test_tracker.py
- [[log_prediction() must persist liquidity_edge_scalegated_edge (backlog.txt…]] - rationale - tests/test_tracker.py
- [[log_prediction() must persist nbm_quantile_prob (backlog.txt NBM PROBABILISTIC…]] - rationale - tests/test_tracker.py
- [[log_prediction() must persist run_trend's pointsdeltajumpy through the UPSERT…]] - rationale - tests/test_tracker.py
- [[purge_old_predictions keeps predictions within retention_days.]] - rationale - tests/test_tracker.py
- [[purge_old_predictions removes settled predictions older than retention_days.]] - rationale - tests/test_tracker.py
- [[settle_analysis_attempt()]] - code - tracker.py
- [[test_api_edge_realization_returns_list()]] - code - tests/test_tracker.py
- [[test_api_reliability_returns_empty_for_unknown_city()]] - code - tests/test_tracker.py
- [[test_backfill_emos_data_excludes_rain_from_non_force_part1()]] - code - tests/test_tracker.py
- [[test_backfill_emos_data_excludes_snow_from_non_force_part1()]] - code - tests/test_tracker.py
- [[test_composite_indexes_exist()]] - code - tests/test_tracker.py
- [[test_get_unselected_bias_excludes_traded_markets()]] - code - tests/test_tracker.py
- [[test_get_unselected_bias_returns_zero_when_no_data()]] - code - tests/test_tracker.py
- [[test_health_endpoint_returns_ok()]] - code - tests/test_tracker.py
- [[test_log_analysis_attempt_none_target_date_writes_null_not_string()]] - code - tests/test_tracker.py
- [[test_log_analysis_attempt_stores_all_markets()]] - code - tests/test_tracker.py
- [[test_schema_drift.py_1]] - code - tests/test_schema_drift.py
- [[test_settle_analysis_attempt_matches_null_target_date_via_is_null()]] - code - tests/test_tracker.py
- [[test_settlement_client_rebuilds_on_env_change()]] - code - tests/test_tracker.py
- [[test_tracker.py]] - code - tests/test_tracker.py
- [[tmp_db()]] - code - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Tracker_SQLite_Storage_Tests
SORT file.name ASC
```

## Connections to other communities
- 21 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 9 edges to [[_COMMUNITY_Community 36]]
- 4 edges to [[_COMMUNITY_Community 46]]
- 3 edges to [[_COMMUNITY_Community 65]]
- 2 edges to [[_COMMUNITY_Community 135]]
- 2 edges to [[_COMMUNITY_Community 153]]
- 2 edges to [[_COMMUNITY_Community 313]]
- 2 edges to [[_COMMUNITY_Community 39]]
- 2 edges to [[_COMMUNITY_Community 76]]
- 2 edges to [[_COMMUNITY_Community 77]]
- 1 edge to [[_COMMUNITY_Community 128]]
- 1 edge to [[_COMMUNITY_Community 177]]
- 1 edge to [[_COMMUNITY_Community 239]]
- 1 edge to [[_COMMUNITY_Community 264]]
- 1 edge to [[_COMMUNITY_Community 265]]
- 1 edge to [[_COMMUNITY_Tracker Brier Score & Outcome Logging]]
- 1 edge to [[_COMMUNITY_Community 286]]
- 1 edge to [[_COMMUNITY_Community 287]]
- 1 edge to [[_COMMUNITY_Community 288]]
- 1 edge to [[_COMMUNITY_Community 289]]
- 1 edge to [[_COMMUNITY_Tracker Disputed Outcome Restoration]]
- 1 edge to [[_COMMUNITY_Tracker Settlement Sigma & Disputed Rows]]
- 1 edge to [[_COMMUNITY_Community 314]]
- 1 edge to [[_COMMUNITY_Community 315]]
- 1 edge to [[_COMMUNITY_Community 316]]
- 1 edge to [[_COMMUNITY_Community 317]]
- 1 edge to [[_COMMUNITY_Community 318]]
- 1 edge to [[_COMMUNITY_Community 319]]
- 1 edge to [[_COMMUNITY_Community 381]]
- 1 edge to [[_COMMUNITY_Community 411]]
- 1 edge to [[_COMMUNITY_Community 412]]
- 1 edge to [[_COMMUNITY_Community 413]]
- 1 edge to [[_COMMUNITY_Community 436]]
- 1 edge to [[_COMMUNITY_Community 437]]
- 1 edge to [[_COMMUNITY_Community 438]]
- 1 edge to [[_COMMUNITY_Community 439]]
- 1 edge to [[_COMMUNITY_Community 440]]
- 1 edge to [[_COMMUNITY_Community 441]]
- 1 edge to [[_COMMUNITY_Community 487]]
- 1 edge to [[_COMMUNITY_Community 522]]
- 1 edge to [[_COMMUNITY_Community 523]]
- 1 edge to [[_COMMUNITY_Community 524]]
- 1 edge to [[_COMMUNITY_Community 525]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Community 184]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 78]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Community 109]]

## Top bridge nodes
- [[test_tracker.py]] - degree 89, connects to 44 communities
- [[log_analysis_attempt()]] - degree 12, connects to 5 communities
- [[settle_analysis_attempt()]] - degree 8, connects to 3 communities
- [[get_unselected_bias()]] - degree 7, connects to 2 communities
- [[test_backfill_emos_data_excludes_rain_from_non_force_part1()]] - degree 5, connects to 2 communities