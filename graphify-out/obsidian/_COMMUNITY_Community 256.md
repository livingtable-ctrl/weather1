---
type: community
cohesion: 0.14
members: 14
---

# Community 256

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-setup_method()_5]] - code - tests/test_execution_log.py
- [[dot-teardown_method()_5]] - code - tests/test_execution_log.py
- [[dot-test_all_migrated_columns_present_on_fresh_db()]] - code - tests/test_execution_log.py
- [[dot-test_genuine_operational_error_is_not_swallowed()]] - code - tests/test_execution_log.py
- [[dot-test_legacy_db_with_all_columns_but_no_version_self_heals()]] - code - tests/test_execution_log.py
- [[dot-test_schema_version_equals_migration_count()]] - code - tests/test_execution_log.py
- [[dot-test_user_version_equals_schema_version_after_init()]] - code - tests/test_execution_log.py
- [[A brand-new DB (no legacy columns baked into CREATE TABLE) must still end up…]] - rationale - tests/test_execution_log.py
- [[A pre-versioning DB already has every column (the old CREATE TABLE included…]] - rationale - tests/test_execution_log.py
- [[After init_log(), PRAGMA user_version must equal _SCHEMA_VERSION.]] - rationale - tests/test_execution_log.py
- [[Mutation-proof check for the actual bug this migration style fixes a real…]] - rationale - tests/test_execution_log.py
- [[TestSchemaVersionMatchesMigrations]] - code - tests/test_execution_log.py
- [[_SCHEMA_VERSION must equal len(_MIGRATIONS) -- off-by-one leaves the last…]] - rationale - tests/test_execution_log.py
- [[backlog.txt execution_log.py's SWALLOWED-ALTER MIGRATIONS vs tracker.py's…]] - rationale - tests/test_execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_256
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]

## Top bridge nodes
- [[TestSchemaVersionMatchesMigrations]] - degree 9, connects to 1 community