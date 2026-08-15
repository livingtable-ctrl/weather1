---
type: community
cohesion: 0.18
members: 14
---

# Community 265

**Cohesion:** 0.18 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-_insert_prediction_and_outcome()]] - code - tests/test_tracker.py
- [[dot-setUp()_11]] - code - tests/test_tracker.py
- [[dot-tearDown()_11]] - code - tests/test_tracker.py
- [[dot-test_midpoint_prediction()]] - code - tests/test_tracker.py
- [[dot-test_no_data_returns_none()]] - code - tests/test_tracker.py
- [[dot-test_perfect_prediction_brier_zero()]] - code - tests/test_tracker.py
- [[dot-test_worst_prediction_brier_one()]] - code - tests/test_tracker.py
- [[Focused tests for tracker.brier_score() (111).]] - rationale - tests/test_tracker.py
- [[Helper log a prediction and its outcome.]] - rationale - tests/test_tracker.py
- [[TestBrierScore]] - code - tests/test_tracker.py
- [[brier_score() returns None when there are no settled predictions.]] - rationale - tests/test_tracker.py
- [[forecast_prob=0.0, outcome=YES → Brier score = 1.]] - rationale - tests/test_tracker.py
- [[forecast_prob=0.5, outcome=NO → Brier = (0.5-0)2 = 0.25.]] - rationale - tests/test_tracker.py
- [[forecast_prob=1.0, outcome=YES → Brier score = 0.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_265
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestBrierScore]] - degree 9, connects to 1 community