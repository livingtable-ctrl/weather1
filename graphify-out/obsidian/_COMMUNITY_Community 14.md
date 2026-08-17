---
type: community
cohesion: 0.04
members: 65
---

# Community 14

**Cohesion:** 0.04 - loosely connected
**Members:** 65 nodes

## Members
- [[dot-dump_to_disk()]] - code - forecast_cache.py
- [[dot-load_from_disk()]] - code - forecast_cache.py
- [[Any]] - code
- [[Concurrent set() calls for DIFFERENT keys from multiple threads must not…]] - rationale - tests/test_forecast_cache.py
- [[First-ever process start (no prior dump) must not raise -- matches nws.py's…]] - rationale - tests/test_forecast_cache.py
- [[ForecastCache class]] - code - forecast_cache.py
- [[ForecastCache with whole-dict persistence to a JSON file. For permanent…]] - rationale - forecast_cache.py
- [[Grade Audit Module Doc forecast_cache.py]] - document - docs/grade_audit/modules/forecast_cache.md
- [[L5-A _ttl_until_next_cycle must return at least 1800s (30 min) to prevent…]] - rationale - tests/test_forecast_cache.py
- [[L5-A just before a model cycle, TTL is short; just after, TTL is long. At…]] - rationale - tests/test_forecast_cache.py
- [[L5-A per-entry TTL is isolated — other entries keep their own TTL.]] - rationale - tests/test_forecast_cache.py
- [[L5-A per-entry TTL of 2s expires before class-default 60s TTL. A cache written…]] - rationale - tests/test_forecast_cache.py
- [[L5-A set_with_ttl stores value accessible before per-entry TTL expires.]] - rationale - tests/test_forecast_cache.py
- [[Load a previously dumped cache from `path` into this instance, if the file…]] - rationale - forecast_cache.py
- [[P1-1 wall_clock_fetch_ts must reflect when the entry was stored, not now. We…]] - rationale - tests/test_forecast_cache.py
- [[Path_4]] - code
- [[Persist the entire cache to `path` as JSON, atomically (via…]] - rationale - forecast_cache.py
- [[PersistentForecastCache]] - code - forecast_cache.py
- [[PersistentForecastCache class]] - code - forecast_cache.py
- [[PersistentForecastCache must still behave as a normal ForecastCache for getset…]] - rationale - tests/test_forecast_cache.py
- [[Regression for the specific bug this migration fixes dump_to_disk (iterates…]] - rationale - tests/test_forecast_cache.py
- [[Regression dump_to_disk must write v0 (the value), not the raw (value, ts)…]] - rationale - tests/test_forecast_cache.py
- [[Regression load_from_disk must restore the ENTIRE persisted snapshot even if…]] - rationale - tests/test_forecast_cache.py
- [[The exact property nws.py's station cache depends on dump the current cache to…]] - rationale - tests/test_forecast_cache.py
- [[_tuple_key_to_str()]] - code - tests/test_forecast_cache.py
- [[_tuple_str_to_key()]] - code - tests/test_forecast_cache.py
- [[dump_to_disk must refuse (not silently drop the TTL) when the cache holds an…]] - rationale - tests/test_forecast_cache.py
- [[get_with_ts honours per-entry TTL set via set_with_ttl.]] - rationale - tests/test_forecast_cache.py
- [[get_with_ts returns (None, False, 0.0) for a cache miss.]] - rationale - tests/test_forecast_cache.py
- [[get_with_ts returns (None, False, 0.0) when the entry has expired.]] - rationale - tests/test_forecast_cache.py
- [[get_with_ts returns (value, True, wall_ts) on a cache hit.]] - rationale - tests/test_forecast_cache.py
- [[module-level _forecast_cache_ensemble_cache singletons]] - code - weather_markets.py
- [[nws.py's real cache path is data.nws_station_cache.json -- the parent…]] - rationale - tests/test_forecast_cache.py
- [[prune_expired() on an empty cache returns 0 without error.]] - rationale - tests/test_forecast_cache.py
- [[prune_expired() only removes expired entries — fresh entries survive.]] - rationale - tests/test_forecast_cache.py
- [[prune_expired() removes all expired entries and returns the correct count.]] - rationale - tests/test_forecast_cache.py
- [[prune_expired() uses per-entry TTL for set_with_ttl() entries.]] - rationale - tests/test_forecast_cache.py
- [[test_clear_empties_cache()]] - code - tests/test_forecast_cache.py
- [[test_dump_creates_missing_parent_directories()]] - code - tests/test_forecast_cache.py
- [[test_dump_only_persists_values_not_internal_timestamps()]] - code - tests/test_forecast_cache.py
- [[test_dump_then_load_round_trips_values()]] - code - tests/test_forecast_cache.py
- [[test_dump_to_disk_raises_on_per_entry_ttl_entry()]] - code - tests/test_forecast_cache.py
- [[test_forecast_cache.py]] - code - tests/test_forecast_cache.py
- [[test_get_returns_none_after_ttl()]] - code - tests/test_forecast_cache.py
- [[test_get_returns_none_for_missing_key()]] - code - tests/test_forecast_cache.py
- [[test_get_returns_value_within_ttl()]] - code - tests/test_forecast_cache.py
- [[test_get_with_ts_expired_returns_miss()]] - code - tests/test_forecast_cache.py
- [[test_get_with_ts_hit_returns_value_and_true()]] - code - tests/test_forecast_cache.py
- [[test_get_with_ts_miss_returns_triple_none()]] - code - tests/test_forecast_cache.py
- [[test_get_with_ts_per_entry_ttl_respected()]] - code - tests/test_forecast_cache.py
- [[test_get_with_ts_wall_clock_reflects_original_store_time()]] - code - tests/test_forecast_cache.py
- [[test_load_from_disk_does_not_evict_beyond_max_size()]] - code - tests/test_forecast_cache.py
- [[test_load_from_disk_is_a_noop_when_file_does_not_exist()]] - code - tests/test_forecast_cache.py
- [[test_persistent_cache_dump_is_thread_safe_against_concurrent_writes()]] - code - tests/test_forecast_cache.py
- [[test_persistent_cache_get_set_is_thread_safe()]] - code - tests/test_forecast_cache.py
- [[test_persistent_cache_is_a_forecast_cache()]] - code - tests/test_forecast_cache.py
- [[test_prune_expired_empty_cache()]] - code - tests/test_forecast_cache.py
- [[test_prune_expired_leaves_non_expired()]] - code - tests/test_forecast_cache.py
- [[test_prune_expired_removes_expired_returns_count()]] - code - tests/test_forecast_cache.py
- [[test_prune_expired_respects_per_entry_ttl()]] - code - tests/test_forecast_cache.py
- [[test_set_with_ttl_does_not_affect_other_entries()]] - code - tests/test_forecast_cache.py
- [[test_set_with_ttl_expires_before_class_default()]] - code - tests/test_forecast_cache.py
- [[test_set_with_ttl_returns_value_within_per_entry_ttl()]] - code - tests/test_forecast_cache.py
- [[test_ttl_until_next_cycle_at_cycle_boundary()]] - code - tests/test_forecast_cache.py
- [[test_ttl_until_next_cycle_returns_at_least_1800()]] - code - tests/test_forecast_cache.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_14
SORT file.name ASC
```

## Connections to other communities
- 18 edges to [[_COMMUNITY_Community 9]]
- 4 edges to [[_COMMUNITY_Community 5]]
- 3 edges to [[_COMMUNITY_Community 23]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 6]]
- 1 edge to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 15]]
- 1 edge to [[_COMMUNITY_Community 38]]

## Top bridge nodes
- [[test_forecast_cache.py]] - degree 38, connects to 4 communities
- [[PersistentForecastCache]] - degree 16, connects to 3 communities
- [[dot-dump_to_disk()]] - degree 6, connects to 2 communities
- [[ForecastCache class]] - degree 5, connects to 2 communities
- [[module-level _forecast_cache_ensemble_cache singletons]] - degree 3, connects to 2 communities