---
type: community
cohesion: 0.07
members: 42
---

# Community 47

**Cohesion:** 0.07 - loosely connected
**Members:** 42 nodes

## Members
- [[dot-from_env()]] - code - config.py
- [[dot-validate()]] - code - config.py
- [[Automated guard against the config-divergencedead-field bug class. This…]] - rationale - tests/test_config_divergence_guard.py
- [[BotConfig]] - code - config.py
- [[BotConfig class]] - code - config.py
- [[Create a BotConfig reading all env vars fresh. Clears the mtime-gated…]] - rationale - config.py
- [[Create a BotConfig, validate it, and return it. Call at startup.]] - rationale - config.py
- [[Every BotConfig field must either be read somewhere outside config.py itself,…]] - rationale - tests/test_config_divergence_guard.py
- [[Fails if the same env var is read via _env_float()_env_int()…]] - rationale - tests/test_config_divergence_guard.py
- [[Map env var name - {(filename, default_literal), ...} across every top-level…]] - rationale - tests/test_config_divergence_guard.py
- [[Raise ValueError for any invalid configuration combination.]] - rationale - config.py
- [[Reset the singleton and env-var cache — used in tests between runs.]] - rationale - config.py
- [[Return the global BotConfig singleton, loading from env on first call. Must be…]] - rationale - config.py
- [[The inverse check every allowlisted field must still be an actual BotConfig…]] - rationale - tests/test_config_divergence_guard.py
- [[The rate this bot's own trades actually pay (maker fills are $0 on this bot's…]] - rationale - tests/test_config.py
- [[_botconfig_field_names()]] - code - tests/test_config_divergence_guard.py
- [[_has_real_call_site()]] - code - tests/test_config_divergence_guard.py
- [[_numeric_or_str()]] - code - tests/test_config_divergence_guard.py
- [[_scan_env_defaults()]] - code - tests/test_config_divergence_guard.py
- [[breakeven_trigger_pct and max_days_out both read their env var fresh from the…]] - rationale - tests/test_config_validation.py
- [[get_config()]] - code - config.py
- [[load_and_validate()]] - code - config.py
- [[reset_config()]] - code - config.py
- [[test_bot_config_defaults_are_sane()]] - code - tests/test_config_validation.py
- [[test_bot_config_loads_from_env()]] - code - tests/test_config_validation.py
- [[test_config.py]] - code - tests/test_config.py
- [[test_config_divergence_guard.py]] - code - tests/test_config_divergence_guard.py
- [[test_config_validation.py]] - code - tests/test_config_validation.py
- [[test_dead_field_allowlist_has_no_stale_entries()]] - code - tests/test_config_divergence_guard.py
- [[test_drawdown_halt_out_of_range_raises()]] - code - tests/test_config.py
- [[test_every_botconfig_field_has_a_call_site_or_a_documented_reason()]] - code - tests/test_config_divergence_guard.py
- [[test_fee_rate_out_of_range_raises()]] - code - tests/test_config.py
- [[test_maker_fee_rate_defaults_to_zero()]] - code - tests/test_config.py
- [[test_maker_fee_rate_negative_raises()]] - code - tests/test_config.py
- [[test_maker_fee_rate_out_of_range_raises()]] - code - tests/test_config.py
- [[test_min_edge_above_strong_edge_raises()]] - code - tests/test_config.py
- [[test_no_env_var_has_conflicting_hardcoded_defaults()]] - code - tests/test_config_divergence_guard.py
- [[test_paths_module_exports_critical_paths()]] - code - tests/test_config_validation.py
- [[test_valid_config_passes()]] - code - tests/test_config.py
- [[test_validate_config_does_not_exit_in_demo_when_keys_missing()]] - code - tests/test_config_validation.py
- [[test_validate_config_exits_in_prod_when_keys_missing()]] - code - tests/test_config_validation.py
- [[test_validate_config_passes_in_prod_with_keys()]] - code - tests/test_config_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_47
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 6]]
- 3 edges to [[_COMMUNITY_Community 33]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 8]]

## Top bridge nodes
- [[test_config_divergence_guard.py]] - degree 17, connects to 4 communities
- [[BotConfig]] - degree 18, connects to 2 communities
- [[test_config.py]] - degree 11, connects to 2 communities
- [[test_config_validation.py]] - degree 11, connects to 2 communities
- [[load_and_validate()]] - degree 5, connects to 2 communities