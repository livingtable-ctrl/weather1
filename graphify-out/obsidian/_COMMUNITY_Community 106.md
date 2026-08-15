---
type: community
cohesion: 0.08
members: 26
---

# Community 106

**Cohesion:** 0.08 - loosely connected
**Members:** 26 nodes

## Members
- [[dot-setUp()_2]] - code - tests/test_paper.py
- [[dot-tearDown()_2]] - code - tests/test_paper.py
- [[dot-test_boundary_exactly_800_not_paused()]] - code - tests/test_paper.py
- [[dot-test_effective_balance_adds_back_same_day_cost()]] - code - tests/test_paper.py
- [[dot-test_effective_balance_ignores_multiday_cost()]] - code - tests/test_paper.py
- [[dot-test_kelly_normal_above_threshold()]] - code - tests/test_paper.py
- [[dot-test_kelly_returns_zero_in_drawdown()]] - code - tests/test_paper.py
- [[dot-test_max_drawdown_pct_uses_actual_balance()]] - code - tests/test_paper.py
- [[dot-test_needs_manual_settle_excluded_from_effective_balance()]] - code - tests/test_paper.py
- [[dot-test_not_paused_at_start()]] - code - tests/test_paper.py
- [[dot-test_paused_below_threshold()]] - code - tests/test_paper.py
- [[dot-test_paused_drawdown_ignores_same_day_costs()]] - code - tests/test_paper.py
- [[dot-test_reset_peak_requires_confirmed()]] - code - tests/test_paper.py
- [[dot-test_reset_peak_sets_to_current_balance()]] - code - tests/test_paper.py
- [[Balance below 50% of $1000 → drawdown active.]] - rationale - tests/test_paper.py
- [[Balance exactly at $800 (= 80% of $1000, 20% halt) is NOT paused (strict less-…]] - rationale - tests/test_paper.py
- [[Same-day trades marked needs_manual_settle are excluded from effective balance…]] - rationale - tests/test_paper.py
- [[TestMaxDrawdown]] - code - tests/test_paper.py
- [[get_effective_balance() adds back open same-day trade costs.]] - rationale - tests/test_paper.py
- [[get_effective_balance() does NOT add back multi-day trade costs.]] - rationale - tests/test_paper.py
- [[get_max_drawdown_pct() uses actual balance for reporting — same-day open costs…]] - rationale - tests/test_paper.py
- [[is_paused_drawdown() stays False when balance dips below halt only due to open…]] - rationale - tests/test_paper.py
- [[kelly_bet_dollars should return 0.0 when in drawdown.]] - rationale - tests/test_paper.py
- [[kelly_bet_dollars works normally when balance = $500 (capped at $50).]] - rationale - tests/test_paper.py
- [[reset_peak_balance() raises ValueError without confirmed=True.]] - rationale - tests/test_paper.py
- [[reset_peak_balance() resets peak to current balance, preserving trades.]] - rationale - tests/test_paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_106
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 56]]

## Top bridge nodes
- [[TestMaxDrawdown]] - degree 16, connects to 2 communities