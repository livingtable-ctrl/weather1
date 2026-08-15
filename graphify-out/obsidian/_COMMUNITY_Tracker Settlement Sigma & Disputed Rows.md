---
type: community
cohesion: 0.05
members: 53
---

# Tracker Settlement Sigma & Disputed Rows

**Cohesion:** 0.05 - loosely connected
**Members:** 53 nodes

## Members
- [[dot-_log_settled()_1]] - code - tests/test_tracker.py
- [[dot-_log_settled()_2]] - code - tests/test_tracker.py
- [[dot-setUp()_37]] - code - tests/test_tracker.py
- [[dot-tearDown()_37]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_clears_stale_dispute_on_clean_recheck()]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_daily_fetch_exception_returns_false_not_raise()]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_daily_missing_expiration_value_returns_false()]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_daily_non_numeric_expiration_value_returns_false()]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_daily_not_finalized_returns_false_no_write()]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_daily_ticker_still_uses_daily_path()]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_does_not_mark_disputed_when_matched()]] - code - tests/test_tracker.py
- [[dot-test_audit_settlement_marks_disputed_on_mismatch()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_below_predictions_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_hourly_predictions_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_hurricane_next_event_predictions_counts_only_next_event_tickers()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_hurricane_next_event_predictions_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_hurricane_predictions_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_counts_raw_rows_not_distinct_events()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_excludes_between()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_excludes_hurricane_count()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_excludes_hurricane_next_event()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_excludes_rain()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_excludes_snow()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_excludes_storm_order()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_rolling_excludes_between()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_rolling_excludes_hurricane_rows()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_predictions_rolling_excludes_rain_and_snow()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_rain_predictions_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_snow_predictions_counts_events_not_ladder_rows()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_snow_predictions_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_snow_predictions_warns_on_unparseable_ticker()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_storm_order_predictions_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_storm_order_predictions_ignores_lookalike_series()]] - code - tests/test_tracker.py
- [[dot-test_get_rolling_win_rate_excludes_between()]] - code - tests/test_tracker.py
- [[dot-test_get_rolling_win_rate_excludes_hurricane_rows()]] - code - tests/test_tracker.py
- [[dot-test_get_rolling_win_rate_excludes_rain_and_snow()]] - code - tests/test_tracker.py
- [[dot-test_get_sameday_calibration_cli_excludes_rain()]] - code - tests/test_tracker.py
- [[dot-test_get_sameday_calibration_cli_excludes_snow()]] - code - tests/test_tracker.py
- [[dot-test_get_sameday_calibration_cli_excludes_storm_order()]] - code - tests/test_tracker.py
- [[Companion regression an ordinary daily ticker must not be routed through the…]] - rationale - tests/test_tracker.py
- [[Must refuse a non-finalized market even with a valid expiration_value -- proves…]] - rationale - tests/test_tracker.py
- [[Opus-review-caught (2026-08-07) this exclusion list was never extended when…]] - rationale - tests/test_tracker.py
- [[Opus-review-caught (2026-08-07) this feeds paper.is_accuracy_halted(), the…]] - rationale - tests/test_tracker.py
- [[Opus-review-caught gap Denver's KXDENSNOWM ladder has 7 sibling brackets that…]] - rationale - tests/test_tracker.py
- [[Opus-review-caught gap an unparseable settled snow ticker is silently dropped…]] - rationale - tests/test_tracker.py
- [[Same coarse-SQL-LIKE-prefix-vs-series-EXACT-match risk shape the sibling next-…]] - rationale - tests/test_tracker.py
- [[TestLiveTradingGateConditionTypeFilter]] - code - tests/test_tracker.py
- [[backlog.txt COUNT_SETTLED_PREDICTIONS() COUNTS RAW ROWS, NOT DISTINCT…]] - rationale - tests/test_tracker.py
- [[backlog.txt COUNT_SETTLED_PREDICTIONS() HAS NO CONDITION_TYPE FILTER every…]] - rationale - tests/test_tracker.py
- [[backlog.txt DATA-DRIVEN SIGMA FROM SETTLED HISTORY + CLI-REPORT SETTLEMENT…]] - rationale - tests/test_tracker.py
- [[backlog.txt HURRICANE MARKETS -- storm-order model (2026-08-07) same this…]] - rationale - tests/test_tracker.py
- [[backlog.txt HURRICANE MARKETS -- time-to-next-event model (2026-08-07) must…]] - rationale - tests/test_tracker.py
- [[opus-review-caught (2026-08-10) every disputed row in production was flagged…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Tracker_Settlement_Sigma__Disputed_Rows
SORT file.name ASC
```

## Connections to other communities
- 43 edges to [[_COMMUNITY_Tracker Disputed Outcome Restoration]]
- 11 edges to [[_COMMUNITY_Community 128]]
- 2 edges to [[_COMMUNITY_Community 442]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 614]]
- 1 edge to [[_COMMUNITY_Community 616]]
- 1 edge to [[_COMMUNITY_Community 619]]
- 1 edge to [[_COMMUNITY_Community 620]]
- 1 edge to [[_COMMUNITY_Community 621]]
- 1 edge to [[_COMMUNITY_Community 622]]
- 1 edge to [[_COMMUNITY_Community 623]]
- 1 edge to [[_COMMUNITY_Community 624]]
- 1 edge to [[_COMMUNITY_Community 625]]
- 1 edge to [[_COMMUNITY_Community 626]]
- 1 edge to [[_COMMUNITY_Community 627]]
- 1 edge to [[_COMMUNITY_Community 628]]
- 1 edge to [[_COMMUNITY_Community 629]]
- 1 edge to [[_COMMUNITY_Community 630]]
- 1 edge to [[_COMMUNITY_Community 288]]

## Top bridge nodes
- [[dot-_log_settled()_2]] - degree 66, connects to 18 communities
- [[TestLiveTradingGateConditionTypeFilter]] - degree 19, connects to 2 communities
- [[dot-test_count_settled_predictions_counts_raw_rows_not_distinct_events()]] - degree 4, connects to 1 community
- [[dot-test_count_settled_predictions_excludes_hurricane_count()]] - degree 4, connects to 1 community
- [[dot-test_count_settled_predictions_excludes_storm_order()]] - degree 4, connects to 1 community