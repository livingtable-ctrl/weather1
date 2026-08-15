---
type: community
cohesion: 0.06
members: 47
---

# Community 37

**Cohesion:** 0.06 - loosely connected
**Members:** 47 nodes

## Members
- [[dot-test_brier_scores_in_valid_range()]] - code - tests/test_walk_forward.py
- [[dot-test_creates_correct_number_of_folds()]] - code - tests/test_walk_forward.py
- [[dot-test_each_fold_has_brier_score()]] - code - tests/test_walk_forward.py
- [[dot-test_find_optimal_min_edge_called_with_training_data_only()]] - code - tests/test_p1_remaining.py
- [[dot-test_fold_results_include_optimal_min_edge()]] - code - tests/test_p1_remaining.py
- [[dot-test_insufficient_data_returns_empty()]] - code - tests/test_walk_forward.py
- [[dot-test_no_data_leakage()]] - code - tests/test_walk_forward.py
- [[dot-test_optimal_edge_is_median_of_training_folds()]] - code - tests/test_p1_remaining.py
- [[dot-test_result_includes_summary()]] - code - tests/test_walk_forward.py
- [[dot-test_returns_results_dict()]] - code - tests/test_walk_forward.py
- [[dot-test_test_period_advances_each_fold()]] - code - tests/test_walk_forward.py
- [[All fold Brier scores are between 0.0 and 1.0.]] - rationale - tests/test_walk_forward.py
- [[Compute Brier score from a list of trade dicts.]] - rationale - backtest.py
- [[D4 Find the edge threshold that maximises win rate for trades above it.…]] - rationale - backtest.py
- [[D4 Persist walk-forward results so config.py can use optimal_min_edge as a…]] - rationale - backtest.py
- [[Each fold in results has 'brier', 'n_test', 'test_period' keys.]] - rationale - tests/test_walk_forward.py
- [[Each fold result includes 'optimal_min_edge' derived from training data.]] - rationale - tests/test_p1_remaining.py
- [[Each fold's test period is one month later than the previous.]] - rationale - tests/test_walk_forward.py
- [[Less than train_months + test_months of data → empty list.]] - rationale - tests/test_walk_forward.py
- [[Make a minimal trade record for backtesting.]] - rationale - tests/test_walk_forward.py
- [[Path_3]] - code
- [[Result includes overall mean_brier and std_brier across folds.]] - rationale - tests/test_walk_forward.py
- [[Run a walk-forward (rolling out-of-sample) backtest on historical trade data.…]] - rationale - backtest.py
- [[Split trades into walk-forward traintest folds. Each fold trains on start,…]] - rationale - backtest.py
- [[Test period never overlaps with train period in any fold.]] - rationale - tests/test_walk_forward.py
- [[TestWalkForwardBacktest]] - code - tests/test_walk_forward.py
- [[TestWalkForwardNoLookAhead]] - code - tests/test_p1_remaining.py
- [[TestWalkForwardSplit]] - code - tests/test_walk_forward.py
- [[Tests for walk-forward backtesting engine.]] - rationale - tests/test_walk_forward.py
- [[Top-level optimal_min_edge is the median of per-fold training edges.]] - rationale - tests/test_p1_remaining.py
- [[When no windows have data, cmd_walkforward should print a clear no-data message.]] - rationale - tests/test_walk_forward.py
- [[With 12 months of data and window=6, test_size=1 → 6 folds.]] - rationale - tests/test_walk_forward.py
- [[_brier_score_from_trades()]] - code - backtest.py
- [[_fetch_settled_markets must query by series_ticker, not dump all global…]] - rationale - tests/test_walk_forward.py
- [[_find_optimal_min_edge must be called with per-fold training data, not full…]] - rationale - tests/test_p1_remaining.py
- [[_find_optimal_min_edge()]] - code - backtest.py
- [[_make_trade()_2]] - code - tests/test_p1_remaining.py
- [[_make_trade()_6]] - code - tests/test_walk_forward.py
- [[run_walk_forward reads settled predictions from the tracker DB directly; it…]] - rationale - tests/test_walk_forward.py
- [[save_walk_forward_params()]] - code - backtest.py
- [[test_fetch_settled_markets_queries_by_weather_series()]] - code - tests/test_walk_forward.py
- [[test_run_walk_forward_reads_from_db_not_run_backtest()]] - code - tests/test_walk_forward.py
- [[test_walk_forward.py]] - code - tests/test_walk_forward.py
- [[test_walkforward_prints_no_data_message_when_empty()]] - code - tests/test_walk_forward.py
- [[walk_forward_backtest returns a dict with 'folds' list.]] - rationale - tests/test_walk_forward.py
- [[walk_forward_backtest()]] - code - backtest.py
- [[walk_forward_split()]] - code - backtest.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_37
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 4 edges to [[_COMMUNITY_Community 96]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 1 edge to [[_COMMUNITY_Community 454]]
- 1 edge to [[_COMMUNITY_Community 118]]

## Top bridge nodes
- [[walk_forward_backtest()]] - degree 17, connects to 4 communities
- [[save_walk_forward_params()]] - degree 6, connects to 3 communities
- [[walk_forward_split()]] - degree 10, connects to 2 communities
- [[TestWalkForwardNoLookAhead]] - degree 6, connects to 2 communities
- [[_make_trade()_2]] - degree 4, connects to 1 community