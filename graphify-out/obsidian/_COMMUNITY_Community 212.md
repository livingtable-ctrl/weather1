---
type: community
cohesion: 0.14
members: 16
---

# Community 212

**Cohesion:** 0.14 - loosely connected
**Members:** 16 nodes

## Members
- [[dot-from_env()]] - code - config.py
- [[Create a BotConfig reading all env vars fresh. Clears the mtime-gated…]] - rationale - config.py
- [[Create a BotConfig, validate it, and return it. Call at startup.]] - rationale - config.py
- [[Reset the singleton and env-var cache — used in tests between runs.]] - rationale - config.py
- [[Return the global BotConfig singleton, loading from env on first call. Must be…]] - rationale - config.py
- [[breakeven_trigger_pct and max_days_out both read their env var fresh from the…]] - rationale - tests/test_config_validation.py
- [[get_config()]] - code - config.py
- [[load_and_validate()]] - code - config.py
- [[reset_config()]] - code - config.py
- [[test_bot_config_defaults_are_sane()]] - code - tests/test_config_validation.py
- [[test_bot_config_loads_from_env()]] - code - tests/test_config_validation.py
- [[test_config_validation.py]] - code - tests/test_config_validation.py
- [[test_paths_module_exports_critical_paths()]] - code - tests/test_config_validation.py
- [[test_validate_config_does_not_exit_in_demo_when_keys_missing()]] - code - tests/test_config_validation.py
- [[test_validate_config_exits_in_prod_when_keys_missing()]] - code - tests/test_config_validation.py
- [[test_validate_config_passes_in_prod_with_keys()]] - code - tests/test_config_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_212
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 297]]
- 4 edges to [[_COMMUNITY_Community 129]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 243]]

## Top bridge nodes
- [[test_config_validation.py]] - degree 11, connects to 4 communities
- [[get_config()]] - degree 4, connects to 2 communities
- [[load_and_validate()]] - degree 4, connects to 2 communities
- [[dot-from_env()]] - degree 5, connects to 1 community
- [[reset_config()]] - degree 5, connects to 1 community