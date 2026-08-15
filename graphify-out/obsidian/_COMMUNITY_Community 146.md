---
type: community
cohesion: 0.13
members: 21
---

# Community 146

**Cohesion:** 0.13 - loosely connected
**Members:** 21 nodes

## Members
- [[Fails if a function in paper.pytracker.pyweather_markets.py has zero callers…]] - rationale - tests/test_dead_code_scan.py
- [[Inverse check every allowlisted (file, function) pair must still be an actual…]] - rationale - tests/test_dead_code_scan.py
- [[Remove lines that are entirely a `` comment (leading whitespace then ``)…]] - rationale - tests/test_dead_code_scan.py
- [[Returns (fully_dead, tested_unreachable, possible_dynamic) as (filename,…]] - rationale - tests/test_dead_code_scan.py
- [[True if `name` -- or an import alias of it, e.g. `import name as _name` -- is…]] - rationale - tests/test_dead_code_scan.py
- [[True if `name` appears as a quoted string literal -- e.g. a getattr(module,…]] - rationale - tests/test_dead_code_scan.py
- [[True if an import alias of `name` (`from module import name as alias`) is…]] - rationale - tests/test_dead_code_scan.py
- [[True if the bare, unaliased `name(` is directly called in src.]] - rationale - tests/test_dead_code_scan.py
- [[_alias_called_in()]] - code - tests/test_dead_code_scan.py
- [[_bare_called_in()]] - code - tests/test_dead_code_scan.py
- [[_called_in()]] - code - tests/test_dead_code_scan.py
- [[_module_level_funcs()]] - code - tests/test_dead_code_scan.py
- [[_scan()]] - code - tests/test_dead_code_scan.py
- [[_string_referenced_in()]] - code - tests/test_dead_code_scan.py
- [[_strip_full_comment_lines()]] - code - tests/test_dead_code_scan.py
- [[rAutomated guard against orphaned functions in…]] - rationale - tests/test_dead_code_scan.py
- [[test_dead_code_allowlist_has_no_stale_entries()]] - code - tests/test_dead_code_scan.py
- [[test_dead_code_scan.py]] - code - tests/test_dead_code_scan.py
- [[test_no_new_dead_code_outside_allowlist()]] - code - tests/test_dead_code_scan.py
- [[tracker.get_unselected_bias (dead-code allowlist entry)]] - code - tracker.py
- [[weather_markets._current_forecast_cycle]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_146
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 254]]
- 3 edges to [[_COMMUNITY_Community 494]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 202]]
- 1 edge to [[_COMMUNITY_Community 497]]
- 1 edge to [[_COMMUNITY_Community 162]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 191]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 355]]

## Top bridge nodes
- [[test_dead_code_scan.py]] - degree 26, connects to 10 communities
- [[_called_in()]] - degree 6, connects to 1 community
- [[_scan()]] - degree 6, connects to 1 community
- [[_alias_called_in()]] - degree 5, connects to 1 community
- [[_module_level_funcs()]] - degree 4, connects to 1 community