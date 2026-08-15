---
type: community
cohesion: 0.11
members: 23
---

# Community 135

**Cohesion:** 0.11 - loosely connected
**Members:** 23 nodes

## Members
- [[dot-_add()]] - code - tests/test_tracker.py
- [[dot-test_get_sameday_calibration_still_includes_between()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_bucket_grouping()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_empty()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_excludes_between()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_excludes_sameday_rows()]] - code - tests/test_tracker.py
- [[dot-test_returns_dict_with_settled_data()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_with_no_data()]] - code - tests/test_tracker.py
- [[dot-test_sameday_calibration_cli_empty()]] - code - tests/test_tracker.py
- [[dot-test_sameday_calibration_cli_excludes_between()]] - code - tests/test_tracker.py
- [[dot-test_sameday_calibration_cli_excludes_multiday_rows()]] - code - tests/test_tracker.py
- [[dot-test_small_sample_has_wider_interval_than_large_sample()]] - code - tests/test_tracker.py
- [[A days_out=0 row must not appear in the multiday population.]] - rationale - tests/test_tracker.py
- [[A days_out=1 row must not appear in the sameday population.]] - rationale - tests/test_tracker.py
- [[Dashboard-facing get_sameday_calibration() must NOT change behavior — it still…]] - rationale - tests/test_tracker.py
- [[Helper log prediction + outcome.]] - rationale - tests/test_tracker.py
- [[Regression for the 69-row scenario found in production data 'between' sameday…]] - rationale - tests/test_tracker.py
- [[Rows land in the correct 0.2-wide probability buckets.]] - rationale - tests/test_tracker.py
- [[TestCliCalibrationSplit]] - code - tests/test_tracker.py
- [[TestGetRollingWinRateCI]] - code - tests/test_tracker.py
- [[Tests for get_multiday_calibration_cli()  get_sameday_calibration_cli() and a…]] - rationale - tests/test_tracker.py
- [[condition_type='between' rows must not affect nbrier.]] - rationale - tests/test_tracker.py
- [[get_rolling_win_rate_ci() pairs get_rolling_win_rate's real (win_rate, count)…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_135
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 313]]
- 3 edges to [[_COMMUNITY_Community 436]]
- 3 edges to [[_COMMUNITY_Community 487]]
- 3 edges to [[_COMMUNITY_Community 438]]
- 3 edges to [[_COMMUNITY_Community 439]]
- 2 edges to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 2 edges to [[_COMMUNITY_Community 437]]
- 1 edge to [[_COMMUNITY_Community 411]]
- 1 edge to [[_COMMUNITY_Community 315]]

## Top bridge nodes
- [[dot-_add()]] - degree 27, connects to 8 communities
- [[TestCliCalibrationSplit]] - degree 11, connects to 2 communities
- [[TestGetRollingWinRateCI]] - degree 6, connects to 2 communities