---
type: community
cohesion: 0.20
members: 14
---

# Community 243

**Cohesion:** 0.20 - loosely connected
**Members:** 14 nodes

## Members
- [[Automated guard against the config-divergencedead-field bug class. This…]] - rationale - tests/test_config_divergence_guard.py
- [[BotConfig class]] - code - config.py
- [[Every BotConfig field must either be read somewhere outside config.py itself,…]] - rationale - tests/test_config_divergence_guard.py
- [[Fails if the same env var is read via _env_float()_env_int()…]] - rationale - tests/test_config_divergence_guard.py
- [[Map env var name - {(filename, default_literal), ...} across every top-level…]] - rationale - tests/test_config_divergence_guard.py
- [[The inverse check every allowlisted field must still be an actual BotConfig…]] - rationale - tests/test_config_divergence_guard.py
- [[_botconfig_field_names()]] - code - tests/test_config_divergence_guard.py
- [[_has_real_call_site()]] - code - tests/test_config_divergence_guard.py
- [[_numeric_or_str()]] - code - tests/test_config_divergence_guard.py
- [[_scan_env_defaults()]] - code - tests/test_config_divergence_guard.py
- [[test_config_divergence_guard.py]] - code - tests/test_config_divergence_guard.py
- [[test_dead_field_allowlist_has_no_stale_entries()]] - code - tests/test_config_divergence_guard.py
- [[test_every_botconfig_field_has_a_call_site_or_a_documented_reason()]] - code - tests/test_config_divergence_guard.py
- [[test_no_env_var_has_conflicting_hardcoded_defaults()]] - code - tests/test_config_divergence_guard.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_243
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 129]]
- 2 edges to [[_COMMUNITY_Community 297]]
- 1 edge to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 1 edge to [[_COMMUNITY_Community 212]]

## Top bridge nodes
- [[test_config_divergence_guard.py]] - degree 13, connects to 4 communities
- [[BotConfig class]] - degree 3, connects to 2 communities