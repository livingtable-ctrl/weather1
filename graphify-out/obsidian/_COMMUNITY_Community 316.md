---
type: community
cohesion: 0.17
members: 12
---

# Community 316

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-setUp()_32]] - code - tests/test_tracker.py
- [[dot-tearDown()_32]] - code - tests/test_tracker.py
- [[dot-test_local_hour_column_exists_after_init()]] - code - tests/test_tracker.py
- [[dot-test_log_prediction_succeeds_with_local_hour()]] - code - tests/test_tracker.py
- [[dot-test_schema_version_equals_migration_count()_1]] - code - tests/test_tracker.py
- [[dot-test_user_version_equals_schema_version_after_init()_1]] - code - tests/test_tracker.py
- [[After init_db(), PRAGMA user_version must equal _SCHEMA_VERSION.]] - rationale - tests/test_tracker.py
- [[After init_db(), the predictions table must have the local_hour column.]] - rationale - tests/test_tracker.py
- [[P0-12 — _SCHEMA_VERSION must equal the number of migrations so local_hour…]] - rationale - tests/test_tracker.py
- [[TestSchemaVersionMatchesMigrations_1]] - code - tests/test_tracker.py
- [[_SCHEMA_VERSION must equal len(_MIGRATIONS) — off-by-one leaves last migration…]] - rationale - tests/test_tracker.py
- [[log_prediction must not crash when local_hour is present in analysis dict.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_316
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestSchemaVersionMatchesMigrations_1]] - degree 8, connects to 1 community