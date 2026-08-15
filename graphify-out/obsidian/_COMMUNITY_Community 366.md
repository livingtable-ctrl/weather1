---
type: community
cohesion: 0.20
members: 10
---

# Community 366

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-_make_client()_6]] - code - tests/test_kalshi_client.py
- [[dot-test_no_side_buy_maps_to_ask_at_complementary_price()_1]] - code - tests/test_kalshi_client.py
- [[dot-test_no_side_place_live_order_calls_buy_not_sell_yes()]] - code - tests/test_kalshi_client.py
- [[dot-test_yes_side_buy_maps_to_bid_at_same_price()]] - code - tests/test_kalshi_client.py
- [[L1-A Verify side='no' action='buy' API semantics are correct via the full…]] - rationale - tests/test_kalshi_client.py
- [[Return a KalshiClient with no auth (we only test body construction).]] - rationale - tests/test_kalshi_client.py
- [[TestPlaceOrderApiSemantics]] - code - tests/test_kalshi_client.py
- [[_place_live_order with side='no' must call client.place_order(side='no',…]] - rationale - tests/test_kalshi_client.py
- [[side='no' action='buy' must send V2 side='ask' at price=1-price.]] - rationale - tests/test_kalshi_client.py
- [[side='yes' action='buy' must send V2 side='bid' at the same price.]] - rationale - tests/test_kalshi_client.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_366
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 100]]
- 1 edge to [[_COMMUNITY_Community 225]]

## Top bridge nodes
- [[TestPlaceOrderApiSemantics]] - degree 6, connects to 1 community
- [[dot-test_no_side_buy_maps_to_ask_at_complementary_price()_1]] - degree 3, connects to 1 community
- [[dot-test_yes_side_buy_maps_to_bid_at_same_price()]] - degree 3, connects to 1 community