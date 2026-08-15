---
type: community
cohesion: 0.08
members: 26
---

# Community 107

**Cohesion:** 0.08 - loosely connected
**Members:** 26 nodes

## Members
- [[dot-setUp()_1]] - code - tests/test_paper.py
- [[dot-tearDown()_1]] - code - tests/test_paper.py
- [[dot-test_exposure_ignores_other_city()]] - code - tests/test_paper.py
- [[dot-test_exposure_ignores_settled_trade()]] - code - tests/test_paper.py
- [[dot-test_exposure_with_matching_trade()]] - code - tests/test_paper.py
- [[dot-test_exposure_zero_with_no_trades()]] - code - tests/test_paper.py
- [[dot-test_l3a_kelly_clamped_to_remaining_room()]] - code - tests/test_paper.py
- [[dot-test_l3a_no_city_context_also_clamped()]] - code - tests/test_paper.py
- [[dot-test_l3a_sum_of_independent_kellys_bounded()]] - code - tests/test_paper.py
- [[dot-test_place_paper_order_stores_city_date()]] - code - tests/test_paper.py
- [[dot-test_portfolio_kelly_at_cap()]] - code - tests/test_paper.py
- [[dot-test_portfolio_kelly_no_city_passthrough()]] - code - tests/test_paper.py
- [[dot-test_portfolio_kelly_no_exposure()]] - code - tests/test_paper.py
- [[dot-test_portfolio_kelly_partial_exposure()]] - code - tests/test_paper.py
- [[Existing exposure = MAX → returns 0.0.]] - rationale - tests/test_paper.py
- [[Half of max citydate exposure → Kelly reduced by both city-date scale and the…]] - rationale - tests/test_paper.py
- [[L3-A even with no citydate context, result is clamped to remaining room.]] - rationale - tests/test_paper.py
- [[L3-A placing N independent citydate trades cannot push total Kelly sum past…]] - rationale - tests/test_paper.py
- [[L3-A when portfolio is 80% full, a 20% Kelly is clamped to 10% (remaining…]] - rationale - tests/test_paper.py
- [[None city → base fraction returned unchanged (no lookup possible).]] - rationale - tests/test_paper.py
- [[Open trade for NYC2026-04-09 should show up in exposure.]] - rationale - tests/test_paper.py
- [[Settled trades should not count toward exposure.]] - rationale - tests/test_paper.py
- [[TestPortfolioKelly]] - code - tests/test_paper.py
- [[Trade for Chicago should not count toward NYC exposure.]] - rationale - tests/test_paper.py
- [[Trade record should include city and target_date fields.]] - rationale - tests/test_paper.py
- [[Zero existing exposure → base fraction returned unchanged.]] - rationale - tests/test_paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_107
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 56]]
- 1 edge to [[_COMMUNITY_Community 45]]

## Top bridge nodes
- [[TestPortfolioKelly]] - degree 16, connects to 2 communities