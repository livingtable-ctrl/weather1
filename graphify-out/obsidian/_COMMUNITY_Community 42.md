---
type: community
cohesion: 0.09
members: 44
---

# Community 42

**Cohesion:** 0.09 - loosely connected
**Members:** 44 nodes

## Members
- [[Add amount to today's live loss total and return the new total. amount  0…]] - rationale - execution_log.py
- [[Apply any pending schema migrations and advance PRAGMA user_version. Mirrors…]] - rationale - execution_log.py
- [[Connection_2]] - code
- [[Execution log — SQLite-backed audit trail of every live order attempt. Prevents…]] - rationale - execution_log.py
- [[Export settled live orders to CSV for tax reporting. Filters to live=1,…]] - rationale - execution_log.py
- [[Fetch a single order record by id from execution_log.db.]] - rationale - execution_log.py
- [[Mark an open live position closed via an early protective exit (stop-…]] - rationale - execution_log.py
- [[Missing EXECUTION_LOG_PATH Centralization (Possible)]] - document - docs/grade_audit/outputs/paths.py.md
- [[PaperPositionStore.save_peak]] - code - paper.py
- [[Reconcile an open live position's tracked size after an IOC exit order only…]] - rationale - execution_log.py
- [[Record a live order attempt. Returns the new row ID. Call with status='sent'…]] - rationale - execution_log.py
- [[Record a new peak unrealized-profit fraction for an open live position (mirrors…]] - rationale - execution_log.py
- [[Return True if a filled order for this ticker was placed within the last N…]] - rationale - execution_log.py
- [[Return True if an order for this ticker+side was placed within the last N…]] - rationale - execution_log.py
- [[Return True if an order for ticker+side was placed on this forecast cycle.]] - rationale - execution_log.py
- [[Return live filled orders that have not yet had their settlement outcome…]] - rationale - execution_log.py
- [[Return live order P&L summary for the dashboard. Returns today_pnl sum of pnl…]] - rationale - execution_log.py
- [[Return today's cumulative live order spend in dollars (UTC date), across every…]] - rationale - execution_log.py
- [[Tests for execution_log schema migration and cycle-aware deduplication.]] - rationale - tests/test_execution_log.py
- [[Write settlement outcome to an order row. outcome_yes=True means the YES side…]] - rationale - execution_log.py
- [[_clear_degraded_flag()]] - code - execution_log.py
- [[_conn()_1]] - code - execution_log.py
- [[_run_migrations()_1]] - code - execution_log.py
- [[add_live_loss()]] - code - execution_log.py
- [[execution_log._MIGRATIONS  _SCHEMA_VERSION]] - code - execution_log.py
- [[execution_log.py]] - code - execution_log.py
- [[execution_log.py File Grade median 7-810, 2 RF1 promotions]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[execution_log.py Grade Audit]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[export_live_tax_csv()]] - code - execution_log.py
- [[get_filled_unsettled_live_orders()]] - code - execution_log.py
- [[get_live_pnl_summary()]] - code - execution_log.py
- [[get_order_by_id()]] - code - execution_log.py
- [[get_today_live_spend()]] - code - execution_log.py
- [[init_log()]] - code - execution_log.py
- [[log_order()]] - code - execution_log.py
- [[log_order() json.dumps Failure Returns id=0 (710)]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[record_live_early_exit()]] - code - execution_log.py
- [[record_live_partial_exit()]] - code - execution_log.py
- [[record_live_settlement()]] - code - execution_log.py
- [[test_execution_log.py]] - code - tests/test_execution_log.py
- [[update_live_peak_profit()]] - code - execution_log.py
- [[was_ordered_recently()]] - code - execution_log.py
- [[was_ordered_this_cycle()]] - code - execution_log.py
- [[was_recently_ordered()]] - code - execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_42
SORT file.name ASC
```

## Connections to other communities
- 11 edges to [[_COMMUNITY_Community 1]]
- 9 edges to [[_COMMUNITY_Community 3]]
- 9 edges to [[_COMMUNITY_Community 404]]
- 8 edges to [[_COMMUNITY_Community 4]]
- 6 edges to [[_COMMUNITY_Community 0]]
- 6 edges to [[_COMMUNITY_Community 119]]
- 5 edges to [[_COMMUNITY_Community 459]]
- 4 edges to [[_COMMUNITY_Community 110]]
- 4 edges to [[_COMMUNITY_Community 6]]
- 3 edges to [[_COMMUNITY_Community 44]]
- 2 edges to [[_COMMUNITY_Community 12]]
- 2 edges to [[_COMMUNITY_Community 171]]
- 1 edge to [[_COMMUNITY_Community 136]]
- 1 edge to [[_COMMUNITY_Community 253]]
- 1 edge to [[_COMMUNITY_Community 275]]
- 1 edge to [[_COMMUNITY_Community 377]]
- 1 edge to [[_COMMUNITY_Community 416]]
- 1 edge to [[_COMMUNITY_Community 458]]
- 1 edge to [[_COMMUNITY_Community 407]]
- 1 edge to [[_COMMUNITY_Community 220]]
- 1 edge to [[_COMMUNITY_Community 281]]
- 1 edge to [[_COMMUNITY_Community 35]]
- 1 edge to [[_COMMUNITY_Community 33]]
- 1 edge to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[execution_log.py]] - degree 48, connects to 11 communities
- [[test_execution_log.py]] - degree 25, connects to 10 communities
- [[log_order()]] - degree 15, connects to 8 communities
- [[_conn()_1]] - degree 21, connects to 4 communities
- [[init_log()]] - degree 21, connects to 4 communities