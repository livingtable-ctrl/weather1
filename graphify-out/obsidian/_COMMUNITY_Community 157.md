---
type: community
cohesion: 0.12
members: 21
---

# Community 157

**Cohesion:** 0.12 - loosely connected
**Members:** 21 nodes

## Members
- [[56 - get_calibration_by_city() must accept condition_type filter.]] - rationale - tests/test_tracker.py
- [[dot-_log()]] - code - tests/test_tracker.py
- [[dot-_log()_1]] - code - tests/test_tracker.py
- [[dot-setUp()_5]] - code - tests/test_tracker.py
- [[dot-setUp()_6]] - code - tests/test_tracker.py
- [[dot-tearDown()_5]] - code - tests/test_tracker.py
- [[dot-tearDown()_6]] - code - tests/test_tracker.py
- [[dot-test_grpb_calib_city_empty_returns_empty_dict()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calib_city_filter_above_only()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calib_city_filter_changes_brier()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calib_city_multi_city()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calib_city_no_filter_includes_all_types()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_does_not_raise_on_offset_close_time()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_does_not_raise_on_z_suffix_close_time()]] - code - tests/test_tracker.py
- [[dot-test_sync_outcomes_skips_market_closed_less_than_1h_ago()]] - code - tests/test_tracker.py
- [[Markets finalized less than 1 hour ago must be skipped (Kalshi may revise).]] - rationale - tests/test_tracker.py
- [[P0-13 — sync_outcomes must not crash on awarenaive datetime subtraction.]] - rationale - tests/test_tracker.py
- [[TestCalibrationByCityConditionTypeGrpB]] - code - tests/test_tracker.py
- [[TestSyncOutcomesDatetimeFix]] - code - tests/test_tracker.py
- [[close_time with +0000 offset must not raise TypeError.]] - rationale - tests/test_tracker.py
- [[close_time with Z suffix must not raise TypeError (aware vs naive mismatch).]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_157
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 35]]

## Top bridge nodes
- [[TestCalibrationByCityConditionTypeGrpB]] - degree 10, connects to 1 community
- [[TestSyncOutcomesDatetimeFix]] - degree 8, connects to 1 community