---
type: community
cohesion: 0.03
members: 127
---

# Tracker P&L Attribution Tests

**Cohesion:** 0.03 - loosely connected
**Members:** 127 nodes

## Members
- [[110 Write a row to the audit_log table for any manual user action (e.g.…]] - rationale - tracker.py
- [[perf Bulk-insert analysis attempts in a single transaction (much faster than…]] - rationale - tracker.py
- [[Audit stop-loss exits did they save money vs. holding to actual settlement…]] - rationale - tracker.py
- [[Backfill EMOS training data for all settled predictions. Part 1 —…]] - rationale - tracker.py
- [[Brier score and bias broken down by meteorological season (59). Returns…]] - rationale - tracker.py
- [[Brier score segmented by forecast horizon. Returns {same_day brier, 1-2d…]] - rationale - tracker.py
- [[Brier score split by signal tier based on abs(edge) at prediction time. Tiers…]] - rationale - tracker.py
- [[Clear a ticker's disputed flag (opus-review-caught, 2026-08-10)…]] - rationale - tracker.py
- [[Compare today's forecast for target_date against the last few runs. lead=N (N =…]] - rationale - tracker.py
- [[Compute Brier score and win rate grouped by signal_source. Reveals which signal…]] - rationale - tracker.py
- [[Compute pairwise city temperature correlations from recent settled outcomes.…]] - rationale - tracker.py
- [[Correlation-weighted mean forecast error of CORRELATED cities' recent…]] - rationale - tracker.py
- [[Count DISTINCT settled hurricane-season-count events -- (basin, count_type,…]] - rationale - tracker.py
- [[Count DISTINCT settled monthly-snow accrual events (ticker prefix, year,…]] - rationale - tracker.py
- [[Count DISTINCT settled storm-order tickers -- backlog.txt HURRICANE MARKETS…]] - rationale - tracker.py
- [[Count DISTINCT settled time-to-next-event tickers -- backlog.txt HURRICANE…]] - rationale - tracker.py
- [[Count multi-day below-type predictions with a known outcome.]] - rationale - tracker.py
- [[Count multi-day predictions that are actually trainable EMOS rows — ens_mean…]] - rationale - tracker.py
- [[Count multi-day predictions whose outcome settled within the last `weeks`…]] - rationale - tracker.py
- [[Count same-day (days_out=0) predictions with a known outcome.]] - rationale - tracker.py
- [[Count settled KXRAINM monthly-rain predictions (backlog.txt RAIN  SNOW …]] - rationale - tracker.py
- [[Count settled KXTEMPxxxH hourly predictions (backlog.txt HOURLY- DIRECTIONAL…]] - rationale - tracker.py
- [[Delete settled predictions older than retention_days and their outcomes.…]] - rationale - tracker.py
- [[Extract the local hour from a KXTEMPxxxH hourly ticker (e.g.…]] - rationale - weather_markets.py
- [[Fetch daily high (var='max') or low (var='min') from IEM ASOS archive. Uses…]] - rationale - tracker.py
- [[Fetch every IEM ASOS METAR reading on `target_date`'s LOCAL calendar day for…]] - rationale - tracker.py
- [[Fetch observed daily high (var='max') or low (var='min') from Open-Meteo…]] - rationale - tracker.py
- [[Fetch one model's daily max or min from the Previous Runs API. Requests…]] - rationale - tracker.py
- [[Fetch several lead offsets for one model in a single Previous Runs API call.…]] - rationale - tracker.py
- [[Fetch the ASOS reading nearest local `hour` on `target_date`, for KXTEMPxxxH…]] - rationale - tracker.py
- [[Lazily build a KalshiClient from env vars, mirroring main.py's build_client()…]] - rationale - tracker.py
- [[Mark an outcome row as disputed (archiveKalshi settlement mismatch). Disputed…]] - rationale - tracker.py
- [[Mean(forecast_prob - settled_yes) across ALL analyzed markets (55). Returns…]] - rationale - tracker.py
- [[One-off recovery pass for ensemble_member_scores rows logged before…]] - rationale - tracker.py
- [[One-off recovery pass for outcomes.settled_temp_f rows written by…]] - rationale - tracker.py
- [[P&L Attribution Tests]] - code - tests/test_pnl_attribution.py
- [[P2-13 Delete api_requests rows older than days_to_keep. Returns row count…]] - rationale - tracker.py
- [[P9.1 Brier score and sample count grouped by edge_calc_version. Returns…]] - rationale - tracker.py
- [[Per condition-type Brier score, bias, and sample count. Returns…]] - rationale - tracker.py
- [[Per-model MAE filtered to recent predictions, used by learn_seasonal_weights().…]] - rationale - tracker.py
- [[Per-model SIGNED bias (mean predicted - actual), split by var (max min),…]] - rationale - tracker.py
- [[Prediction tracker — SQLite-backed log of every prediction we make. After…]] - rationale - tracker.py
- [[Record whether a forecast source returned usable data for a city today. Uses…]] - rationale - tracker.py
- [[Return average blend-source weights per city from settled predictions.]] - rationale - tracker.py
- [[Return count of settled multi-day predictions per west-coast city. Uses the…]] - rationale - tracker.py
- [[Return mean signed temperature error (predicted - actual) per city from the…]] - rationale - tracker.py
- [[Return mean slippage in cents over the last `days` days, or None if no fills.]] - rationale - tracker.py
- [[Return per-model mean absolute error from ensemble_member_scores over the last…]] - rationale - tracker.py
- [[Return rows for EMOS fitting {ens_mean, ens_var, settled_temp_f}. Excludes…]] - rationale - tracker.py
- [[Return the METARASOS station for a city (matches Kalshi settlement).]] - rationale - weather_markets.py
- [[Return the number of outcomes flagged as disputed (settlement audit mismatch).]] - rationale - tracker.py
- [[Return the recorded outcome for a ticker (True=YES, False=NO), or None if no…]] - rationale - tracker.py
- [[Returns (basin, count_type, season_year) for one of the 5 season- total count…]] - rationale - weather_markets.py
- [[Rolling Brier score AND directional accuracy per condition_type, for one…]] - rationale - tracker.py
- [[Rolling Brier score over a retired method's PROBATION-only predictions…]] - rationale - tracker.py
- [[Rolling Brier score per method over the last `window` settled predictions.…]] - rationale - tracker.py
- [[Save a prediction to the database. Stores both the raw (pre-bias-correction)…]] - rationale - tracker.py
- [[Tests for strategy P&L attribution by signal source.]] - rationale - tests/test_pnl_attribution.py
- [[Warn (never halt) when a (method, condition_type) pair's rolling directional…]] - rationale - tracker.py
- [[Write outcomes.settled_temp_f  settled_value from Kalshi's own settlement data…]] - rationale - tracker.py
- [[_conn()_1]] - code - tracker.py
- [[_fetch_actual_daily_temp()]] - code - tracker.py
- [[_fetch_asos_daily_temp()]] - code - tracker.py
- [[_fetch_asos_hour_temp()]] - code - tracker.py
- [[_fetch_asos_observations()]] - code - tracker.py
- [[_fetch_previous_run_daily()]] - code - tracker.py
- [[_fetch_previous_run_leads()]] - code - tracker.py
- [[_get_settlement_kalshi_client()]] - code - tracker.py
- [[_hurricane_count_key_from_ticker()]] - code - weather_markets.py
- [[_metar_station_for_city()]] - code - weather_markets.py
- [[audit_settlement()]] - code - tracker.py
- [[backfill_daily_temp_settlement()]] - code - tracker.py
- [[backfill_emos_data()]] - code - tracker.py
- [[backfill_ensemble_member_scores_var()]] - code - tracker.py
- [[batch_log_analysis_attempts()]] - code - tracker.py
- [[brier_by_condition_type_rolling()]] - code - tracker.py
- [[brier_score_by_method_rolling()]] - code - tracker.py
- [[brier_score_probation_rolling()]] - code - tracker.py
- [[check_condition_type_weakness()]] - code - tracker.py
- [[count_emos_ready_predictions()]] - code - tracker.py
- [[count_settled_below_predictions()]] - code - tracker.py
- [[count_settled_hourly_predictions()]] - code - tracker.py
- [[count_settled_hurricane_next_event_predictions()]] - code - tracker.py
- [[count_settled_hurricane_predictions()]] - code - tracker.py
- [[count_settled_predictions_rolling()]] - code - tracker.py
- [[count_settled_rain_predictions()]] - code - tracker.py
- [[count_settled_sameday_predictions()]] - code - tracker.py
- [[count_settled_snow_predictions()]] - code - tracker.py
- [[count_settled_storm_order_predictions()]] - code - tracker.py
- [[count_settled_west_coast_multiday()]] - code - tracker.py
- [[date_5]] - code
- [[datetime_3]] - code
- [[fixture_12]] - code
- [[get_analysis_bias()]] - code - tracker.py
- [[get_brier_by_days_out()]] - code - tracker.py
- [[get_brier_by_tier()]] - code - tracker.py
- [[get_brier_by_version()]] - code - tracker.py
- [[get_calibration_by_season()]] - code - tracker.py
- [[get_calibration_by_type()]] - code - tracker.py
- [[get_disputed_count()]] - code - tracker.py
- [[get_dynamic_station_bias()]] - code - tracker.py
- [[get_edge_realization_by_city()]] - code - tracker.py
- [[get_emos_training_data()]] - code - tracker.py
- [[get_forecast_run_trend()]] - code - tracker.py
- [[get_mean_slippage()]] - code - tracker.py
- [[get_member_accuracy()]] - code - tracker.py
- [[get_member_bias()]] - code - tracker.py
- [[get_model_attribution_by_city()]] - code - tracker.py
- [[get_model_brier_scores()]] - code - tracker.py
- [[get_outcome_for_ticker()]] - code - tracker.py
- [[get_pnl_by_signal_source()]] - code - tracker.py
- [[get_recent_city_correlations()]] - code - tracker.py
- [[get_regional_recent_bias()]] - code - tracker.py
- [[get_stop_loss_accuracy()_1]] - code - tracker.py
- [[log_audit()]] - code - tracker.py
- [[log_prediction()]] - code - tracker.py
- [[log_source_attempt()]] - code - tracker.py
- [[mark_outcome_disputed()]] - code - tracker.py
- [[mark_outcome_undisputed()]] - code - tracker.py
- [[parse_ticker_hour()]] - code - weather_markets.py
- [[prune_api_requests()]] - code - tracker.py
- [[prune_old_analysis_attempts()]] - code - tracker.py
- [[purge_old_predictions()]] - code - tracker.py
- [[test_batch_log_analysis_attempts_none_target_date_writes_null()]] - code - tests/test_tracker.py
- [[test_tracker.py_1]] - code - tests/test_tracker.py
- [[tmp_tracker()_1]] - code - tests/test_pnl_attribution.py
- [[tracker.py]] - code - tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Tracker_PL_Attribution_Tests
SORT file.name ASC
```

## Connections to other communities
- 83 edges to [[_COMMUNITY_Community 36]]
- 32 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 31 edges to [[_COMMUNITY_Black Swan Halt State]]
- 29 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 22 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 21 edges to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 15 edges to [[_COMMUNITY_Community 184]]
- 9 edges to [[_COMMUNITY_Community 71]]
- 8 edges to [[_COMMUNITY_Community 384]]
- 8 edges to [[_COMMUNITY_Community 385]]
- 8 edges to [[_COMMUNITY_Community 52]]
- 6 edges to [[_COMMUNITY_Community 494]]
- 5 edges to [[_COMMUNITY_Community 40]]
- 5 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 5 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 4 edges to [[_COMMUNITY_Community 137]]
- 3 edges to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 3 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 3 edges to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 3 edges to [[_COMMUNITY_Community 570]]
- 3 edges to [[_COMMUNITY_Community 582]]
- 3 edges to [[_COMMUNITY_Community 500]]
- 3 edges to [[_COMMUNITY_Community 50]]
- 3 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 2 edges to [[_COMMUNITY_METAR Settlement Monitoring]]
- 2 edges to [[_COMMUNITY_Community 296]]
- 2 edges to [[_COMMUNITY_Community 47]]
- 2 edges to [[_COMMUNITY_Community 78]]
- 2 edges to [[_COMMUNITY_Community 580]]
- 2 edges to [[_COMMUNITY_Community 581]]
- 2 edges to [[_COMMUNITY_Community 533]]
- 2 edges to [[_COMMUNITY_Community 64]]
- 2 edges to [[_COMMUNITY_Community 583]]
- 2 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 483]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 422]]
- 1 edge to [[_COMMUNITY_Community 432]]
- 1 edge to [[_COMMUNITY_Community 237]]
- 1 edge to [[_COMMUNITY_Community 174]]
- 1 edge to [[_COMMUNITY_Community 96]]
- 1 edge to [[_COMMUNITY_Community 74]]
- 1 edge to [[_COMMUNITY_Community 181]]
- 1 edge to [[_COMMUNITY_Community 568]]
- 1 edge to [[_COMMUNITY_Community 146]]
- 1 edge to [[_COMMUNITY_Community 595]]
- 1 edge to [[_COMMUNITY_Community 119]]
- 1 edge to [[_COMMUNITY_Community 388]]
- 1 edge to [[_COMMUNITY_Community 103]]
- 1 edge to [[_COMMUNITY_Community 182]]
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 1 edge to [[_COMMUNITY_Community 194]]
- 1 edge to [[_COMMUNITY_Kelly City Multiplier & Edge Realization]]

## Top bridge nodes
- [[tracker.py]] - degree 162, connects to 33 communities
- [[_conn()_1]] - degree 113, connects to 19 communities
- [[log_prediction()]] - degree 24, connects to 11 communities
- [[audit_settlement()]] - degree 17, connects to 6 communities
- [[backfill_emos_data()]] - degree 14, connects to 5 communities