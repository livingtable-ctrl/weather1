---
type: community
cohesion: 0.08
members: 39
---

# Community 51

**Cohesion:** 0.08 - loosely connected
**Members:** 39 nodes

## Members
- [[dot-__init__()_4]] - code - forecast_cache.py
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
- [[dot-test_custom_max_size()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_evicts_oldest_when_full()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_max_size_default_is_500()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_prune_expired_empty_cache()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_prune_expired_removes_stale()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_prune_expired_returns_count()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_set_with_ttl_respects_max_size()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_update_existing_does_not_evict()]] - code - tests/test_phase2_batch_m.py
- [[ForecastCache]] - code - forecast_cache.py
- [[L5-A per-entry TTL of 2s expires before class-default 60s TTL. A cache written…]] - rationale - tests/test_forecast_cache.py
- [[Remove all expired entries. Returns the number of entries removed.]] - rationale - forecast_cache.py
- [[Remove the entry with the smallest (oldest) timestamp. Must hold _lock.]] - rationale - forecast_cache.py
- [[Return (value, hit, wall_clock_fetch_ts). wall_clock_fetch_ts is derived from…]] - rationale - forecast_cache.py
- [[Return the TTL for an entry per-entry (3-tuple) or class default (2-tuple).]] - rationale - forecast_cache.py
- [[Store with a per-entry TTL, overriding the class-level default. L5-A used to…]] - rationale - forecast_cache.py
- [[Store with an explicit monotonic timestamp (e.g. when restoring from disk). ts…]] - rationale - forecast_cache.py
- [[Store with both an explicit monotonic timestamp AND a per-entry TTL. Use when…]] - rationale - forecast_cache.py
- [[T]] - code
- [[TestForecastCacheLRU]] - code - tests/test_phase2_batch_m.py
- [[Thread-safe dict-based cache with per-entry TTL and LRU eviction. Keys are…]] - rationale - forecast_cache.py
- [[prune_expired() on an empty cache returns 0 without error.]] - rationale - tests/test_forecast_cache.py
- [[prune_expired() only removes expired entries — fresh entries survive.]] - rationale - tests/test_forecast_cache.py
- [[prune_expired() removes all expired entries and returns the correct count.]] - rationale - tests/test_forecast_cache.py
- [[test_prune_expired_empty_cache()]] - code - tests/test_forecast_cache.py
- [[test_prune_expired_leaves_non_expired()]] - code - tests/test_forecast_cache.py
- [[test_prune_expired_removes_expired_returns_count()]] - code - tests/test_forecast_cache.py
- [[test_set_with_ttl_expires_before_class_default()]] - code - tests/test_forecast_cache.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_51
SORT file.name ASC
```

## Connections to other communities
- 18 edges to [[_COMMUNITY_Forecast Persistent Cache]]
- 7 edges to [[_COMMUNITY_Community 234]]
- 6 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 5 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 5 edges to [[_COMMUNITY_Community 255]]
- 4 edges to [[_COMMUNITY_Community 119]]
- 4 edges to [[_COMMUNITY_Community 32]]
- 3 edges to [[_COMMUNITY_Community 182]]
- 3 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 2 edges to [[_COMMUNITY_Community 62]]
- 2 edges to [[_COMMUNITY_Community 44]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Community 276]]
- 2 edges to [[_COMMUNITY_Community 73]]
- 2 edges to [[_COMMUNITY_Community 339]]
- 1 edge to [[_COMMUNITY_Community 129]]
- 1 edge to [[_COMMUNITY_Community 454]]
- 1 edge to [[_COMMUNITY_Community 297]]
- 1 edge to [[_COMMUNITY_Community 211]]
- 1 edge to [[_COMMUNITY_Community 99]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 423]]
- 1 edge to [[_COMMUNITY_Community 303]]
- 1 edge to [[_COMMUNITY_Community 504]]
- 1 edge to [[_COMMUNITY_Community 545]]
- 1 edge to [[_COMMUNITY_Community 70]]
- 1 edge to [[_COMMUNITY_Community 424]]
- 1 edge to [[_COMMUNITY_Community 464]]
- 1 edge to [[_COMMUNITY_Community 572]]
- 1 edge to [[_COMMUNITY_Community 169]]
- 1 edge to [[_COMMUNITY_Community 275]]
- 1 edge to [[_COMMUNITY_Community 170]]
- 1 edge to [[_COMMUNITY_Community 394]]
- 1 edge to [[_COMMUNITY_Community 399]]
- 1 edge to [[_COMMUNITY_Community 367]]
- 1 edge to [[_COMMUNITY_Community 91]]
- 1 edge to [[_COMMUNITY_Community 131]]
- 1 edge to [[_COMMUNITY_Community 344]]
- 1 edge to [[_COMMUNITY_Community 432]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_METAR Lock-In Confidence Tests]]
- 1 edge to [[_COMMUNITY_Community 172]]
- 1 edge to [[_COMMUNITY_Community 345]]
- 1 edge to [[_COMMUNITY_Community 555]]
- 1 edge to [[_COMMUNITY_Community 374]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]

## Top bridge nodes
- [[ForecastCache]] - degree 119, connects to 46 communities
- [[TestForecastCacheLRU]] - degree 10, connects to 1 community
- [[test_prune_expired_empty_cache()]] - degree 3, connects to 1 community
- [[test_prune_expired_leaves_non_expired()]] - degree 3, connects to 1 community
- [[test_prune_expired_removes_expired_returns_count()]] - degree 3, connects to 1 community