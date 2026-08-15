---
type: community
cohesion: 0.11
members: 19
---

# Community 171

**Cohesion:** 0.11 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-setup_method()_14]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_13]] - code - tests/test_live_execution.py
- [[dot-test_gtc_age_cancel_with_partial_fill_resolves_to_filled()]] - code - tests/test_live_execution.py
- [[dot-test_gtc_cancel_fires_for_old_pending_order()]] - code - tests/test_live_execution.py
- [[dot-test_gtc_cancel_skips_fresh_orders()]] - code - tests/test_live_execution.py
- [[dot-test_no_side_settlement_no_wins()]] - code - tests/test_live_execution.py
- [[dot-test_no_side_settlement_yes_wins()]] - code - tests/test_live_execution.py
- [[dot-test_settlement_loss_does_not_double_count()]] - code - tests/test_live_execution.py
- [[dot-test_settlement_recorded_for_finalized_market()]] - code - tests/test_live_execution.py
- [[dot-test_settlement_win_credits_the_counter()]] - code - tests/test_live_execution.py
- [[F7 a losing settlement must add exactly the loss to the daily counter, not…]] - rationale - tests/test_live_execution.py
- [[F7 a winning settlement must credit (reduce) the daily counter — under the old…]] - rationale - tests/test_live_execution.py
- [[F9 followup cancel_order() alone doesn't reveal whether the order partially…]] - rationale - tests/test_live_execution.py
- [[NO bet loses when YES wins pnl = -qty  price (NO contract cost).]] - rationale - tests/test_live_execution.py
- [[NO bet wins when NO wins pnl = qty  (1 - price)  (1 - fee).]] - rationale - tests/test_live_execution.py
- [[Orders older than gtc_cancel_hours are cancelled via the API.]] - rationale - tests/test_live_execution.py
- [[Orders younger than gtc_cancel_hours are not cancelled.]] - rationale - tests/test_live_execution.py
- [[TestPollPendingOrdersExtended]] - code - tests/test_live_execution.py
- [[When a filled YES order's market is finalized (YES wins), P&L is computed and…]] - rationale - tests/test_live_execution.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_171
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 111]]

## Top bridge nodes
- [[TestPollPendingOrdersExtended]] - degree 13, connects to 2 communities