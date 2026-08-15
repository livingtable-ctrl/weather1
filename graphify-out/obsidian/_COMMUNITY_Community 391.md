---
type: community
cohesion: 0.22
members: 9
---

# Community 391

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_api_error_skips_series_and_continues()]] - code - tests/test_backtest.py
- [[dot-test_min_close_time_forwarded_to_api()]] - code - tests/test_backtest.py
- [[dot-test_min_close_time_omitted_when_none()]] - code - tests/test_backtest.py
- [[dot-test_pagination_follows_cursor_within_series()]] - code - tests/test_backtest.py
- [[TestFetchSettledMarkets]] - code - tests/test_backtest.py
- [[When min_close_time is None the param must not appear in the API call.]] - rationale - tests/test_backtest.py
- [[_fetch_settled_markets follows cursor pages within a single series.]] - rationale - tests/test_backtest.py
- [[_fetch_settled_markets must pass min_close_time to every API call. Root cause…]] - rationale - tests/test_backtest.py
- [[_fetch_settled_markets silently skips a series that errors and continues.]] - rationale - tests/test_backtest.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_391
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Backtest Engine & Atomic Writes]]

## Top bridge nodes
- [[TestFetchSettledMarkets]] - degree 5, connects to 1 community