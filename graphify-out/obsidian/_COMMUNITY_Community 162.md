---
type: community
cohesion: 0.13
members: 20
---

# Community 162

**Cohesion:** 0.13 - loosely connected
**Members:** 20 nodes

## Members
- [[Every .py file in the repo outside the excluded directories above.]] - rationale - tests/test_disputed_row_guard.py
- [[Fails if a function joins the raw outcomes table without a documented reason in…]] - rationale - tests/test_disputed_row_guard.py
- [[Innermost (smallest-span) function containing lineno, or None if the line isn't…]] - rationale - tests/test_disputed_row_guard.py
- [[Inverse check every allowlisted (file, qualname) must still actually join the…]] - rationale - tests/test_disputed_row_guard.py
- [[Module]] - code
- [[Path_5]] - code
- [[Return (relative_file, line_number, enclosing_qualified_function_name) for…]] - rationale - tests/test_disputed_row_guard.py
- [[Return (start_line, end_line, qualified_name) for every…]] - rationale - tests/test_disputed_row_guard.py
- [[Sanity check the view definition itself hasn't been renamedremoved out from…]] - rationale - tests/test_disputed_row_guard.py
- [[_func_for_line()]] - code - tests/test_disputed_row_guard.py
- [[_function_spans()]] - code - tests/test_disputed_row_guard.py
- [[_iter_outcomes_join_sites()]] - code - tests/test_disputed_row_guard.py
- [[_production_py_files()]] - code - tests/test_disputed_row_guard.py
- [[rAutomated guard against a new query anywhere in the repo joining the raw…]] - rationale - tests/test_disputed_row_guard.py
- [[test_config_divergence_guard.py_1]] - code - tests/test_config_divergence_guard.py
- [[test_disputed_row_guard.py]] - code - tests/test_disputed_row_guard.py
- [[test_no_new_raw_outcomes_join_outside_allowlist()]] - code - tests/test_disputed_row_guard.py
- [[test_outcomes_valid_view_exists_in_schema()]] - code - tests/test_disputed_row_guard.py
- [[test_raw_outcomes_allowlist_has_no_stale_entries()]] - code - tests/test_disputed_row_guard.py
- [[tracker.outcomes_valid VIEW (init_db)]] - code - tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_162
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 184]]
- 1 edge to [[_COMMUNITY_Community 355]]
- 1 edge to [[_COMMUNITY_Community 146]]
- 1 edge to [[_COMMUNITY_Community 497]]
- 1 edge to [[_COMMUNITY_Community 202]]

## Top bridge nodes
- [[test_disputed_row_guard.py]] - degree 13, connects to 3 communities
- [[test_config_divergence_guard.py_1]] - degree 3, connects to 2 communities