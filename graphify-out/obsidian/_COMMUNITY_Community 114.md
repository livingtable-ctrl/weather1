---
type: community
cohesion: 0.14
members: 25
---

# Community 114

**Cohesion:** 0.14 - loosely connected
**Members:** 25 nodes

## Members
- [[dot-setup_method()_28]] - code - tests/test_mos_nbs.py
- [[dot-setup_method()_27]] - code - tests/test_mos_nbs.py
- [[dot-test_eastern_station_00z_is_max_12z_is_min()]] - code - tests/test_mos_nbs.py
- [[dot-test_max_min_assignment_is_not_arbitrary()_1]] - code - tests/test_mos_nbs.py
- [[dot-test_min_var_does_not_return_the_max_value()]] - code - tests/test_mos_nbs.py
- [[dot-test_network_failure_returns_none_and_caches_the_miss()_1]] - code - tests/test_mos_nbs.py
- [[dot-test_off_cycle_txn_rows_are_skipped()]] - code - tests/test_mos_nbs.py
- [[dot-test_pacific_station_same_00z_max_12z_min_rule()]] - code - tests/test_mos_nbs.py
- [[dot-test_returns_max_for_covered_date()]] - code - tests/test_mos_nbs.py
- [[dot-test_returns_none_for_uncovered_date()_1]] - code - tests/test_mos_nbs.py
- [[dot-test_rows_without_txn_are_skipped()]] - code - tests/test_mos_nbs.py
- [[dot-test_single_fetch_serves_both_station_and_tz_repeat_calls()]] - code - tests/test_mos_nbs.py
- [[A txn value on a row that isn't exactly 00Z12Z-ending is dropped defensively…]] - rationale - tests/test_mos_nbs.py
- [[Build a fake mos.json payload shaped like the real IEM API.]] - rationale - tests/test_mos_nbs.py
- [[Live-verified pattern (KNYC, 2026-07-17) 00Z-ending row is the higher value…]] - rationale - tests/test_mos_nbs.py
- [[Mutation-proof if the 00Z12Z - maxmin assignment were flipped, this test…]] - rationale - tests/test_mos_nbs.py
- [[Mutation-proof requesting var='min' on a date that only has a max entry must…_1]] - rationale - tests/test_mos_nbs.py
- [[One station covers a fixed timezone in practice; repeat calls for the same…]] - rationale - tests/test_mos_nbs.py
- [[TestFetchNbmIem]] - code - tests/test_mos_nbs.py
- [[TestFetchNbsDailyExtremes]] - code - tests/test_mos_nbs.py
- [[Tests for mos.py's NBS (real NBM via IEM) parsing -- the core logic behind…]] - rationale - tests/test_mos_nbs.py
- [[The 00Z=max12Z=min assignment must hold for Pacific too (live- verified KLAX,…]] - rationale - tests/test_mos_nbs.py
- [[_mock_nbs_response()]] - code - tests/test_mos_nbs.py
- [[_row()]] - code - tests/test_mos_nbs.py
- [[test_mos_nbs.py]] - code - tests/test_mos_nbs.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_114
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 99]]
- 1 edge to [[_COMMUNITY_Community 182]]

## Top bridge nodes
- [[test_mos_nbs.py]] - degree 9, connects to 2 communities