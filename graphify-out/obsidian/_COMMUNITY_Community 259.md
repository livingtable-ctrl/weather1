---
type: community
cohesion: 0.14
members: 14
---

# Community 259

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-setUp()_8]] - code - tests/test_paper.py
- [[dot-tearDown()_8]] - code - tests/test_paper.py
- [[dot-test_auto_settle_settles_matching_trade()]] - code - tests/test_paper.py
- [[dot-test_auto_settle_skips_no_outcome()]] - code - tests/test_paper.py
- [[dot-test_get_outcome_for_ticker_returns_correct_value()]] - code - tests/test_paper.py
- [[dot-test_get_outcome_for_ticker_returns_none_when_missing()]] - code - tests/test_paper.py
- [[dot-test_no_side_loss_recorded_as_loss()]] - code - tests/test_paper.py
- [[dot-test_no_side_win_recorded_as_win()]] - code - tests/test_paper.py
- [[NO-side trade that loses (outcome=YES) must have zero payout.]] - rationale - tests/test_paper.py
- [[NO-side trade that wins (outcome=NO) must be settled as a win, not a loss.]] - rationale - tests/test_paper.py
- [[TestAutoSettlePaperTrades]] - code - tests/test_paper.py
- [[Tests for auto-settling paper trades when tracker outcomes are recorded.]] - rationale - tests/test_paper.py
- [[auto_settle_paper_trades() closes paper trades with recorded outcomes.]] - rationale - tests/test_paper.py
- [[auto_settle_paper_trades() leaves trades open when no outcome recorded.]] - rationale - tests/test_paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_259
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 56]]

## Top bridge nodes
- [[TestAutoSettlePaperTrades]] - degree 11, connects to 2 communities