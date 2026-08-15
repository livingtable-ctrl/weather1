---
type: community
cohesion: 0.20
members: 10
---

# Community 370

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_no_real_ask_still_prices_normally()]] - code - tests/test_paper.py
- [[dot-test_no_zero_ask_returns_none_not_one()]] - code - tests/test_paper.py
- [[dot-test_yes_real_bid_still_prices_normally()]] - code - tests/test_paper.py
- [[dot-test_yes_zero_bid_returns_none_not_zero()]] - code - tests/test_paper.py
- [[dot-test_zero_ask_no_longer_books_phantom_win()]] - code - tests/test_paper.py
- [[dot-test_zero_bid_no_longer_fires_phantom_stop_loss()]] - code - tests/test_paper.py
- [[Deep-review followup parse_market_price() coalesces a missing side to 0.0…]] - rationale - tests/test_paper.py
- [[End-to-end a NO position with a one-sided (ask=0) book must not be treated as…]] - rationale - tests/test_paper.py
- [[End-to-end a YES position with a one-sided (bid=0) book must not be treated as…]] - rationale - tests/test_paper.py
- [[TestLiquidationPriceZeroSide]] - code - tests/test_paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_370
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 159]]
- 1 edge to [[_COMMUNITY_Community 145]]
- 1 edge to [[_COMMUNITY_Community 56]]

## Top bridge nodes
- [[TestLiquidationPriceZeroSide]] - degree 9, connects to 2 communities
- [[dot-test_zero_ask_no_longer_books_phantom_win()]] - degree 4, connects to 2 communities
- [[dot-test_zero_bid_no_longer_fires_phantom_stop_loss()]] - degree 4, connects to 2 communities