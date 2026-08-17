---
source_file: "tests/test_forecast_cache.py"
type: "code"
community: "Community 14"
location: "L1"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_14
---

# test_forecast_cache.py

## Connections
- [[ForecastCache]] - `imports` [EXTRACTED]
- [[ForecastCache class]] - `references` [EXTRACTED]
- [[Grade Audit Module Doc forecast_cache.py]] - `references` [EXTRACTED]
- [[PersistentForecastCache]] - `imports` [EXTRACTED]
- [[PersistentForecastCache class]] - `references` [EXTRACTED]
- [[_ttl_until_next_cycle()]] - `imports` [EXTRACTED]
- [[_tuple_key_to_str()]] - `contains` [EXTRACTED]
- [[_tuple_str_to_key()]] - `contains` [EXTRACTED]
- [[forecast_cache.py]] - `imports_from` [EXTRACTED]
- [[test_clear_empties_cache()]] - `contains` [EXTRACTED]
- [[test_dump_creates_missing_parent_directories()]] - `contains` [EXTRACTED]
- [[test_dump_only_persists_values_not_internal_timestamps()]] - `contains` [EXTRACTED]
- [[test_dump_then_load_round_trips_values()]] - `contains` [EXTRACTED]
- [[test_dump_to_disk_raises_on_per_entry_ttl_entry()]] - `contains` [EXTRACTED]
- [[test_get_returns_none_after_ttl()]] - `contains` [EXTRACTED]
- [[test_get_returns_none_for_missing_key()]] - `contains` [EXTRACTED]
- [[test_get_returns_value_within_ttl()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_expired_returns_miss()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_hit_returns_value_and_true()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_miss_returns_triple_none()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_per_entry_ttl_respected()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_wall_clock_reflects_original_store_time()]] - `contains` [EXTRACTED]
- [[test_load_from_disk_does_not_evict_beyond_max_size()]] - `contains` [EXTRACTED]
- [[test_load_from_disk_is_a_noop_when_file_does_not_exist()]] - `contains` [EXTRACTED]
- [[test_persistent_cache_dump_is_thread_safe_against_concurrent_writes()]] - `contains` [EXTRACTED]
- [[test_persistent_cache_get_set_is_thread_safe()]] - `contains` [EXTRACTED]
- [[test_persistent_cache_is_a_forecast_cache()]] - `contains` [EXTRACTED]
- [[test_prune_expired_empty_cache()]] - `contains` [EXTRACTED]
- [[test_prune_expired_leaves_non_expired()]] - `contains` [EXTRACTED]
- [[test_prune_expired_removes_expired_returns_count()]] - `contains` [EXTRACTED]
- [[test_prune_expired_respects_per_entry_ttl()]] - `contains` [EXTRACTED]
- [[test_set_with_ttl_does_not_affect_other_entries()]] - `contains` [EXTRACTED]
- [[test_set_with_ttl_expires_before_class_default()]] - `contains` [EXTRACTED]
- [[test_set_with_ttl_returns_value_within_per_entry_ttl()]] - `contains` [EXTRACTED]
- [[test_ttl_until_next_cycle_at_cycle_boundary()]] - `contains` [EXTRACTED]
- [[test_ttl_until_next_cycle_returns_at_least_1800()]] - `contains` [EXTRACTED]
- [[threading]] - `imports` [EXTRACTED]
- [[time]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_14