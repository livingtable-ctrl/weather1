---
type: community
cohesion: 0.11
members: 27
---

# Community 106

**Cohesion:** 0.11 - loosely connected
**Members:** 27 nodes

## Members
- [[dot-_make_client()_1]] - code - tests/test_kalshi_client.py
- [[dot-_make_client()]] - code - tests/test_kalshi_client.py
- [[dot-test_calls_correct_path_and_params()]] - code - tests/test_kalshi_client.py
- [[dot-test_client_order_id_included_when_provided()]] - code - tests/test_kalshi_client.py
- [[dot-test_client_order_id_omitted_when_not_provided()]] - code - tests/test_kalshi_client.py
- [[dot-test_cursor_passed_on_second_call()]] - code - tests/test_kalshi_client.py
- [[dot-test_cursor_present_but_next_page_empty_stops_pagination()]] - code - tests/test_kalshi_client.py
- [[dot-test_min_ts_max_ts_omitted_when_not_provided()]] - code - tests/test_kalshi_client.py
- [[dot-test_missing_trades_key_returns_empty_list()]] - code - tests/test_kalshi_client.py
- [[dot-test_no_side_buy_maps_to_ask_at_complementary_price()]] - code - tests/test_kalshi_client.py
- [[dot-test_posts_to_amend_path_with_order_id()]] - code - tests/test_kalshi_client.py
- [[dot-test_repeated_cursor_stops_pagination()]] - code - tests/test_kalshi_client.py
- [[dot-test_returns_raw_post_response_unchanged()]] - code - tests/test_kalshi_client.py
- [[dot-test_single_page_returns_all_trades_no_cursor()]] - code - tests/test_kalshi_client.py
- [[dot-test_two_page_pagination_combines_results()]] - code - tests/test_kalshi_client.py
- [[dot-test_updated_client_order_id_always_present_and_deterministic()]] - code - tests/test_kalshi_client.py
- [[dot-test_updated_client_order_id_differs_for_different_price()]] - code - tests/test_kalshi_client.py
- [[A cursor identical to one already seen must stop the loop rather than spin…]] - rationale - tests/test_kalshi_client.py
- [[AMEND ORDER (V2) kalshi_client.amend_order() -- POST…]] - rationale - tests/test_kalshi_client.py
- [[Live-verified real Kalshi behavior (2026-07-19) a non-empty cursor can be…]] - rationale - tests/test_kalshi_client.py
- [[No cursor in response - single call, all trades returned.]] - rationale - tests/test_kalshi_client.py
- [[No get_order() follow-up (unlike place_order) -- the amend response already…]] - rationale - tests/test_kalshi_client.py
- [[PUBLIC TRADES REST BACKFILL backlog item -- GET marketstrades fetch.]] - rationale - tests/test_kalshi_client.py
- [[Same (order_id, side, count, price, cycle) - same updated_client_order_id, so…]] - rationale - tests/test_kalshi_client.py
- [[Same V2 sideprice mapping as place_order -- a NO buy amend must be expressed…]] - rationale - tests/test_kalshi_client.py
- [[TestAmendOrder]] - code - tests/test_kalshi_client.py
- [[TestGetTrades]] - code - tests/test_kalshi_client.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_106
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 344]]
- 4 edges to [[_COMMUNITY_Community 506]]
- 2 edges to [[_COMMUNITY_Community 229]]
- 2 edges to [[_COMMUNITY_Community 379]]
- 2 edges to [[_COMMUNITY_Community 569]]
- 2 edges to [[_COMMUNITY_Community 570]]

## Top bridge nodes
- [[dot-_make_client()]] - degree 30, connects to 5 communities
- [[TestGetTrades]] - degree 11, connects to 1 community
- [[TestAmendOrder]] - degree 10, connects to 1 community