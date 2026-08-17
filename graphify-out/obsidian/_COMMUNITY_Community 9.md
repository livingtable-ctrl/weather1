---
type: community
cohesion: 0.03
members: 85
---

# Community 9

**Cohesion:** 0.03 - loosely connected
**Members:** 85 nodes

## Members
- [[dot-__init__()_12]] - code - forecast_cache.py
- [[dot-__len__()]] - code - forecast_cache.py
- [[dot-_effective_ttl()]] - code - forecast_cache.py
- [[dot-_evict_oldest()]] - code - forecast_cache.py
- [[dot-clear()]] - code - forecast_cache.py
- [[dot-get()]] - code - forecast_cache.py
- [[dot-get_with_ts()]] - code - forecast_cache.py
- [[dot-prune_expired()]] - code - forecast_cache.py
- [[dot-set()]] - code - forecast_cache.py
- [[dot-set_at()]] - code - forecast_cache.py
- [[dot-set_at_with_ttl()]] - code - forecast_cache.py
- [[dot-set_with_ttl()]] - code - forecast_cache.py
- [[dot-test_cron_source_no_exact_hour_check()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_custom_max_size()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_default_max_trades_still_works()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_evicts_oldest_when_full()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_fetch_temperature_nbm_negative_caches_failure()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_prefers_real_nbm_over_openmeteo()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_returns_float_or_none()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_returns_none_on_error()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_unknown_station_skips_iem()]] - code - tests/test_nbm.py
- [[dot-test_get_active_variant_skips_meta_key()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_get_active_variant_uses_persisted_max()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_logs_warning_on_mismatched_lengths()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_max_size_default_is_500()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_meta_key_written_on_init()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_meta_updated_when_max_trades_changes()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_minneapolis_not_97pct_climatology()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_minneapolis_weights_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_nbm_in_ensemble_models()]] - code - tests/test_nbm.py
- [[dot-test_no_warning_on_equal_lengths()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_openmeteo_fallback_does_not_clobber_iem_value_for_other_var()]] - code - tests/test_nbm.py
- [[dot-test_prune_expired_empty_cache()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_prune_expired_removes_stale()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_prune_expired_returns_count()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_reduced_hyperparams()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_retrain_fires_when_marker_old()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_retrain_fires_when_no_marker()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_retrain_skipped_when_marker_recent()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_set_with_ttl_respects_max_size()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_skips_city_when_holdout_mse_not_better()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_train_source_has_holdout_split()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_update_existing_does_not_evict()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_zip_uses_shortest_list()]] - code - tests/test_phase2_batch_m.py
- [[2026-07-17 (opus review finding) NBS has per-var coverage gaps at its ~3-day…]] - rationale - tests/test_nbm.py
- [[2026-07-17 fetch_temperature_nbm must try the real-NBM IEM path first and use…]] - rationale - tests/test_nbm.py
- [[A city with no ASOS station mapping must skip straight to Open-Meteo rather…]] - rationale - tests/test_nbm.py
- [[A failed fetch (both IEM and Open-Meteo unavailable) must be negative-cached --…]] - rationale - tests/test_nbm.py
- [[ABTest.__init__ must write max_trades_per_variant into _meta.]] - rationale - tests/test_phase2_batch_m.py
- [[City model must not be added when holdout MSE = baseline.]] - rationale - tests/test_phase2_batch_m.py
- [[Constructing ABTest with a new max_trades must update the persisted _meta.]] - rationale - tests/test_phase2_batch_m.py
- [[ENSEMBLE_MODELS_EXTENDED includes NBM.]] - rationale - tests/test_nbm.py
- [[ForecastCache]] - code - forecast_cache.py
- [[GradientBoostingRegressor must use n_estimators=50, max_depth=2.]] - rationale - tests/test_phase2_batch_m.py
- [[Marker file 6 days old → should retrain.]] - rationale - tests/test_phase2_batch_m.py
- [[Marker file less than 6 days old → should NOT retrain.]] - rationale - tests/test_phase2_batch_m.py
- [[P2-10 Minneapolis city weights must not have 0.97 climatology.]] - rationale - tests/test_phase2_batch_c.py
- [[Phase 2 Batch M regression tests P2-353738424446.]] - rationale - tests/test_phase2_batch_m.py
- [[Remove all expired entries. Returns the number of entries removed.]] - rationale - forecast_cache.py
- [[Remove the entry with the smallest (oldest) timestamp. Must hold _lock.]] - rationale - forecast_cache.py
- [[Return (value, hit, wall_clock_fetch_ts). wall_clock_fetch_ts is derived from…]] - rationale - forecast_cache.py
- [[Return the TTL for an entry per-entry (3-tuple) or class default (2-tuple).]] - rationale - forecast_cache.py
- [[Returns None gracefully when both the IEM and Open-Meteo paths fail.]] - rationale - tests/test_nbm.py
- [[Store with a per-entry TTL, overriding the class-level default. L5-A used to…]] - rationale - forecast_cache.py
- [[Store with an explicit monotonic timestamp (e.g. when restoring from disk). ts…]] - rationale - forecast_cache.py
- [[Store with both an explicit monotonic timestamp AND a per-entry TTL. Use when…]] - rationale - forecast_cache.py
- [[T]] - code
- [[TestAbTestMaxTradesMeta]] - code - tests/test_phase2_batch_m.py
- [[TestClimatologyZipTruncation]] - code - tests/test_phase2_batch_m.py
- [[TestForecastCacheLRU]] - code - tests/test_phase2_batch_m.py
- [[TestGbmHoldoutValidation]] - code - tests/test_phase2_batch_m.py
- [[TestMinneapolisWeights]] - code - tests/test_phase2_batch_c.py
- [[TestMlRetrainMarkerFile]] - code - tests/test_phase2_batch_m.py
- [[TestNBMFetch]] - code - tests/test_nbm.py
- [[Thread-safe dict-based cache with per-entry TTL and LRU eviction. Keys are…]] - rationale - forecast_cache.py
- [[When marker file is absent, retrain should be attempted.]] - rationale - tests/test_phase2_batch_m.py
- [[Without a persisted _meta, _DEFAULT_MAX_TRADES is used.]] - rationale - tests/test_phase2_batch_m.py
- [[cron retrain block must use .last_ml_retrain marker, not exact UTC hour.]] - rationale - tests/test_phase2_batch_m.py
- [[cron._cmd_cron_body must NOT use exact-hour retrain logic.]] - rationale - tests/test_phase2_batch_m.py
- [[fetch_temperature_nbm falls back to Open-Meteo best_match when the real-NBM IEM…]] - rationale - tests/test_nbm.py
- [[get_active_variant must not treat _meta as a variant.]] - rationale - tests/test_phase2_batch_m.py
- [[get_active_variant must respect the persisted max_trades, not…]] - rationale - tests/test_phase2_batch_m.py
- [[test_phase2_batch_m.py]] - code - tests/test_phase2_batch_m.py
- [[train_bias_model source must contain 8020 holdout logic.]] - rationale - tests/test_phase2_batch_m.py
- [[zip() truncates to shortest — result must not raise IndexError.]] - rationale - tests/test_phase2_batch_m.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_9
SORT file.name ASC
```

## Connections to other communities
- 18 edges to [[_COMMUNITY_Community 14]]
- 10 edges to [[_COMMUNITY_Community 4]]
- 8 edges to [[_COMMUNITY_Community 5]]
- 5 edges to [[_COMMUNITY_Community 252]]
- 4 edges to [[_COMMUNITY_Community 15]]
- 4 edges to [[_COMMUNITY_Community 232]]
- 4 edges to [[_COMMUNITY_Community 23]]
- 4 edges to [[_COMMUNITY_Community 6]]
- 3 edges to [[_COMMUNITY_Community 38]]
- 3 edges to [[_COMMUNITY_Community 102]]
- 3 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 26]]
- 2 edges to [[_COMMUNITY_Community 277]]
- 2 edges to [[_COMMUNITY_Community 280]]
- 2 edges to [[_COMMUNITY_Community 68]]
- 1 edge to [[_COMMUNITY_Community 100]]
- 1 edge to [[_COMMUNITY_Community 109]]
- 1 edge to [[_COMMUNITY_Community 11]]
- 1 edge to [[_COMMUNITY_Community 116]]
- 1 edge to [[_COMMUNITY_Community 177]]
- 1 edge to [[_COMMUNITY_Community 178]]
- 1 edge to [[_COMMUNITY_Community 181]]
- 1 edge to [[_COMMUNITY_Community 22]]
- 1 edge to [[_COMMUNITY_Community 276]]
- 1 edge to [[_COMMUNITY_Community 306]]
- 1 edge to [[_COMMUNITY_Community 350]]
- 1 edge to [[_COMMUNITY_Community 378]]
- 1 edge to [[_COMMUNITY_Community 381]]
- 1 edge to [[_COMMUNITY_Community 386]]
- 1 edge to [[_COMMUNITY_Community 417]]
- 1 edge to [[_COMMUNITY_Community 418]]
- 1 edge to [[_COMMUNITY_Community 424]]
- 1 edge to [[_COMMUNITY_Community 460]]
- 1 edge to [[_COMMUNITY_Community 461]]
- 1 edge to [[_COMMUNITY_Community 469]]
- 1 edge to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Community 503]]
- 1 edge to [[_COMMUNITY_Community 565]]
- 1 edge to [[_COMMUNITY_Community 614]]
- 1 edge to [[_COMMUNITY_Community 65]]
- 1 edge to [[_COMMUNITY_Community 7]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 2]]
- 1 edge to [[_COMMUNITY_Community 95]]
- 1 edge to [[_COMMUNITY_Community 312]]

## Top bridge nodes
- [[ForecastCache]] - degree 119, connects to 42 communities
- [[test_phase2_batch_m.py]] - degree 17, connects to 6 communities
- [[TestNBMFetch]] - degree 9, connects to 1 community
- [[TestMinneapolisWeights]] - degree 5, connects to 1 community
- [[dot-test_fetch_temperature_nbm_negative_caches_failure()]] - degree 4, connects to 1 community