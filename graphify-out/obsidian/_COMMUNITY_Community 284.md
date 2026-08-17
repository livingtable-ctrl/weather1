---
type: community
cohesion: 0.26
members: 13
---

# Community 284

**Cohesion:** 0.26 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-test_current_api_open_interest_fp_prevents_false_stale()]] - code - tests/test_paper.py
- [[dot-test_current_api_volume_fp_prevents_false_stale()]] - code - tests/test_paper.py
- [[dot-test_market_no_volume_closing_soon_is_stale()]] - code - tests/test_paper.py
- [[dot-test_market_no_volume_far_future_not_stale()]] - code - tests/test_paper.py
- [[dot-test_market_with_open_interest_not_stale()]] - code - tests/test_paper.py
- [[dot-test_market_with_volume_not_stale()]] - code - tests/test_paper.py
- [[dot-test_missing_close_time_not_stale()]] - code - tests/test_paper.py
- [[dot-test_string_volume_fp_does_not_crash()]] - code - tests/test_paper.py
- [[dot-test_string_zero_volume_fp_still_stale_when_closing_soon()]] - code - tests/test_paper.py
- [[A genuinely-zero string volume_fp (0.00) must still correctly report stale --…]] - rationale - tests/test_paper.py
- [[Returns True if a market has no volume AND no open interest AND closes within…]] - rationale - weather_markets.py
- [[TestIsStale]] - code - tests/test_paper.py
- [[is_stale()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_284
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 21]]
- 1 edge to [[_COMMUNITY_Community 12]]
- 1 edge to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 5]]

## Top bridge nodes
- [[is_stale()]] - degree 17, connects to 4 communities
- [[TestIsStale]] - degree 11, connects to 2 communities