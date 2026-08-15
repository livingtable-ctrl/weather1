---
type: community
cohesion: 0.08
members: 43
---

# Community 45

**Cohesion:** 0.08 - loosely connected
**Members:** 43 nodes

## Members
- [[dot-__init__()_7]] - code - order_executor.py
- [[dot-exit()]] - code - order_executor.py
- [[dot-get_open()]] - code - order_executor.py
- [[dot-get_open()_2]] - code - positions.py
- [[dot-save_peak()]] - code - order_executor.py
- [[dot-save_peak()_2]] - code - positions.py
- [[dot-setup_method()_22]] - code - tests/test_live_execution.py
- [[dot-setup_method()_35]] - code - tests/test_positions.py
- [[dot-teardown_method()_21]] - code - tests/test_live_execution.py
- [[dot-teardown_method()_26]] - code - tests/test_positions.py
- [[dot-test_check_breakeven_stops_is_the_same_object_everywhere()]] - code - tests/test_positions.py
- [[dot-test_check_stop_losses_is_the_same_object_everywhere()]] - code - tests/test_positions.py
- [[dot-test_creates_default_if_missing()]] - code - tests/test_live_execution.py
- [[dot-test_does_not_overwrite_a_higher_stored_peak()]] - code - tests/test_live_execution.py
- [[dot-test_exit_wraps_exit_live_position()]] - code - tests/test_positions.py
- [[dot-test_get_open_converts_filled_unsettled_rows_to_positions()]] - code - tests/test_positions.py
- [[dot-test_records_new_peak_when_higher()]] - code - tests/test_live_execution.py
- [[dot-test_save_peak_called_once_per_improved_position_not_batched()]] - code - tests/test_positions.py
- [[dot-test_save_peak_not_called_when_no_position_improves()]] - code - tests/test_positions.py
- [[dot-test_save_peak_persists_to_execution_log()]] - code - tests/test_positions.py
- [[dot-test_update_peak_profits_is_the_same_object_everywhere()]] - code - tests/test_positions.py
- [[Adapt one _get_live_open_positions() dict into the shared Position shape…]] - rationale - order_executor.py
- [[F6 _open_trades_list.append(trade) only ever ran on the paper branch. A live…]] - rationale - tests/test_live_execution.py
- [[LivePositionStore]] - code - order_executor.py
- [[Mutation-testing the peak-profit-fix decision the pre-refactor…]] - rationale - tests/test_positions.py
- [[Position]] - code - positions.py
- [[PositionStore backed by execution_log's SQLite rows. See…]] - rationale - order_executor.py
- [[Shared execution_log DB isolation for the live-position-protection test classes…]] - rationale - tests/test_live_execution.py
- [[TestLivePositionStore]] - code - tests/test_positions.py
- [[TestLoadLiveConfig]] - code - tests/test_live_execution.py
- [[TestOpenTradesListLivePath]] - code - tests/test_live_execution.py
- [[TestSharedAcrossPaperAndLive]] - code - tests/test_positions.py
- [[TestUpdateLivePeakProfits]] - code - tests/test_live_execution.py
- [[TestUpdatePeakProfitsSavesPerPosition]] - code - tests/test_positions.py
- [[Tests for positions.py -- the shared Position read-model paper.py and…]] - rationale - tests/test_positions.py
- [[The subset of an open position's fields NOT the full stored record on either…]] - rationale - positions.py
- [[The whole point of this module paper.py and order_executor.py must be calling…]] - rationale - tests/test_positions.py
- [[Update peak_profit_pct on open positions if current unrealized profit is a new…]] - rationale - positions.py
- [[_LiveDBTestBase]] - code - tests/test_live_execution.py
- [[_live_dict_to_position()]] - code - order_executor.py
- [[order_executor._update_live_peak_profits was superseded by the shared…]] - rationale - tests/test_live_execution.py
- [[test_positions.py]] - code - tests/test_positions.py
- [[update_peak_profits()]] - code - positions.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_45
SORT file.name ASC
```

## Connections to other communities
- 17 edges to [[_COMMUNITY_Community 111]]
- 15 edges to [[_COMMUNITY_Community 145]]
- 8 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 8 edges to [[_COMMUNITY_Community 110]]
- 8 edges to [[_COMMUNITY_Community 144]]
- 5 edges to [[_COMMUNITY_Community 56]]
- 4 edges to [[_COMMUNITY_Community 215]]
- 4 edges to [[_COMMUNITY_Community 157]]
- 4 edges to [[_COMMUNITY_Community 67]]
- 4 edges to [[_COMMUNITY_Community 484]]
- 4 edges to [[_COMMUNITY_Community 159]]
- 3 edges to [[_COMMUNITY_Community 138]]
- 3 edges to [[_COMMUNITY_Community 370]]
- 2 edges to [[_COMMUNITY_Community 40]]
- 2 edges to [[_COMMUNITY_Community 300]]
- 2 edges to [[_COMMUNITY_Community 429]]
- 2 edges to [[_COMMUNITY_Community 468]]
- 2 edges to [[_COMMUNITY_Community 469]]
- 2 edges to [[_COMMUNITY_Community 337]]
- 2 edges to [[_COMMUNITY_Community 171]]
- 2 edges to [[_COMMUNITY_Community 338]]
- 2 edges to [[_COMMUNITY_Community 389]]
- 2 edges to [[_COMMUNITY_Community 329]]
- 2 edges to [[_COMMUNITY_Community 401]]
- 1 edge to [[_COMMUNITY_Community 33]]
- 1 edge to [[_COMMUNITY_Community 183]]
- 1 edge to [[_COMMUNITY_Community 354]]
- 1 edge to [[_COMMUNITY_Community 259]]
- 1 edge to [[_COMMUNITY_Community 258]]
- 1 edge to [[_COMMUNITY_Community 459]]
- 1 edge to [[_COMMUNITY_Community 343]]
- 1 edge to [[_COMMUNITY_Community 188]]
- 1 edge to [[_COMMUNITY_Community 478]]
- 1 edge to [[_COMMUNITY_Community 479]]
- 1 edge to [[_COMMUNITY_Community 402]]
- 1 edge to [[_COMMUNITY_Community 513]]
- 1 edge to [[_COMMUNITY_Community 371]]
- 1 edge to [[_COMMUNITY_Community 280]]
- 1 edge to [[_COMMUNITY_Community 150]]
- 1 edge to [[_COMMUNITY_Community 250]]
- 1 edge to [[_COMMUNITY_Community 106]]
- 1 edge to [[_COMMUNITY_Community 87]]
- 1 edge to [[_COMMUNITY_Community 107]]
- 1 edge to [[_COMMUNITY_Community 330]]
- 1 edge to [[_COMMUNITY_Community 272]]
- 1 edge to [[_COMMUNITY_Community 463]]
- 1 edge to [[_COMMUNITY_Community 235]]
- 1 edge to [[_COMMUNITY_Community 85]]
- 1 edge to [[_COMMUNITY_Community 125]]

## Top bridge nodes
- [[Position]] - degree 92, connects to 40 communities
- [[LivePositionStore]] - degree 51, connects to 21 communities
- [[update_peak_profits()]] - degree 20, connects to 8 communities
- [[test_positions.py]] - degree 14, connects to 5 communities
- [[_LiveDBTestBase]] - degree 11, connects to 3 communities