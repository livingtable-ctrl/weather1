---
type: community
cohesion: 0.05
members: 67
---

# Community 12

**Cohesion:** 0.05 - loosely connected
**Members:** 67 nodes

## Members
- [[dot-__init__()_2]] - code - order_executor.py
- [[dot-exit()_1]] - code - order_executor.py
- [[dot-get_open()_1]] - code - order_executor.py
- [[dot-get_open()_2]] - code - positions.py
- [[dot-save_peak()_1]] - code - order_executor.py
- [[dot-save_peak()_2]] - code - positions.py
- [[dot-setup_method()_2]] - code - tests/test_live_execution.py
- [[dot-setup_method()_3]] - code - tests/test_live_execution.py
- [[dot-setup_method()_1]] - code - tests/test_positions.py
- [[dot-teardown_method()_2]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_3]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_1]] - code - tests/test_positions.py
- [[dot-test_amended_row_excluded_new_row_counted_once()]] - code - tests/test_live_execution.py
- [[dot-test_creates_default_if_missing()]] - code - tests/test_live_execution.py
- [[dot-test_cycle_dedup_skips_already_ordered()]] - code - tests/test_live_execution.py
- [[dot-test_does_not_overwrite_a_higher_stored_peak()]] - code - tests/test_live_execution.py
- [[dot-test_exit_order_row_excluded_entry_row_counted()]] - code - tests/test_live_execution.py
- [[dot-test_exit_wraps_exit_live_position()]] - code - tests/test_positions.py
- [[dot-test_filled_order_updates_status()]] - code - tests/test_live_execution.py
- [[dot-test_get_open_converts_filled_unsettled_rows_to_positions()]] - code - tests/test_positions.py
- [[dot-test_live_placement_appends_to_open_trades_list()]] - code - tests/test_live_execution.py
- [[dot-test_mutation_amended_included_would_double_count()]] - code - tests/test_live_execution.py
- [[dot-test_places_order_when_not_yet_ordered()]] - code - tests/test_live_execution.py
- [[dot-test_records_new_peak_when_higher()]] - code - tests/test_live_execution.py
- [[dot-test_repeated_partial_exit_retries_do_not_compound_spend()]] - code - tests/test_live_execution.py
- [[dot-test_returns_false_when_already_ordered_this_cycle()]] - code - tests/test_live_execution.py
- [[dot-test_save_peak_called_once_per_improved_position_not_batched()]] - code - tests/test_positions.py
- [[dot-test_save_peak_not_called_when_no_position_improves()]] - code - tests/test_positions.py
- [[dot-test_save_peak_persists_to_execution_log()]] - code - tests/test_positions.py
- [[dot-test_var_computation_error_skips_the_trade()]] - code - tests/test_live_execution.py
- [[A position whose IOC exit partial-fills every cycle logs a fresh exit-order row…]] - rationale - tests/test_live_execution.py
- [[A protective exit (SELL) order reduces existing exposure, it isn't new capital…]] - rationale - tests/test_live_execution.py
- [[AMEND ORDER (V2) get_today_live_spend() must exclude 'amended' rows the same…]] - rationale - tests/test_live_execution.py
- [[Adapt one _get_live_open_positions() dict into the shared Position shape…]] - rationale - order_executor.py
- [[Direct proof the exclusion is load-bearing temporarily querying with 'amended'…]] - rationale - tests/test_live_execution.py
- [[F5 a portfolio_var() exception used to be swallowed at DEBUG and the trade…]] - rationale - tests/test_live_execution.py
- [[F6 _open_trades_list.append(trade) only ever ran on the paper branch. A live…]] - rationale - tests/test_live_execution.py
- [[If was_ordered_this_cycle returns True, no paper or live order is placed.]] - rationale - tests/test_live_execution.py
- [[LivePositionStore]] - code - order_executor.py
- [[LiveTradingGate.check()pre_live_trade_check()]] - code - trading_gates.py
- [[Mutation-testing the peak-profit-fix decision the pre-refactor…]] - rationale - tests/test_positions.py
- [[Position]] - code - positions.py
- [[PositionStore]] - code - positions.py
- [[PositionStore backed by execution_log's SQLite rows. See…]] - rationale - order_executor.py
- [[Positive control order fires when dedup finds no prior order this cycle.]] - rationale - tests/test_live_execution.py
- [[Protocol]] - code
- [[TestAutoPlaceTradesCycleCheck]] - code - tests/test_live_execution.py
- [[TestGetTodayLiveSpendExcludesAmended]] - code - tests/test_live_execution.py
- [[TestGetTodayLiveSpendExcludesExitOrders]] - code - tests/test_live_execution.py
- [[TestLivePositionStore]] - code - tests/test_positions.py
- [[TestLoadLiveConfig]] - code - tests/test_live_execution.py
- [[TestOpenTradesListLivePath]] - code - tests/test_live_execution.py
- [[TestPlaceLiveOrderDedup]] - code - tests/test_live_execution.py
- [[TestPollPendingOrders]] - code - tests/test_live_execution.py
- [[TestUpdateLivePeakProfits]] - code - tests/test_live_execution.py
- [[TestUpdatePeakProfitsSavesPerPosition]] - code - tests/test_positions.py
- [[TestVarGateFailsClosed]] - code - tests/test_live_execution.py
- [[Tests for live execution path in main.py.]] - rationale - tests/test_live_execution.py
- [[The genuinely shared surface between paper.PaperPositionStore and…]] - rationale - positions.py
- [[The subset of an open position's fields NOT the full stored record on either…]] - rationale - positions.py
- [[Update peak_profit_pct on open positions if current unrealized profit is a new…]] - rationale - positions.py
- [[_live_dict_to_position()]] - code - order_executor.py
- [[_place_live_order must return (False, 0.0) when the ticker was already ordered…]] - rationale - tests/test_live_execution.py
- [[_poll_pending_orders updates a pending live order to 'filled' when API returns…]] - rationale - tests/test_live_execution.py
- [[order_executor._update_live_peak_profits was superseded by the shared…]] - rationale - tests/test_live_execution.py
- [[test_live_execution.py]] - code - tests/test_live_execution.py
- [[update_peak_profits()]] - code - positions.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_12
SORT file.name ASC
```

## Connections to other communities
- 15 edges to [[_COMMUNITY_Community 1]]
- 11 edges to [[_COMMUNITY_Community 3]]
- 11 edges to [[_COMMUNITY_Community 73]]
- 10 edges to [[_COMMUNITY_Community 119]]
- 10 edges to [[_COMMUNITY_Community 57]]
- 10 edges to [[_COMMUNITY_Community 137]]
- 8 edges to [[_COMMUNITY_Community 74]]
- 8 edges to [[_COMMUNITY_Community 219]]
- 6 edges to [[_COMMUNITY_Community 21]]
- 4 edges to [[_COMMUNITY_Community 406]]
- 4 edges to [[_COMMUNITY_Community 407]]
- 3 edges to [[_COMMUNITY_Community 107]]
- 3 edges to [[_COMMUNITY_Community 466]]
- 3 edges to [[_COMMUNITY_Community 345]]
- 3 edges to [[_COMMUNITY_Community 525]]
- 3 edges to [[_COMMUNITY_Community 179]]
- 3 edges to [[_COMMUNITY_Community 346]]
- 3 edges to [[_COMMUNITY_Community 423]]
- 3 edges to [[_COMMUNITY_Community 283]]
- 2 edges to [[_COMMUNITY_Community 42]]
- 2 edges to [[_COMMUNITY_Community 336]]
- 2 edges to [[_COMMUNITY_Community 368]]
- 2 edges to [[_COMMUNITY_Community 189]]
- 2 edges to [[_COMMUNITY_Community 427]]
- 2 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 113]]
- 1 edge to [[_COMMUNITY_Community 114]]
- 1 edge to [[_COMMUNITY_Community 116]]
- 1 edge to [[_COMMUNITY_Community 349]]
- 1 edge to [[_COMMUNITY_Community 515]]
- 1 edge to [[_COMMUNITY_Community 516]]
- 1 edge to [[_COMMUNITY_Community 428]]
- 1 edge to [[_COMMUNITY_Community 468]]
- 1 edge to [[_COMMUNITY_Community 385]]
- 1 edge to [[_COMMUNITY_Community 256]]
- 1 edge to [[_COMMUNITY_Community 180]]
- 1 edge to [[_COMMUNITY_Community 194]]
- 1 edge to [[_COMMUNITY_Community 284]]
- 1 edge to [[_COMMUNITY_Community 154]]
- 1 edge to [[_COMMUNITY_Community 209]]
- 1 edge to [[_COMMUNITY_Community 502]]
- 1 edge to [[_COMMUNITY_Community 104]]
- 1 edge to [[_COMMUNITY_Community 236]]
- 1 edge to [[_COMMUNITY_Community 76]]
- 1 edge to [[_COMMUNITY_Community 30]]
- 1 edge to [[_COMMUNITY_Community 335]]
- 1 edge to [[_COMMUNITY_Community 229]]

## Top bridge nodes
- [[Position]] - degree 91, connects to 36 communities
- [[test_live_execution.py]] - degree 54, connects to 18 communities
- [[LivePositionStore]] - degree 50, connects to 18 communities
- [[update_peak_profits()]] - degree 18, connects to 7 communities
- [[PositionStore]] - degree 10, connects to 4 communities