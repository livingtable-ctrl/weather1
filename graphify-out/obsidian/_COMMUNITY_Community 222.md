---
type: community
cohesion: 0.20
members: 16
---

# Community 222

**Cohesion:** 0.20 - loosely connected
**Members:** 16 nodes

## Members
- [[dot-_mock_network()]] - code - tests/test_climatology.py
- [[dot-_mock_network_failure()]] - code - tests/test_climatology.py
- [[dot-test_force_true_bypasses_mem_cache()]] - code - tests/test_climatology.py
- [[dot-test_fresh_disk_cache_read_also_populates_mem_cache()]] - code - tests/test_climatology.py
- [[dot-test_fresh_disk_cache_serves_without_network_call()]] - code - tests/test_climatology.py
- [[dot-test_network_failure_fallback_also_populates_mem_cache()]] - code - tests/test_climatology.py
- [[dot-test_network_failure_falls_back_to_existing_disk_cache()]] - code - tests/test_climatology.py
- [[dot-test_network_failure_with_no_disk_cache_returns_none()]] - code - tests/test_climatology.py
- [[dot-test_network_fetch_populates_mem_cache_and_writes_disk()]] - code - tests/test_climatology.py
- [[dot-test_second_call_same_city_serves_from_mem_cache_not_network()]] - code - tests/test_climatology.py
- [[dot-test_stale_disk_cache_triggers_network_refetch()]] - code - tests/test_climatology.py
- [[Deletes the disk cache file between calls so the second call can ONLY succeed…]] - rationale - tests/test_climatology.py
- [[Targets _MEM_CACHE.set() on the fresh-disk-read branch specifically…]] - rationale - tests/test_climatology.py
- [[Targets _MEM_CACHE.set() on the network-failure-fallback branch specifically…]] - rationale - tests/test_climatology.py
- [[TestFetchHistoricalCaching]] - code - tests/test_climatology.py
- [[fetch_historical()'s _MEM_CACHE memoization -- previously zero direct coverage…]] - rationale - tests/test_climatology.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_222
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestFetchHistoricalCaching]] - degree 13, connects to 1 community