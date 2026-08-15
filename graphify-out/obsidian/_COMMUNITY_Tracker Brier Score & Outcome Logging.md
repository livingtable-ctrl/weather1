---
type: community
cohesion: 0.05
members: 53
---

# Tracker Brier Score & Outcome Logging

**Cohesion:** 0.05 - loosely connected
**Members:** 53 nodes

## Members
- [[dot-_fake_analysis()]] - code - tests/test_tracker.py
- [[dot-setUp()_13]] - code - tests/test_tracker.py
- [[dot-tearDown()_13]] - code - tests/test_tracker.py
- [[dot-test_bias_insufficient_data()]] - code - tests/test_tracker.py
- [[dot-test_brier_returns_none_when_empty()]] - code - tests/test_tracker.py
- [[dot-test_brier_score()]] - code - tests/test_tracker.py
- [[dot-test_calibration_by_city_empty()]] - code - tests/test_tracker.py
- [[dot-test_calibration_by_city_with_data()]] - code - tests/test_tracker.py
- [[dot-test_calibration_by_type_empty()]] - code - tests/test_tracker.py
- [[dot-test_calibration_by_type_with_data()]] - code - tests/test_tracker.py
- [[dot-test_calibration_trend_empty()]] - code - tests/test_tracker.py
- [[dot-test_export_predictions_csv()]] - code - tests/test_tracker.py
- [[dot-test_export_predictions_csv_empty()]] - code - tests/test_tracker.py
- [[dot-test_log_and_retrieve()]] - code - tests/test_tracker.py
- [[dot-test_log_outcome_replace()]] - code - tests/test_tracker.py
- [[dot-test_log_prediction_falls_back_to_recomputed_days_out_when_absent()]] - code - tests/test_tracker.py
- [[dot-test_log_prediction_uses_analysis_days_out_not_recomputed_utc()]] - code - tests/test_tracker.py
- [[dot-test_no_duplicate_same_day()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_backfills_price_history_on_settlement()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_backfills_trade_history_on_settlement()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_prefers_real_series_ticker_when_present()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_records_finalized()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_skips_already_settled()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_skips_candlestick_fetch_without_open_time()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_skips_open_markets()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_skips_trade_fetch_without_open_time()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_survives_candlestick_backfill_failure()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_survives_trade_history_backfill_failure()]] - code - tests/test_tracker.py
- [[A candlestick-fetch error must never block outcome recording.]] - rationale - tests/test_tracker.py
- [[A trade-history-fetch error must never block outcome recording.]] - rationale - tests/test_tracker.py
- [[Brier score should be computed correctly from outcomes.]] - rationale - tests/test_tracker.py
- [[If a futuredifferent API response ever DOES carry a real series_ticker field,…]] - rationale - tests/test_tracker.py
- [[Logged prediction should appear in get_history().]] - rationale - tests/test_tracker.py
- [[Logging the same ticker twice on the same day should update, not insert.]] - rationale - tests/test_tracker.py
- [[No open_time on the market → skip the fetch cleanly (older malformed responses…]] - rationale - tests/test_tracker.py
- [[No open_time on the market → skip the trade-history fetch cleanly (same guard…]] - rationale - tests/test_tracker.py
- [[P2-C log_outcome refuses to overwrite an existing finalized outcome (by…]] - rationale - tests/test_tracker.py
- [[PUBLIC TRADES REST BACKFILL sync_outcomes should fetch and store the full…]] - rationale - tests/test_tracker.py
- [[Redirect tracker DB to a temp file for each test.]] - rationale - tests/test_tracker.py
- [[TestTracker]] - code - tests/test_tracker.py
- [[When analysis has no days_out key (e.g. a shadowlookup write built from a…]] - rationale - tests/test_tracker.py
- [[brier_score() should return None with no settled outcomes.]] - rationale - tests/test_tracker.py
- [[get_bias() should return 0.0 with fewer samples than min_samples.]] - rationale - tests/test_tracker.py
- [[get_calibration_by_city returns correct Brier + bias per city.]] - rationale - tests/test_tracker.py
- [[get_calibration_by_city returns empty dict with no data.]] - rationale - tests/test_tracker.py
- [[get_calibration_by_type returns correct Brier + bias per condition type.]] - rationale - tests/test_tracker.py
- [[get_calibration_by_type returns empty dict with no data.]] - rationale - tests/test_tracker.py
- [[get_calibration_trend returns empty list with no settled data.]] - rationale - tests/test_tracker.py
- [[log_prediction must store analysisdays_out (analyze_trade's own value,…]] - rationale - tests/test_tracker.py
- [[sync_outcomes should fetch and store full OHLC candlestick history exactly once…]] - rationale - tests/test_tracker.py
- [[sync_outcomes should not double-count already-settled markets.]] - rationale - tests/test_tracker.py
- [[sync_outcomes should not record outcomes for markets still open.]] - rationale - tests/test_tracker.py
- [[sync_outcomes should record YES outcome for a finalized market.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Tracker_Brier_Score__Outcome_Logging
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestTracker]] - degree 29, connects to 1 community