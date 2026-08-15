---
type: community
cohesion: 0.25
members: 8
---

# Community 428

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_get_cached_storms_named_returns_none_for_non_int()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_storms_named_returns_none_when_missing()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_storms_named_round_trips_through_real_refresh()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_storms_named_shares_staleness_guard_with_count()]] - code - tests/test_hurricane_markets.py
- [[dot-test_refresh_writes_storms_named_per_basin()]] - code - tests/test_hurricane_markets.py
- [[Both readers delegate to the same _get_cached_hurricane_names_ entry helper --…]] - rationale - tests/test_hurricane_markets.py
- [[TestStormsNamedToDateCache]] - code - tests/test_hurricane_markets.py
- [[The real end-to-end path refresh_hurricane_count_to_date's actual write, read…]] - rationale - tests/test_hurricane_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_428
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 90]]

## Top bridge nodes
- [[TestStormsNamedToDateCache]] - degree 6, connects to 1 community