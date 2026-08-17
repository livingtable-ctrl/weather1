---
type: community
cohesion: 0.05
members: 51
---

# Community 33

**Cohesion:** 0.05 - loosely connected
**Members:** 51 nodes

## Members
- [[Between-Market METAR Lock-in Daily-Extreme Bug]] - document - docs/grade_audit/modules/weather_markets.md
- [[Every .py file in the repo outside the excluded directories above.]] - rationale - tests/test_disputed_row_guard.py
- [[Every _ALLOWLIST entry must name a real file, a positive expected count, and a…]] - rationale - tests/test_paths_bypass_guard.py
- [[Fails if a function calls date.today() without a documented reason in…]] - rationale - tests/test_date_today_guard.py
- [[Fails if a function joins the raw outcomes table without a documented reason in…]] - rationale - tests/test_disputed_row_guard.py
- [[Grade Audit Module Doc weather_markets.py]] - document - docs/grade_audit/modules/weather_markets.md
- [[Innermost (smallest-span) function containing lineno, or None if the line isn't…]] - rationale - tests/test_disputed_row_guard.py
- [[Inverse check every allowlisted (file, qualname) must still actually join the…]] - rationale - tests/test_disputed_row_guard.py
- [[Inverse check every allowlisted function must still actually call date.today()…]] - rationale - tests/test_date_today_guard.py
- [[Module]] - code
- [[No .py file anywhere in the repo should construct its own data path locally.…]] - rationale - tests/test_paths_bypass_guard.py
- [[Path_12]] - code
- [[Path_13]] - code
- [[Path_14]] - code
- [[Regression for an opus-review finding on this guard Python 3.12+ tokenizes…]] - rationale - tests/test_date_today_guard.py
- [[Regression this guard's own first version flagged a false positive on…]] - rationale - tests/test_date_today_guard.py
- [[Return (file, line_number, enclosing_function_name) for every date.today() call…]] - rationale - tests/test_date_today_guard.py
- [[Return (relative_file, line_number, enclosing_qualified_function_name) for…]] - rationale - tests/test_disputed_row_guard.py
- [[Return (start_line, end_line, qualified_name) for every…]] - rationale - tests/test_disputed_row_guard.py
- [[Return source lines with every STRINGCOMMENTf-string-text token blanked out…]] - rationale - tests/test_date_today_guard.py
- [[Sanity check the view definition itself hasn't been renamedremoved out from…]] - rationale - tests/test_disputed_row_guard.py
- [[The positive-case sibling to the above a real date.today() call interpolated…]] - rationale - tests/test_date_today_guard.py
- [[_all_source_files()]] - code - tests/test_paths_bypass_guard.py
- [[_code_only_lines()]] - code - tests/test_date_today_guard.py
- [[_func_for_line()]] - code - tests/test_disputed_row_guard.py
- [[_function_spans()]] - code - tests/test_disputed_row_guard.py
- [[_iter_date_today_sites()]] - code - tests/test_date_today_guard.py
- [[_iter_outcomes_join_sites()]] - code - tests/test_disputed_row_guard.py
- [[_production_py_files()]] - code - tests/test_disputed_row_guard.py
- [[backlog.txt]] - document - backlog.txt
- [[io]] - concept
- [[rAutomated guard against a new query anywhere in the repo joining the raw…]] - rationale - tests/test_disputed_row_guard.py
- [[rAutomated guard against new date.today() usage in production code…]] - rationale - tests/test_date_today_guard.py
- [[rAutomated guard against orphaned functions in…]] - rationale - tests/test_dead_code_scan.py
- [[rAutomated guard against the paths.py-bypass anti-pattern reappearing.…]] - rationale - tests/test_paths_bypass_guard.py
- [[test_allowlist_entries_still_exist_and_are_justified()]] - code - tests/test_paths_bypass_guard.py
- [[test_date_today_allowlist_has_no_stale_entries()]] - code - tests/test_date_today_guard.py
- [[test_date_today_guard.py]] - code - tests/test_date_today_guard.py
- [[test_dead_code_scan.py]] - code - tests/test_dead_code_scan.py
- [[test_disputed_row_guard.py]] - code - tests/test_disputed_row_guard.py
- [[test_docstring_mention_of_date_today_is_not_a_false_positive()]] - code - tests/test_date_today_guard.py
- [[test_fstring_prose_mention_is_not_a_false_positive()]] - code - tests/test_date_today_guard.py
- [[test_fstring_real_call_is_still_caught()]] - code - tests/test_date_today_guard.py
- [[test_no_new_date_today_outside_allowlist()]] - code - tests/test_date_today_guard.py
- [[test_no_new_paths_py_bypass_sites()]] - code - tests/test_paths_bypass_guard.py
- [[test_no_new_raw_outcomes_join_outside_allowlist()]] - code - tests/test_disputed_row_guard.py
- [[test_outcomes_valid_view_exists_in_schema()]] - code - tests/test_disputed_row_guard.py
- [[test_paths_bypass_guard.py]] - code - tests/test_paths_bypass_guard.py
- [[test_raw_outcomes_allowlist_has_no_stale_entries()]] - code - tests/test_disputed_row_guard.py
- [[teststest_phase2_batch_c.py]] - code - tests/test_phase2_batch_c.py
- [[weather_markets._current_forecast_cycle]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_33
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_Community 83]]
- 6 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Community 175]]
- 1 edge to [[_COMMUNITY_Community 23]]
- 1 edge to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 460]]
- 1 edge to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 163]]
- 1 edge to [[_COMMUNITY_Community 238]]
- 1 edge to [[_COMMUNITY_Community 31]]
- 1 edge to [[_COMMUNITY_Community 38]]
- 1 edge to [[_COMMUNITY_Community 42]]
- 1 edge to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 6]]
- 1 edge to [[_COMMUNITY_Community 226]]
- 1 edge to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[Grade Audit Module Doc weather_markets.py]] - degree 9, connects to 7 communities
- [[test_dead_code_scan.py]] - degree 22, connects to 6 communities
- [[backlog.txt]] - degree 8, connects to 4 communities
- [[test_date_today_guard.py]] - degree 14, connects to 2 communities
- [[test_disputed_row_guard.py]] - degree 12, connects to 2 communities