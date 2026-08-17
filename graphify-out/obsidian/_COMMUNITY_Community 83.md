---
type: community
cohesion: 0.09
members: 31
---

# Community 83

**Cohesion:** 0.09 - loosely connected
**Members:** 31 nodes

## Members
- [[dot-test_collision_with_explicit_alias_import_still_counts()]] - code - tests/test_dead_code_scan.py
- [[dot-test_real_cross_file_alias_call_is_still_counted()]] - code - tests/test_dead_code_scan.py
- [[dot-test_real_cross_file_bare_call_with_no_collision_is_still_counted()]] - code - tests/test_dead_code_scan.py
- [[dot-test_same_name_collision_in_another_file_is_not_counted_as_a_call()]] - code - tests/test_dead_code_scan.py
- [[Baseline sanity check the normal (no collision) alias-import cross-file call…]] - rationale - tests/test_dead_code_scan.py
- [[Fails if a function in paper.pytracker.pyweather_markets.py has zero callers…]] - rationale - tests/test_dead_code_scan.py
- [[Inverse check every allowlisted (file, function) pair must still be an actual…]] - rationale - tests/test_dead_code_scan.py
- [[Mutation-proof pair to the first test even when another file defines its OWN…]] - rationale - tests/test_dead_code_scan.py
- [[No collision (module_c doesn't define its own `helper`) -- a plain, unaliased…]] - rationale - tests/test_dead_code_scan.py
- [[Path_30]] - code
- [[Remove `def name(...)` so a function's own definition doesn't count as a self-…]] - rationale - tests/test_dead_code_scan.py
- [[Remove lines that are entirely a `` comment (leading whitespace then ``)…]] - rationale - tests/test_dead_code_scan.py
- [[Return (has_real_call, has_string_reference) for `name` (a module-level…]] - rationale - tests/test_dead_code_scan.py
- [[Returns (fully_dead, tested_unreachable, possible_dynamic) as (filename,…]] - rationale - tests/test_dead_code_scan.py
- [[TestSameNameCollisionResolution]] - code - tests/test_dead_code_scan.py
- [[True if `name` -- or an import alias of it, e.g. `import name as _name` -- is…]] - rationale - tests/test_dead_code_scan.py
- [[True if `name` appears as a quoted string literal -- e.g. a getattr(module,…]] - rationale - tests/test_dead_code_scan.py
- [[True if an import alias of `name` (`from module import name as alias`) is…]] - rationale - tests/test_dead_code_scan.py
- [[True if the bare, unaliased `name(` is directly called in src.]] - rationale - tests/test_dead_code_scan.py
- [[_alias_called_in()]] - code - tests/test_dead_code_scan.py
- [[_bare_called_in()]] - code - tests/test_dead_code_scan.py
- [[_called_in()]] - code - tests/test_dead_code_scan.py
- [[_module_level_funcs()]] - code - tests/test_dead_code_scan.py
- [[_resolve_prod_evidence()]] - code - tests/test_dead_code_scan.py
- [[_scan()]] - code - tests/test_dead_code_scan.py
- [[_string_referenced_in()]] - code - tests/test_dead_code_scan.py
- [[_strip_def_line()]] - code - tests/test_dead_code_scan.py
- [[_strip_full_comment_lines()]] - code - tests/test_dead_code_scan.py
- [[backlog.txt TWO FUNCTIONS NAMED _current_forecast_cycle -- this scan used to…]] - rationale - tests/test_dead_code_scan.py
- [[test_dead_code_allowlist_has_no_stale_entries()]] - code - tests/test_dead_code_scan.py
- [[test_no_new_dead_code_outside_allowlist()]] - code - tests/test_dead_code_scan.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_83
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_Community 33]]

## Top bridge nodes
- [[_resolve_prod_evidence()]] - degree 12, connects to 1 community
- [[_called_in()]] - degree 6, connects to 1 community
- [[_scan()]] - degree 6, connects to 1 community
- [[TestSameNameCollisionResolution]] - degree 6, connects to 1 community
- [[_alias_called_in()]] - degree 5, connects to 1 community