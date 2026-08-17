---
type: community
cohesion: 0.14
members: 24
---

# Community 131

**Cohesion:** 0.14 - loosely connected
**Members:** 24 nodes

## Members
- [[Exact-membership matching (not substring) is deliberate, mirroring the…]] - rationale - tests/test_series_drift.py
- [[Known-dead placeholder series (KNOWN_DEAD_WEATHER_SERIES) must not trigger the…]] - rationale - tests/test_series_drift.py
- [[Matches check_series_drift's own datetime.now(UTC).date() — using local…]] - rationale - tests/test_series_drift.py
- [[Tests for check_series_drift() — once-per-day detection of Kalshi ticker drift…]] - rationale - tests/test_series_drift.py
- [[The real subtlety found on plan review client.get_series_list() returns ALL…]] - rationale - tests/test_series_drift.py
- [[_mock_client()_1]] - code - tests/test_series_drift.py
- [[_today()_1]] - code - tests/test_series_drift.py
- [[backlog.txt HURRICANE MARKETS -- storm-order model (2026-08-07) the 1 new…]] - rationale - tests/test_series_drift.py
- [[backlog.txt HURRICANE MARKETS -- time-to-next-event model (2026-08-07) the 2…]] - rationale - tests/test_series_drift.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 1 a genuinely novelunknown…]] - rationale - tests/test_series_drift.py
- [[test_first_run_creates_state_file()]] - code - tests/test_series_drift.py
- [[test_gated_to_run_once_per_day()]] - code - tests/test_series_drift.py
- [[test_hurricane_next_event_series_present_does_not_warn()]] - code - tests/test_series_drift.py
- [[test_known_dead_series_suppressed()]] - code - tests/test_series_drift.py
- [[test_known_untracked_rain_series_suppressed()]] - code - tests/test_series_drift.py
- [[test_missing_ticker_counter_increments_and_warns_at_three()]] - code - tests/test_series_drift.py
- [[test_missing_ticker_does_not_warn_before_three_days()]] - code - tests/test_series_drift.py
- [[test_never_raises_when_get_series_list_throws()]] - code - tests/test_series_drift.py
- [[test_recovered_ticker_resets_counter()]] - code - tests/test_series_drift.py
- [[test_series_drift.py]] - code - tests/test_series_drift.py
- [[test_storm_order_series_present_does_not_warn()]] - code - tests/test_series_drift.py
- [[test_unknown_live_ticker_warns_immediately()]] - code - tests/test_series_drift.py
- [[test_unknown_rain_ticker_warns_immediately()]] - code - tests/test_series_drift.py
- [[test_unrecognized_hurricane_series_deliberately_not_flagged()]] - code - tests/test_series_drift.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_131
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 3]]

## Top bridge nodes
- [[test_series_drift.py]] - degree 21, connects to 2 communities