---
source_file: "tests/test_forecast_cache.py"
type: "code"
community: "Module: tests"
location: "L1"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# test_forecast_cache.py

## Connections
- [[ForecastCache]] - `imports` [EXTRACTED]
- [[_ttl_until_next_cycle()]] - `imports` [EXTRACTED]
- [[test_clear_empties_cache()]] - `contains` [EXTRACTED]
- [[test_get_returns_none_after_ttl()]] - `contains` [EXTRACTED]
- [[test_get_returns_none_for_missing_key()]] - `contains` [EXTRACTED]
- [[test_get_returns_value_within_ttl()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_expired_returns_miss()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_hit_returns_value_and_true()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_miss_returns_triple_none()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_per_entry_ttl_respected()]] - `contains` [EXTRACTED]
- [[test_get_with_ts_wall_clock_reflects_original_store_time()]] - `contains` [EXTRACTED]
- [[test_set_with_ttl_does_not_affect_other_entries()]] - `contains` [EXTRACTED]
- [[test_set_with_ttl_expires_before_class_default()]] - `contains` [EXTRACTED]
- [[test_set_with_ttl_returns_value_within_per_entry_ttl()]] - `contains` [EXTRACTED]
- [[test_ttl_until_next_cycle_at_cycle_boundary()]] - `contains` [EXTRACTED]
- [[test_ttl_until_next_cycle_returns_at_least_1800()]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests