---
type: community
cohesion: 0.33
members: 6
---

# Community 527

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[Apply the common monkeypatches needed for L7-B _auto_place_trades tests.]] - rationale - tests/test_trading.py
- [[Regression for L7-B for NO trades, entry_price must equal no_ask = 1 - yes_bid…]] - rationale - tests/test_trading.py
- [[Regression for L7-B for YES trades, entry_price passed to place_paper_order…]] - rationale - tests/test_trading.py
- [[_l7b_common_patches()]] - code - tests/test_trading.py
- [[test_auto_place_uses_no_ask_not_mid_for_no_trades()]] - code - tests/test_trading.py
- [[test_auto_place_uses_yes_ask_not_mid_for_yes_trades()]] - code - tests/test_trading.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_527
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 92]]
- 1 edge to [[_COMMUNITY_Community 347]]

## Top bridge nodes
- [[_l7b_common_patches()]] - degree 5, connects to 2 communities
- [[test_auto_place_uses_no_ask_not_mid_for_no_trades()]] - degree 3, connects to 1 community
- [[test_auto_place_uses_yes_ask_not_mid_for_yes_trades()]] - degree 3, connects to 1 community