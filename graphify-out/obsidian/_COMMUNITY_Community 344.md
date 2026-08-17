---
type: community
cohesion: 0.18
members: 11
---

# Community 344

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-_make_client()_5]] - code - tests/test_kalshi_client.py
- [[dot-test_cursor_passed_on_second_call()_1]] - code - tests/test_kalshi_client.py
- [[dot-test_single_page_returns_all_markets()]] - code - tests/test_kalshi_client.py
- [[dot-test_three_pages_returns_all()]] - code - tests/test_kalshi_client.py
- [[dot-test_two_page_pagination_combines_results()_1]] - code - tests/test_kalshi_client.py
- [[Cursor on first page → second call made, both pages combined.]] - rationale - tests/test_kalshi_client.py
- [[No cursor in response → single call, all markets returned.]] - rationale - tests/test_kalshi_client.py
- [[P1-19 get_markets must follow cursor pagination until exhausted.]] - rationale - tests/test_kalshi_client.py
- [[TestGetMarketsPagination]] - code - tests/test_kalshi_client.py
- [[The cursor value from page 1 is passed as a param on the page 2 call.]] - rationale - tests/test_kalshi_client.py
- [[Three pages with cursors → all 3 pages combined.]] - rationale - tests/test_kalshi_client.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_344
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 106]]
- 1 edge to [[_COMMUNITY_Community 229]]

## Top bridge nodes
- [[TestGetMarketsPagination]] - degree 7, connects to 1 community
- [[dot-test_cursor_passed_on_second_call()_1]] - degree 3, connects to 1 community
- [[dot-test_single_page_returns_all_markets()]] - degree 3, connects to 1 community
- [[dot-test_three_pages_returns_all()]] - degree 3, connects to 1 community
- [[dot-test_two_page_pagination_combines_results()_1]] - degree 3, connects to 1 community