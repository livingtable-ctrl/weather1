---
type: community
cohesion: 0.18
members: 13
---

# Community 287

**Cohesion:** 0.18 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-_log_and_settle()]] - code - tests/test_tracker.py
- [[dot-setUp()_27]] - code - tests/test_tracker.py
- [[dot-tearDown()_27]] - code - tests/test_tracker.py
- [[dot-test_column_exists_after_init()]] - code - tests/test_tracker.py
- [[dot-test_probation_rolling_isolates_from_non_probation_rows()]] - code - tests/test_tracker.py
- [[dot-test_probation_rolling_none_below_min_samples()]] - code - tests/test_tracker.py
- [[dot-test_upsert_min_merge_probation_write_cannot_reflag_real_row()]] - code - tests/test_tracker.py
- [[dot-test_upsert_min_merge_real_write_clears_probation_flag()]] - code - tests/test_tracker.py
- [[A later real (is_probation=0) write for the same (ticker, date) must clear an…]] - rationale - tests/test_tracker.py
- [[A wildly-wrong non-probation row for the same method must not pollute the…]] - rationale - tests/test_tracker.py
- [[Schema v50 must add is_probation to predictions, and…]] - rationale - tests/test_tracker.py
- [[TestIsProbationColumn]] - code - tests/test_tracker.py
- [[The reverse must not happen a probation write after a real write can never re-…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_287
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestIsProbationColumn]] - degree 10, connects to 1 community