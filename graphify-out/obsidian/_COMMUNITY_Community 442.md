---
type: community
cohesion: 0.14
members: 8
---

# Community 442

**Cohesion:** 0.14 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_audit_settlement_hourly_passes_correct_hour_and_uses_hour_fetch()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_hurricane_predictions_counts_events_not_ladder_rows()]] - code - tests/test_tracker.py
- [[dot-test_count_settled_rain_predictions_counts_only_rain_tickers()]] - code - tests/test_tracker.py
- [[dot-test_log_prediction_upsert_already_prevents_raw_duplication()]] - code - tests/test_tracker.py
- [[Documents the real, confirmed-live behavior the test above's docstring relies…]] - rationale - tests/test_tracker.py
- [[Must call the hour-specific fetch (_fetch_asos_hour_temp) with the ticker's…]] - rationale - tests/test_tracker.py
- [[Same raw-row-vs-distinct-event risk count_settled_snow_ predictions() was fixed…]] - rationale - tests/test_tracker.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 handoff item 7 must count…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_442
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Tracker Disputed Outcome Restoration]]
- 2 edges to [[_COMMUNITY_Tracker Settlement Sigma & Disputed Rows]]

## Top bridge nodes
- [[dot-test_count_settled_hurricane_predictions_counts_events_not_ladder_rows()]] - degree 3, connects to 2 communities
- [[dot-test_count_settled_rain_predictions_counts_only_rain_tickers()]] - degree 3, connects to 2 communities
- [[dot-test_audit_settlement_hourly_passes_correct_hour_and_uses_hour_fetch()]] - degree 2, connects to 1 community
- [[dot-test_log_prediction_upsert_already_prevents_raw_duplication()]] - degree 2, connects to 1 community