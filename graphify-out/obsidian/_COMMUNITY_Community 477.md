---
type: community
cohesion: 0.39
members: 8
---

# Community 477

**Cohesion:** 0.39 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-_make_open_trades()]] - code - tests/test_trade_improvements.py
- [[dot-_make_opp()]] - code - tests/test_trade_improvements.py
- [[dot-test_no_trades_placed_when_at_cap()]] - code - tests/test_trade_improvements.py
- [[dot-test_trades_placed_below_cap()]] - code - tests/test_trade_improvements.py
- [[TestMaxConcurrentPositions]] - code - tests/test_trade_improvements.py
- [[When 20 positions already open, _auto_place_trades should place 0 new trades.]] - rationale - tests/test_trade_improvements.py
- [[When only 18 positions open, up to 2 more should be allowed.]] - rationale - tests/test_trade_improvements.py
- [[_auto_place_trades must refuse new trades once 20 open positions exist.]] - rationale - tests/test_trade_improvements.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_477
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestMaxConcurrentPositions]] - degree 6, connects to 1 community