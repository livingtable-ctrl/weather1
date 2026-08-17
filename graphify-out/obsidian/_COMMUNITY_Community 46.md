---
type: community
cohesion: 0.06
members: 43
---

# Community 46

**Cohesion:** 0.06 - loosely connected
**Members:** 43 nodes

## Members
- [[dot-_insert()_1]] - code - tests/test_tracker.py
- [[dot-_insert()_2]] - code - tests/test_tracker.py
- [[dot-_insert()_3]] - code - tests/test_tracker.py
- [[dot-_insert()_4]] - code - tests/test_tracker.py
- [[dot-setUp()_32]] - code - tests/test_tracker.py
- [[dot-setUp()_33]] - code - tests/test_tracker.py
- [[dot-setUp()_34]] - code - tests/test_tracker.py
- [[dot-setUp()_35]] - code - tests/test_tracker.py
- [[dot-tearDown()_31]] - code - tests/test_tracker.py
- [[dot-tearDown()_32]] - code - tests/test_tracker.py
- [[dot-tearDown()_33]] - code - tests/test_tracker.py
- [[dot-tearDown()_34]] - code - tests/test_tracker.py
- [[dot-test_below_min_samples_excluded()]] - code - tests/test_tracker.py
- [[dot-test_brier_values_in_valid_range()]] - code - tests/test_tracker.py
- [[dot-test_checks_each_method_independently()]] - code - tests/test_tracker.py
- [[dot-test_computes_brier_and_directional_accuracy_per_condition_type()]] - code - tests/test_tracker.py
- [[dot-test_condition_types_windowed_independently()]] - code - tests/test_tracker.py
- [[dot-test_empty_db_returns_empty_list()]] - code - tests/test_tracker.py
- [[dot-test_filters_by_method()]] - code - tests/test_tracker.py
- [[dot-test_last_n_empty_returns_none()]] - code - tests/test_tracker.py
- [[dot-test_last_n_greater_than_total_returns_all()]] - code - tests/test_tracker.py
- [[dot-test_last_n_limits_to_most_recent()]] - code - tests/test_tracker.py
- [[dot-test_last_n_none_is_all_time()]] - code - tests/test_tracker.py
- [[dot-test_no_alert_below_min_samples()]] - code - tests/test_tracker.py
- [[dot-test_no_alert_when_healthy()]] - code - tests/test_tracker.py
- [[dot-test_perfect_predictions_full_directional_accuracy()]] - code - tests/test_tracker.py
- [[dot-test_returns_correct_brier_for_seeded_data()]] - code - tests/test_tracker.py
- [[dot-test_warns_when_below_floor()]] - code - tests/test_tracker.py
- [[Brier values must be in 0.0, 1.0.]] - rationale - tests/test_tracker.py
- [[No data → empty list.]] - rationale - tests/test_tracker.py
- [[Seeded prediction prob=0.5, outcome=NO → brier=(0.5-0)2=0.25.]] - rationale - tests/test_tracker.py
- [[TestBrierByConditionTypeRolling]] - code - tests/test_tracker.py
- [[TestBrierScoreLastN]] - code - tests/test_tracker.py
- [[TestCheckConditionTypeWeakness]] - code - tests/test_tracker.py
- [[TestGetBrierOverTime]] - code - tests/test_tracker.py
- [[Tests for brier_score(last_n=N) — last-N settled predictions.]] - rationale - tests/test_tracker.py
- [[Tests for tracker.brier_by_condition_type_rolling() (2026-08-12 investigation…]] - rationale - tests/test_tracker.py
- [[Tests for tracker.check_condition_type_weakness() -- the log-only (never halts)…]] - rationale - tests/test_tracker.py
- [[Tests for tracker.get_brier_over_time().]] - rationale - tests/test_tracker.py
- [[last_n=100 with only 3 predictions behaves the same as all-time.]] - rationale - tests/test_tracker.py
- [[last_n=2 uses only the 2 most recently settled predictions.]] - rationale - tests/test_tracker.py
- [[last_n=5 on empty DB returns None, not 0.0.]] - rationale - tests/test_tracker.py
- [[last_n=None (default) produces the same result as calling without last_n.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_46
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 35]]

## Top bridge nodes
- [[TestBrierByConditionTypeRolling]] - degree 10, connects to 1 community
- [[TestBrierScoreLastN]] - degree 9, connects to 1 community
- [[TestCheckConditionTypeWeakness]] - degree 9, connects to 1 community
- [[TestGetBrierOverTime]] - degree 8, connects to 1 community