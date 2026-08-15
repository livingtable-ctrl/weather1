---
type: community
cohesion: 0.14
members: 22
---

# Community 138

**Cohesion:** 0.14 - loosely connected
**Members:** 22 nodes

## Members
- [[dot-__init__()_12]] - code - tests/test_paper.py
- [[dot-_write_open_trades()]] - code - tests/test_paper.py
- [[dot-_write_open_trades()_1]] - code - tests/test_paper.py
- [[dot-get_market()_3]] - code - tests/test_paper.py
- [[dot-test_client_none_returns_zero_even_with_open_trades()]] - code - tests/test_paper.py
- [[dot-test_exact_040_boundary_is_balanced()]] - code - tests/test_paper.py
- [[dot-test_exact_060_boundary_is_balanced()]] - code - tests/test_paper.py
- [[dot-test_mixed_yes_and_no_sides_sum_correctly()]] - code - tests/test_paper.py
- [[dot-test_no_heavy_below_040()]] - code - tests/test_paper.py
- [[dot-test_no_open_trades_is_balanced_with_zero_costs()]] - code - tests/test_paper.py
- [[dot-test_no_open_trades_returns_zero()]] - code - tests/test_paper.py
- [[dot-test_no_side_marks_at_one_minus_ask()]] - code - tests/test_paper.py
- [[dot-test_yes_heavy_above_060()]] - code - tests/test_paper.py
- [[dot-test_yes_side_marks_at_bid()]] - code - tests/test_paper.py
- [[Minimal stub of the Kalshi client's get_market(ticker) surface.]] - rationale - tests/test_paper.py
- [[NO holder can only realize (1 - yes_ask) — mark_pnl = ((1-ask) - entry)  qty.]] - rationale - tests/test_paper.py
- [[TestGetFactorExposure]] - code - tests/test_paper.py
- [[TestGetUnrealizedPnlPaper]] - code - tests/test_paper.py
- [[YES holder can only realize the bid — mark_pnl = (bid - entry)  qty.]] - rationale - tests/test_paper.py
- [[_FakeMarketClient]] - code - tests/test_paper.py
- [[yes_frac == 0.4 exactly must NOT count as NO-heavy (strict ).]] - rationale - tests/test_paper.py
- [[yes_frac == 0.6 exactly must NOT count as YES-heavy (strict ).]] - rationale - tests/test_paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_138
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 45]]
- 3 edges to [[_COMMUNITY_Community 56]]

## Top bridge nodes
- [[_FakeMarketClient]] - degree 9, connects to 2 communities
- [[TestGetFactorExposure]] - degree 8, connects to 2 communities
- [[TestGetUnrealizedPnlPaper]] - degree 8, connects to 2 communities