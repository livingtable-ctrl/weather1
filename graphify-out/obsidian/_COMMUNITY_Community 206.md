---
type: community
cohesion: 0.12
members: 17
---

# Community 206

**Cohesion:** 0.12 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-_settled_market()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_accepts_recent_date_within_max_age()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_returns_count_for_matching_season()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_returns_none_for_corrupt_non_dict_entry()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_returns_none_for_non_int_count()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_returns_none_for_stale_date()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_returns_none_for_wrong_season_year()]] - code - tests/test_hurricane_markets.py
- [[dot-test_get_cached_returns_none_when_missing()]] - code - tests/test_hurricane_markets.py
- [[dot-test_refresh_counts_settled_yes_per_basin()]] - code - tests/test_hurricane_markets.py
- [[dot-test_refresh_leaves_basin_unwritten_when_no_markets_match()]] - code - tests/test_hurricane_markets.py
- [[dot-test_refresh_never_raises_on_fetch_failure()]] - code - tests/test_hurricane_markets.py
- [[dot-test_refresh_skips_basin_already_done_today()]] - code - tests/test_hurricane_markets.py
- [[A stale prior-season cache entry must never silently tilt the CURRENT season's…]] - rationale - tests/test_hurricane_markets.py
- [[Opus-review-caught (2026-08-03, HIGH) the cache's `date` field was written but…]] - rationale - tests/test_hurricane_markets.py
- [[Opus-review-caught (2026-08-03, MEDIUM-HIGH) an emptyno-match settled-markets…]] - rationale - tests/test_hurricane_markets.py
- [[Opus-review-caught a corrupted cache with a non-dict basin entry must fail…]] - rationale - tests/test_hurricane_markets.py
- [[TestHurricaneCountToDateCache]] - code - tests/test_hurricane_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_206
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 45]]

## Top bridge nodes
- [[TestHurricaneCountToDateCache]] - degree 13, connects to 1 community