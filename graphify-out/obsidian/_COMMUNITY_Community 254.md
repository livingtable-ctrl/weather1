---
type: community
cohesion: 0.22
members: 14
---

# Community 254

**Cohesion:** 0.22 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_collision_with_explicit_alias_import_still_counts()]] - code - tests/test_dead_code_scan.py
- [[dot-test_real_cross_file_alias_call_is_still_counted()]] - code - tests/test_dead_code_scan.py
- [[dot-test_real_cross_file_bare_call_with_no_collision_is_still_counted()]] - code - tests/test_dead_code_scan.py
- [[dot-test_same_name_collision_in_another_file_is_not_counted_as_a_call()]] - code - tests/test_dead_code_scan.py
- [[Baseline sanity check the normal (no collision) alias-import cross-file call…]] - rationale - tests/test_dead_code_scan.py
- [[Mutation-proof pair to the first test even when another file defines its OWN…]] - rationale - tests/test_dead_code_scan.py
- [[No collision (module_c doesn't define its own `helper`) -- a plain, unaliased…]] - rationale - tests/test_dead_code_scan.py
- [[Path_13]] - code
- [[Remove `def name(...)` so a function's own definition doesn't count as a self-…]] - rationale - tests/test_dead_code_scan.py
- [[Return (has_real_call, has_string_reference) for `name` (a module-level…]] - rationale - tests/test_dead_code_scan.py
- [[TestSameNameCollisionResolution]] - code - tests/test_dead_code_scan.py
- [[_resolve_prod_evidence()]] - code - tests/test_dead_code_scan.py
- [[_strip_def_line()]] - code - tests/test_dead_code_scan.py
- [[backlog.txt TWO FUNCTIONS NAMED _current_forecast_cycle -- this scan used to…]] - rationale - tests/test_dead_code_scan.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_254
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 146]]

## Top bridge nodes
- [[_resolve_prod_evidence()]] - degree 12, connects to 1 community
- [[TestSameNameCollisionResolution]] - degree 6, connects to 1 community
- [[Path_13]] - degree 6, connects to 1 community
- [[_strip_def_line()]] - degree 3, connects to 1 community