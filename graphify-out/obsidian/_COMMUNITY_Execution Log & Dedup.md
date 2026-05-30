---
type: community
cohesion: 0.07
members: 60
---

# Execution Log & Dedup

**Cohesion:** 0.07 - loosely connected
**Members:** 60 nodes

## Members
- [[A pendingsentfilled order today must still block re-entry (P1-13).]] - rationale - tests/test_dedup.py
- [[A ticker logged via log_order today must return True for the same side.]] - rationale - tests/test_dedup.py
- [[A ticker never traded today must return False.]] - rationale - tests/test_dedup.py
- [[A ticker with only a failed order today must return False (P1-13).]] - rationale - tests/test_dedup.py
- [[Add amount to today's live loss total and return the new total.      amount]] - rationale - execution_log.py
- [[Append a single entry dict as a JSONL line to the entries log.]] - rationale - execution_log.py
- [[Connection]] - code - execution_log.py
- [[Execution log — SQLite-backed audit trail of every live order attempt. Prevents]] - rationale - execution_log.py
- [[Export settled live orders to CSV for tax reporting.      Filters to live=1, s]] - rationale - execution_log.py
- [[Fetch a single order record by id from execution_log.db.]] - rationale - execution_log.py
- [[P1-11 target_date fixture must always return a future date, not a hardcoded pas]] - rationale - tests/test_dedup.py
- [[P2-A dedup guard must fire in live=True mode, not just paper mode.      When]] - rationale - tests/test_dedup.py
- [[Path_5]] - code - execution_log.py
- [[Record a live order attempt. Returns the new row ID.     Call with status='sent]] - rationale - execution_log.py
- [[Return True if a filled order for this ticker was placed within the last N days.]] - rationale - execution_log.py
- [[Return True if an order for this ticker+side was placed within the last N minute]] - rationale - execution_log.py
- [[Return True if an order for ticker+side was placed on this forecast cycle.]] - rationale - execution_log.py
- [[Return True if this ticker+side was successfully ordered today (UTC).     Exclu]] - rationale - execution_log.py
- [[Return live filled orders that have not yet had their settlement outcome recorde]] - rationale - execution_log.py
- [[Return live order P&L summary for the dashboard.      Returns         today_]] - rationale - execution_log.py
- [[Return the most recent N order log entries.]] - rationale - execution_log.py
- [[Return today's accumulated live loss in dollars (UTC date). Returns 0.0 if no ro]] - rationale - execution_log.py
- [[Tests for P1.5 — was_traded_today() daily dedup guard in execution_log.]] - rationale - tests/test_dedup.py
- [[Traded KXTEST must not block a different ticker.]] - rationale - tests/test_dedup.py
- [[Traded yes must not block a separate no trade on the same ticker.]] - rationale - tests/test_dedup.py
- [[Update an existing order log entry with the final statusresponse.     Structur]] - rationale - execution_log.py
- [[Write settlement outcome to an order row.      outcome_yes=True means the YES]] - rationale - execution_log.py
- [[_auto_place_trades must skip an opp if was_traded_today returns True.]] - rationale - tests/test_dedup.py
- [[_conn()]] - code - execution_log.py
- [[add_live_loss()]] - code - execution_log.py
- [[append_entry()]] - code - execution_log.py
- [[bool_8]] - code - execution_log.py
- [[execution_log.py]] - code - execution_log.py
- [[export_live_tax_csv()]] - code - execution_log.py
- [[float_11]] - code - execution_log.py
- [[get_filled_unsettled_live_orders()]] - code - execution_log.py
- [[get_live_pnl_summary()]] - code - execution_log.py
- [[get_order_by_id()]] - code - execution_log.py
- [[get_recent_orders()]] - code - execution_log.py
- [[get_today_live_loss()]] - code - execution_log.py
- [[init_log()]] - code - execution_log.py
- [[int_8]] - code - execution_log.py
- [[log_order()]] - code - execution_log.py
- [[log_order_result()]] - code - execution_log.py
- [[record_live_settlement()]] - code - execution_log.py
- [[str_11]] - code - execution_log.py
- [[test_auto_place_trades_skips_already_traded_today()]] - code - tests/test_dedup.py
- [[test_dedup.py]] - code - tests/test_dedup.py
- [[test_live_mode_dedup_blocks_already_traded_ticker()]] - code - tests/test_dedup.py
- [[test_target_date_fixture_is_future()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_different_side()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_different_ticker()]] - code - tests/test_dedup.py
- [[test_was_traded_today_false_for_new_ticker()]] - code - tests/test_dedup.py
- [[test_was_traded_today_ignores_failed_orders()]] - code - tests/test_dedup.py
- [[test_was_traded_today_true_after_order()]] - code - tests/test_dedup.py
- [[test_was_traded_today_true_for_non_failed_status()]] - code - tests/test_dedup.py
- [[was_ordered_recently()]] - code - execution_log.py
- [[was_ordered_this_cycle()]] - code - execution_log.py
- [[was_recently_ordered()]] - code - execution_log.py
- [[was_traded_today()]] - code - execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Execution_Log__Dedup
SORT file.name ASC
```

## Connections to other communities
- 10 edges to [[_COMMUNITY_Python Types & Utilities]]
- 4 edges to [[_COMMUNITY_Module frosty]]

## Top bridge nodes
- [[log_order()]] - degree 10, connects to 1 community
- [[was_recently_ordered()]] - degree 9, connects to 1 community
- [[export_live_tax_csv()]] - degree 8, connects to 1 community
- [[log_order_result()]] - degree 8, connects to 1 community
- [[get_order_by_id()]] - degree 7, connects to 1 community