---
type: community
cohesion: 0.08
members: 24
---

# Community 128

**Cohesion:** 0.08 - loosely connected
**Members:** 24 nodes

## Members
- [[dot-setUp()_41]] - code - tests/test_tracker.py
- [[dot-tearDown()_40]] - code - tests/test_tracker.py
- [[dot-test_count_model_observations_counts_settled_rows_for_model_only()]] - code - tests/test_tracker.py
- [[dot-test_count_model_observations_excludes_unsettled_rows()]] - code - tests/test_tracker.py
- [[dot-test_count_model_observations_zero_for_unknown_model()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_market_implied_rain_events_counts_events_not_ladder_rows()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_market_implied_rain_events_counts_only_rain_tickers()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_market_implied_rain_events_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_market_implied_rain_events_requires_implied_mean()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_market_implied_rain_events_warns_on_unparseable_ticker()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_market_implied_rain_events_zero_when_nothing_logged()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_column_counts_non_null_only()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_excludes_disputed()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_json_key_counts_present_key_only()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_require_settled_temp_false_counts_rows_without_temp()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_requires_exactly_one_of_column_json_key()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_requires_settled_temp_f()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_signal_rows_zero_when_nothing_logged()]] - code - tests/test_tracker.py
- [[New generic counters backing backlog.txt's SIGNAL GRADUATION IS A CONVENTION…]] - rationale - tests/test_tracker.py
- [[Opus-review-caught (2026-08-01) resolve_market_implied_for_analysis() hands…]] - rationale - tests/test_tracker.py
- [[Opus-review-caught bug (2026-07-28) the default require_settled_temp=True…]] - rationale - tests/test_tracker.py
- [[Opus-review-caught gap (matches count_settled_snow_predictions()'s own…]] - rationale - tests/test_tracker.py
- [[TestSignalGraduationCounters]] - code - tests/test_tracker.py
- [[backlog.txt RAIN'S MARKET-IMPLIED DISTRIBUTION ... HAS NO GRADUATIONSAMPLE-…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_128
SORT file.name ASC
```

## Connections to other communities
- 11 edges to [[_COMMUNITY_Tracker Settlement Sigma & Disputed Rows]]
- 2 edges to [[_COMMUNITY_Community 288]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestSignalGraduationCounters]] - degree 23, connects to 3 communities
- [[dot-test_count_settled_market_implied_rain_events_counts_events_not_ladder_rows()]] - degree 3, connects to 1 community
- [[dot-test_count_settled_market_implied_rain_events_counts_only_rain_tickers()]] - degree 3, connects to 1 community
- [[dot-test_count_settled_market_implied_rain_events_warns_on_unparseable_ticker()]] - degree 3, connects to 1 community
- [[dot-test_count_settled_signal_rows_require_settled_temp_false_counts_rows_without_temp()]] - degree 3, connects to 1 community