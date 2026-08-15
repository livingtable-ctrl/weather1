---
source_file: "tests/test_tracker.py"
type: "code"
community: "Tracker Settlement Sigma & Disputed Rows"
location: "L7298"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Tracker_Settlement_Sigma__Disputed_Rows
---

# ._log_settled()

## Connections
- [[dot-_add_disputed_outlier()]] - `calls` [EXTRACTED]
- [[dot-_analysis()_1]] - `calls` [EXTRACTED]
- [[dot-_seed_baseline()]] - `calls` [EXTRACTED]
- [[dot-_seed_baseline()_1]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_clears_stale_dispute_on_clean_recheck()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_daily_fetch_exception_returns_false_not_raise()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_daily_missing_expiration_value_returns_false()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_daily_non_numeric_expiration_value_returns_false()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_daily_not_finalized_returns_false_no_write()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_daily_reads_expiration_value_regardless_of_var()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_daily_ticker_still_uses_daily_path()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_does_not_mark_disputed_when_matched()]] - `calls` [EXTRACTED]
- [[dot-test_audit_settlement_marks_disputed_on_mismatch()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_below_predictions_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hourly_predictions_counts_only_hourly_tickers()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hourly_predictions_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_next_event_predictions_counts_only_next_event_tickers()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_next_event_predictions_distinct_ticker_not_raw_rows()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_next_event_predictions_distinguishes_both_series()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_next_event_predictions_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_next_event_predictions_ignores_lookalike_series()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_predictions_counts_events_not_ladder_rows()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_predictions_counts_only_hurricane_tickers()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_predictions_distinguishes_basins_and_count_types()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_predictions_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_hurricane_predictions_warns_on_unparseable_ticker()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_market_implied_rain_events_counts_events_not_ladder_rows()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_market_implied_rain_events_counts_only_rain_tickers()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_market_implied_rain_events_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_market_implied_rain_events_requires_implied_mean()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_market_implied_rain_events_warns_on_unparseable_ticker()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_counts_raw_rows_not_distinct_events()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_excludes_between()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_excludes_hurricane_count()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_excludes_hurricane_next_event()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_excludes_rain()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_excludes_snow()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_excludes_storm_order()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_rolling_excludes_between()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_rolling_excludes_hurricane_rows()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_predictions_rolling_excludes_rain_and_snow()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_rain_predictions_counts_only_rain_tickers()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_rain_predictions_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_signal_rows_column_counts_non_null_only()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_signal_rows_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_signal_rows_json_key_counts_present_key_only()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_signal_rows_require_settled_temp_false_counts_rows_without_temp()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_signal_rows_requires_settled_temp_f()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_snow_predictions_counts_events_not_ladder_rows()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_snow_predictions_counts_only_snow_tickers()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_snow_predictions_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_snow_predictions_warns_on_unparseable_ticker()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_storm_order_predictions_counts_only_storm_order_tickers()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_storm_order_predictions_distinct_ticker_not_raw_rows()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_storm_order_predictions_excludes_disputed()]] - `calls` [EXTRACTED]
- [[dot-test_count_settled_storm_order_predictions_ignores_lookalike_series()]] - `calls` [EXTRACTED]
- [[dot-test_get_multiday_calibration_cli_excludes_rain()]] - `calls` [EXTRACTED]
- [[dot-test_get_multiday_calibration_cli_excludes_snow()]] - `calls` [EXTRACTED]
- [[dot-test_get_multiday_calibration_cli_excludes_storm_order()]] - `calls` [EXTRACTED]
- [[dot-test_get_rolling_win_rate_excludes_between()]] - `calls` [EXTRACTED]
- [[dot-test_get_rolling_win_rate_excludes_hurricane_rows()]] - `calls` [EXTRACTED]
- [[dot-test_get_rolling_win_rate_excludes_rain_and_snow()]] - `calls` [EXTRACTED]
- [[dot-test_get_sameday_calibration_cli_excludes_rain()]] - `calls` [EXTRACTED]
- [[dot-test_get_sameday_calibration_cli_excludes_snow()]] - `calls` [EXTRACTED]
- [[dot-test_get_sameday_calibration_cli_excludes_storm_order()]] - `calls` [EXTRACTED]
- [[TestSignalGraduationCounters]] - `method` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Tracker_Settlement_Sigma__Disputed_Rows