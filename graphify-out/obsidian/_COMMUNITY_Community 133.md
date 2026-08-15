---
type: community
cohesion: 0.09
members: 23
---

# Community 133

**Cohesion:** 0.09 - loosely connected
**Members:** 23 nodes

## Members
- [[dot-setup_method()_7]] - code - tests/test_execution_log.py
- [[dot-teardown_method()_7]] - code - tests/test_execution_log.py
- [[dot-test_exit_orders_own_filled_row_excluded_from_open_positions()]] - code - tests/test_execution_log.py
- [[dot-test_export_live_tax_csv_filters_by_year()]] - code - tests/test_execution_log.py
- [[dot-test_export_live_tax_csv_labels_early_exit_not_no()]] - code - tests/test_execution_log.py
- [[dot-test_get_filled_unsettled_excludes_settled_orders()]] - code - tests/test_execution_log.py
- [[dot-test_get_live_pnl_summary_correct()]] - code - tests/test_execution_log.py
- [[dot-test_log_order_persists_entry_prob()]] - code - tests/test_execution_log.py
- [[dot-test_record_live_early_exit_leaves_outcome_yes_null()]] - code - tests/test_execution_log.py
- [[dot-test_record_live_partial_exit_decrements_relatively_not_absolutely()]] - code - tests/test_execution_log.py
- [[dot-test_record_live_partial_exit_reduces_fill_quantity_keeps_open()]] - code - tests/test_execution_log.py
- [[dot-test_record_live_settlement_writes_outcome()]] - code - tests/test_execution_log.py
- [[dot-test_update_live_peak_profit_does_not_lower_an_already_higher_peak()]] - code - tests/test_execution_log.py
- [[dot-test_update_live_peak_profit_skips_a_settled_row()]] - code - tests/test_execution_log.py
- [[dot-test_update_live_peak_profit_writes_value()]] - code - tests/test_execution_log.py
- [[A concurrent writer's fresher, higher peak must survive a stalelower write…]] - rationale - tests/test_execution_log.py
- [[A partial IOC exit fill must shrink the tracked open quantity by exactly the…]] - rationale - tests/test_execution_log.py
- [[A position closed by another process between the caller's price snapshot and…]] - rationale - tests/test_execution_log.py
- [[An early exit closes the position (settled_at set, excluded from…]] - rationale - tests/test_execution_log.py
- [[Regression `yes if rowoutcome_yes else no` silently wrote no…]] - rationale - tests/test_execution_log.py
- [[Regression a filled exit (SELL) order's own row is live=1, status='filled',…]] - rationale - tests/test_execution_log.py
- [[TestLiveSettlement]] - code - tests/test_execution_log.py
- [[The UPDATE must compute fill_quantity - filled_count IN SQL, not have the…]] - rationale - tests/test_execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_133
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]

## Top bridge nodes
- [[TestLiveSettlement]] - degree 16, connects to 1 community