---
type: community
cohesion: 0.18
members: 11
---

# Community 350

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_cache_is_thread_safe()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_cache_refreshes_after_ttl()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_cache_served_within_ttl()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_different_target_months_do_not_clobber_each_other()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_ttl_constant_is_24_hours()]] - code - tests/test_phase2_batch_c.py
- [[2026-07-19 fix get_indices() must key its cache by (year, month), not a single…]] - rationale - tests/test_phase2_batch_c.py
- [[A second call within TTL must not hit the network.]] - rationale - tests/test_phase2_batch_c.py
- [[After TTL expires, the next call must re-fetch.]] - rationale - tests/test_phase2_batch_c.py
- [[Concurrent calls must not raise and must each return a dict.]] - rationale - tests/test_phase2_batch_c.py
- [[P2-12 get_indices must refresh after TTL expires, not cache forever.]] - rationale - tests/test_phase2_batch_c.py
- [[TestClimateIndicesTTL]] - code - tests/test_phase2_batch_c.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_350
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 23]]
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[TestClimateIndicesTTL]] - degree 8, connects to 2 communities
- [[dot-test_cache_refreshes_after_ttl()]] - degree 3, connects to 1 community
- [[dot-test_cache_served_within_ttl()]] - degree 3, connects to 1 community