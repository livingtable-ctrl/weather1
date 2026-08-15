---
type: community
cohesion: 0.07
members: 35
---

# Community 65

**Cohesion:** 0.07 - loosely connected
**Members:** 35 nodes

## Members
- [[dot-_mock_response()_1]] - code - tests/test_tracker.py
- [[dot-_mock_response()_2]] - code - tests/test_tracker.py
- [[dot-_mock_response()_3]] - code - tests/test_tracker.py
- [[dot-test_ignores_readings_from_other_days_even_if_closer_in_wall_clock()]] - code - tests/test_tracker.py
- [[dot-test_lead_with_no_data_is_omitted_not_zero()]] - code - tests/test_tracker.py
- [[dot-test_malformed_json_returns_empty_dict_not_raise()]] - code - tests/test_tracker.py
- [[dot-test_max_picks_same_day_peak()]] - code - tests/test_tracker.py
- [[dot-test_min_excludes_next_day_readings()]] - code - tests/test_tracker.py
- [[dot-test_min_excludes_next_day_readings_fall_back()]] - code - tests/test_tracker.py
- [[dot-test_min_excludes_next_day_readings_phoenix_no_dst()]] - code - tests/test_tracker.py
- [[dot-test_min_excludes_next_day_readings_spring_forward()]] - code - tests/test_tracker.py
- [[dot-test_network_failure_returns_empty_dict_not_raise()]] - code - tests/test_tracker.py
- [[dot-test_parses_multiple_leads_from_one_response()]] - code - tests/test_tracker.py
- [[dot-test_picks_reading_at_exact_hour_when_available()]] - code - tests/test_tracker.py
- [[dot-test_picks_reading_nearest_target_hour()]] - code - tests/test_tracker.py
- [[dot-test_request_uses_sts_ets_not_day_params()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_on_fetch_error()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_when_no_readings_for_target_day()]] - code - tests/test_tracker.py
- [[dot-test_uses_max_or_min_per_var_argument()]] - code - tests/test_tracker.py
- [[A colder reading on the following local day must NOT be picked up as the target…]] - rationale - tests/test_tracker.py
- [[A lead the API returns as all-null must be absent from the result, never…]] - rationale - tests/test_tracker.py
- [[A reading from an adjacent local day must never be selected, even if it happens…]] - rationale - tests/test_tracker.py
- [[HIGH markets don't need the next-day extension; peak stays on target day.]] - rationale - tests/test_tracker.py
- [[R-42 _fetch_asos_daily_temp must use precise stsets timestamps, not day1day2…]] - rationale - tests/test_tracker.py
- [[Real METAR reports rarely land exactly on the hour (commonly 51-56 past) --…]] - rationale - tests/test_tracker.py
- [[Requesting leads 3, 4 must return both, read from their own…]] - rationale - tests/test_tracker.py
- [[Same same-day-only rule, exercised on a stationtimezone the fix's own…]] - rationale - tests/test_tracker.py
- [[Same-day-only rule on a 23-hour local day (US DST spring-forward, 2026-03-08 —…]] - rationale - tests/test_tracker.py
- [[Same-day-only rule on a 25-hour local day (US DST fall-back, 2026-11-01 — the…]] - rationale - tests/test_tracker.py
- [[TestFetchAsosDailyTemp]] - code - tests/test_tracker.py
- [[TestFetchAsosHourTemp]] - code - tests/test_tracker.py
- [[TestFetchPreviousRunLeads]] - code - tests/test_tracker.py
- [[The HTTP request must use stsets, never day1day2year1year2.]] - rationale - tests/test_tracker.py
- [[backlog.txt FORECAST RUN-TO-RUN TREND SIGNAL -- _fetch_previous_run_leads…]] - rationale - tests/test_tracker.py
- [[backlog.txt HOURLY-DIRECTIONAL TEMPERATURE MARKETS Step 2 handoff item 3…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_65
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]

## Top bridge nodes
- [[TestFetchAsosDailyTemp]] - degree 9, connects to 1 community
- [[TestFetchAsosHourTemp]] - degree 8, connects to 1 community
- [[TestFetchPreviousRunLeads]] - degree 8, connects to 1 community
- [[dot-test_malformed_json_returns_empty_dict_not_raise()]] - degree 2, connects to 1 community