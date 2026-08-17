---
type: community
cohesion: 0.22
members: 9
---

# Community 433

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_05_utc_ttl_is_approx_3600()]] - code - tests/test_phase4.py
- [[dot-test_after_all_cycles_wraps_to_next_day()]] - code - tests/test_phase4.py
- [[dot-test_minimum_ttl_is_1800()]] - code - tests/test_phase4.py
- [[dot-test_returns_int()]] - code - tests/test_phase4.py
- [[After 20 UTC, wraps to 02 UTC next day.]] - rationale - tests/test_phase4.py
- [[At 0500 UTC → TTL is roughly 3600s (until 0800 UTC availability).]] - rationale - tests/test_phase4.py
- [[Minimum TTL is always at least 1800 seconds.]] - rationale - tests/test_phase4.py
- [[TTL is returned as int.]] - rationale - tests/test_phase4.py
- [[TestTtlUntilNextCycle]] - code - tests/test_phase4.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_433
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestTtlUntilNextCycle]] - degree 5, connects to 1 community
- [[dot-test_05_utc_ttl_is_approx_3600()]] - degree 3, connects to 1 community
- [[dot-test_after_all_cycles_wraps_to_next_day()]] - degree 3, connects to 1 community
- [[dot-test_minimum_ttl_is_1800()]] - degree 3, connects to 1 community
- [[dot-test_returns_int()]] - degree 3, connects to 1 community