---
type: community
cohesion: 0.07
members: 57
---

# Execution Log Live-Loss Tracking

**Cohesion:** 0.07 - loosely connected
**Members:** 57 nodes

## Members
- [[Add amount to today's live loss total and return the new total. amount  0…]] - rationale - execution_log.py
- [[Append a single entry dict as a JSONL line to the entries log.]] - rationale - execution_log.py
- [[Apply any pending schema migrations and advance PRAGMA user_version. Mirrors…]] - rationale - execution_log.py
- [[Connection]] - code
- [[Execution log — SQLite-backed audit trail of every live order attempt. Prevents…]] - rationale - execution_log.py
- [[Export settled live orders to CSV for tax reporting. Filters to live=1,…]] - rationale - execution_log.py
- [[Fetch a single order record by id from execution_log.db.]] - rationale - execution_log.py
- [[LiveTradingGate.check()pre_live_trade_check()]] - code - trading_gates.py
- [[Mark an open live position closed via an early protective exit (stop-…]] - rationale - execution_log.py
- [[PaperPositionStore.save_peak]] - code - paper.py
- [[Path_9]] - code
- [[Place a live Kalshi order with hard-stop guards. Returns (placed, dollar_cost).…]] - rationale - order_executor.py
- [[Reconcile an open live position's tracked size after an IOC exit order only…]] - rationale - execution_log.py
- [[Record a live order attempt. Returns the new row ID. Call with status='sent'…]] - rationale - execution_log.py
- [[Record a new peak unrealized-profit fraction for an open live position (mirrors…]] - rationale - execution_log.py
- [[Return True if a filled order for this ticker was placed within the last N…]] - rationale - execution_log.py
- [[Return True if an order for this ticker+side was placed within the last N…]] - rationale - execution_log.py
- [[Return True if an order for ticker+side was placed on this forecast cycle.]] - rationale - execution_log.py
- [[Return live filled orders that have not yet had their settlement outcome…]] - rationale - execution_log.py
- [[Return live order P&L summary for the dashboard. Returns today_pnl sum of pnl…]] - rationale - execution_log.py
- [[Return today's accumulated live loss in dollars (UTC date). Fails closed if a…]] - rationale - execution_log.py
- [[Return today's cumulative live order spend in dollars (UTC date), across every…]] - rationale - execution_log.py
- [[Tests for execution_log schema migration and cycle-aware deduplication.]] - rationale - tests/test_execution_log.py
- [[True if a prior add_live_loss() failure left today's total untrustworthy.]] - rationale - execution_log.py
- [[Update an existing order log entry with the final statusresponse. Structured…]] - rationale - execution_log.py
- [[Write settlement outcome to an order row. outcome_yes=True means the YES side…]] - rationale - execution_log.py
- [[_clear_degraded_flag()]] - code - execution_log.py
- [[_conn()]] - code - execution_log.py
- [[_degraded_flag_path()]] - code - execution_log.py
- [[_degraded_for_today()]] - code - execution_log.py
- [[_place_live_order()]] - code - order_executor.py
- [[_run_migrations()]] - code - execution_log.py
- [[_set_degraded_flag()]] - code - execution_log.py
- [[add_live_loss()]] - code - execution_log.py
- [[append_entry()]] - code - execution_log.py
- [[execution_log._MIGRATIONS  _SCHEMA_VERSION]] - code - execution_log.py
- [[execution_log.py]] - code - execution_log.py
- [[execution_log.py File Grade median 7-810, 2 RF1 promotions]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[execution_log.py Grade Audit]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[export_live_tax_csv()]] - code - execution_log.py
- [[get_filled_unsettled_live_orders()]] - code - execution_log.py
- [[get_live_pnl_summary()]] - code - execution_log.py
- [[get_order_by_id()]] - code - execution_log.py
- [[get_today_live_loss()]] - code - execution_log.py
- [[get_today_live_spend()]] - code - execution_log.py
- [[init_log()]] - code - execution_log.py
- [[log_order()]] - code - execution_log.py
- [[log_order() json.dumps Failure Returns id=0 (710)]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[log_order_result()]] - code - execution_log.py
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
TABLE source_file, type FROM #community/Execution_Log_Live-Loss_Tracking
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 8 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 8 edges to [[_COMMUNITY_Black Swan Halt State]]
- 7 edges to [[_COMMUNITY_Community 110]]
- 6 edges to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 5 edges to [[_COMMUNITY_Community 422]]
- 4 edges to [[_COMMUNITY_Community 97]]
- 3 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 3 edges to [[_COMMUNITY_Community 67]]
- 3 edges to [[_COMMUNITY_Community 111]]
- 2 edges to [[_COMMUNITY_Community 195]]
- 2 edges to [[_COMMUNITY_Community 40]]
- 2 edges to [[_COMMUNITY_Community 389]]
- 1 edge to [[_COMMUNITY_Community 167]]
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Community 157]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Community 248]]
- 1 edge to [[_COMMUNITY_Community 183]]
- 1 edge to [[_COMMUNITY_Community 143]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 274]]
- 1 edge to [[_COMMUNITY_Community 363]]
- 1 edge to [[_COMMUNITY_Community 133]]
- 1 edge to [[_COMMUNITY_Community 256]]
- 1 edge to [[_COMMUNITY_Community 421]]
- 1 edge to [[_COMMUNITY_Community 393]]
- 1 edge to [[_COMMUNITY_Community 497]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 225]]
- 1 edge to [[_COMMUNITY_Community 96]]
- 1 edge to [[_COMMUNITY_Community 351]]

## Top bridge nodes
- [[test_execution_log.py]] - degree 21, connects to 9 communities
- [[_place_live_order()]] - degree 17, connects to 9 communities
- [[log_order()]] - degree 15, connects to 9 communities
- [[execution_log.py]] - degree 41, connects to 8 communities
- [[log_order_result()]] - degree 14, connects to 8 communities