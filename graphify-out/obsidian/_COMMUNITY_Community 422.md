---
type: community
cohesion: 0.32
members: 8
---

# Community 422

**Cohesion:** 0.32 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_already_sqlite_format_passes_through_unchanged()]] - code - tests/test_execution_log.py
- [[dot-test_normalized_value_compares_correctly_against_datetime_now()]] - code - tests/test_execution_log.py
- [[dot-test_normalizes_iso_t_format_to_sqlite_format()]] - code - tests/test_execution_log.py
- [[Return a SQL expression normalizing a mixed-format timestamp column for…]] - rationale - utils.py
- [[TestSqlNormalizeIsoColumn]] - code - tests/test_execution_log.py
- [[The actual bug this exists to prevent an unnormalized ISO-T value sorts higher…]] - rationale - tests/test_execution_log.py
- [[sql_normalize_iso_column()]] - code - utils.py
- [[utils.sql_normalize_iso_column() -- the shared helper both call sites above…]] - rationale - tests/test_execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_422
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 1 edge to [[_COMMUNITY_Community 75]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]

## Top bridge nodes
- [[sql_normalize_iso_column()]] - degree 11, connects to 4 communities
- [[TestSqlNormalizeIsoColumn]] - degree 5, connects to 1 community