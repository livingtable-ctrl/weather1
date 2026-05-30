---
source_file: "forecast_cache.py"
type: "code"
community: "Module: tests"
location: "L10"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# ForecastCache

## Connections
- [[.__init__()_4]] - `method` [EXTRACTED]
- [[.__len__()]] - `method` [EXTRACTED]
- [[._evict_oldest()]] - `method` [EXTRACTED]
- [[.clear()]] - `method` [EXTRACTED]
- [[.get()]] - `method` [EXTRACTED]
- [[.get_with_ts()]] - `method` [EXTRACTED]
- [[.prune_expired()]] - `method` [EXTRACTED]
- [[.set()]] - `method` [EXTRACTED]
- [[.set_at()]] - `method` [EXTRACTED]
- [[.set_with_ttl()]] - `method` [EXTRACTED]
- [[.test_custom_max_size()]] - `calls` [EXTRACTED]
- [[.test_evicts_oldest_when_full()]] - `calls` [EXTRACTED]
- [[.test_max_size_default_is_500()]] - `calls` [EXTRACTED]
- [[.test_prune_expired_empty_cache()]] - `calls` [EXTRACTED]
- [[.test_prune_expired_removes_stale()]] - `calls` [EXTRACTED]
- [[.test_prune_expired_returns_count()]] - `calls` [EXTRACTED]
- [[.test_set_with_ttl_respects_max_size()]] - `calls` [EXTRACTED]
- [[.test_update_existing_does_not_evict()]] - `calls` [EXTRACTED]
- [[KalshiClient_4]] - `uses` [INFERRED]
- [[Response_1]] - `uses` [INFERRED]
- [[Session_1]] - `uses` [INFERRED]
- [[TestAbTestMaxTradesMeta]] - `uses` [INFERRED]
- [[TestClimatologyZipTruncation]] - `uses` [INFERRED]
- [[TestForecastCacheLRU]] - `uses` [INFERRED]
- [[TestGbmHoldoutValidation]] - `uses` [INFERRED]
- [[TestMlRetrainMarkerFile]] - `uses` [INFERRED]
- [[TestParamSweepTemporalSplit]] - `uses` [INFERRED]
- [[Thread-safe dict-based cache with per-entry TTL and LRU eviction.     Keys are]] - `rationale_for` [EXTRACTED]
- [[bool_24]] - `uses` [INFERRED]
- [[date_7]] - `uses` [INFERRED]
- [[datetime_1]] - `uses` [INFERRED]
- [[float_44]] - `uses` [INFERRED]
- [[float_31]] - `uses` [INFERRED]
- [[forecast_cache.py]] - `contains` [EXTRACTED]
- [[int_32]] - `uses` [INFERRED]
- [[int_26]] - `uses` [INFERRED]
- [[str_33]] - `uses` [INFERRED]
- [[test_clear_empties_cache()]] - `calls` [EXTRACTED]
- [[test_forecast_cache.py]] - `imports` [EXTRACTED]
- [[test_get_returns_none_after_ttl()]] - `calls` [EXTRACTED]
- [[test_get_returns_none_for_missing_key()]] - `calls` [EXTRACTED]
- [[test_get_returns_value_within_ttl()]] - `calls` [EXTRACTED]
- [[test_get_with_ts_expired_returns_miss()]] - `calls` [EXTRACTED]
- [[test_get_with_ts_hit_returns_value_and_true()]] - `calls` [EXTRACTED]
- [[test_get_with_ts_miss_returns_triple_none()]] - `calls` [EXTRACTED]
- [[test_get_with_ts_per_entry_ttl_respected()]] - `calls` [EXTRACTED]
- [[test_get_with_ts_wall_clock_reflects_original_store_time()]] - `calls` [EXTRACTED]
- [[test_phase2_batch_m.py]] - `imports` [EXTRACTED]
- [[test_set_with_ttl_does_not_affect_other_entries()]] - `calls` [EXTRACTED]
- [[test_set_with_ttl_expires_before_class_default()]] - `calls` [EXTRACTED]
- [[test_set_with_ttl_returns_value_within_per_entry_ttl()]] - `calls` [EXTRACTED]
- [[weather_markets.py]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests