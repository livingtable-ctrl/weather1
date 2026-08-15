---
type: community
cohesion: 0.05
members: 38
---

# Community 56

**Cohesion:** 0.05 - loosely connected
**Members:** 38 nodes

## Members
- [[79 place_paper_order warns when execution exceeds MAX_ORDER_LATENCY_MS.]] - rationale - tests/test_paper.py
- [[8 a trade with net_edge explicitly None (not absent) — e.g. a dashboard order…]] - rationale - tests/test_paper.py
- [[9 undo_last_trade's peak_balance recompute replayed each trade's entry AND…]] - rationale - tests/test_paper.py
- [[dot-test_clean_state_reports_no_errors()]] - code - tests/test_paper.py
- [[dot-test_corrupted_balance_is_detected()]] - code - tests/test_paper.py
- [[dot-test_fast_order_no_warning()]] - code - tests/test_paper.py
- [[dot-test_max_order_latency_constant_exists()]] - code - tests/test_paper.py
- [[dot-test_none_settled_at_does_not_crash()]] - code - tests/test_paper.py
- [[dot-test_peak_recompute_uses_true_chronological_order()]] - code - tests/test_paper.py
- [[dot-test_slow_order_logs_warning()]] - code - tests/test_paper.py
- [[A balance field that doesn't match computed (start + settled_pnl - open_cost)…]] - rationale - tests/test_paper.py
- [[Callers that don't pass reason= (the majority) must not be miscounted as stop-…]] - rationale - tests/test_paper.py
- [[Deep-review followup t.get(settled_at, ) only covers a MISSING key -- a…_1]] - rationale - tests/test_paper.py
- [[Dynamic cap raises above $50 when Brier score is excellent.]] - rationale - tests/test_paper.py
- [[Explicit cap overrides dynamic Brier cap.]] - rationale - tests/test_paper.py
- [[Poor-performing method (Brier  0.20) reduces Kelly by 25%.]] - rationale - tests/test_paper.py
- [[TestGetDailyPnlNoneSettledAt]] - code - tests/test_paper.py
- [[TestMaxOrderLatency]] - code - tests/test_paper.py
- [[TestUndoLastTradePeakBalance]] - code - tests/test_paper.py
- [[TestValidatePaperTradesIntegrity]] - code - tests/test_paper.py
- [[Tests for paper.py — Kelly compounding, balance, order placement, settlement.]] - rationale - tests/test_paper.py
- [[close_paper_early should settle trade at exit price, not $0$1.]] - rationale - tests/test_paper.py
- [[get_portfolio_expected_value sums cost  net_edge across open positions.]] - rationale - tests/test_paper.py
- [[paper.get_stop_loss_accuracy() must only pass stop_loss-tagged exits to…]] - rationale - tests/test_paper.py
- [[place_paper_order should record the UTC hour of entry.]] - rationale - tests/test_paper.py
- [[test_close_paper_early_exit_reason_defaults_to_none()]] - code - tests/test_paper.py
- [[test_close_paper_early_raises_on_unknown_id()]] - code - tests/test_paper.py
- [[test_close_paper_early_records_exit_reason()]] - code - tests/test_paper.py
- [[test_close_paper_early_settles_at_exit_price()]] - code - tests/test_paper.py
- [[test_get_stop_loss_accuracy_filters_to_stop_loss_reason()]] - code - tests/test_paper.py
- [[test_kelly_bet_dollars_dynamic_cap_higher_with_good_brier()]] - code - tests/test_paper.py
- [[test_kelly_bet_dollars_method_scaling_reduces_kelly()]] - code - tests/test_paper.py
- [[test_kelly_bet_dollars_respects_explicit_cap()]] - code - tests/test_paper.py
- [[test_med_edge_and_max_daily_spend_constants_exist()]] - code - tests/test_paper.py
- [[test_paper.py]] - code - tests/test_paper.py
- [[test_place_paper_order_records_entry_hour()]] - code - tests/test_paper.py
- [[test_portfolio_expected_value_does_not_crash_on_explicit_none_net_edge()]] - code - tests/test_paper.py
- [[test_portfolio_expected_value_positive_for_winning_trades()]] - code - tests/test_paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_56
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 45]]
- 3 edges to [[_COMMUNITY_Community 138]]
- 2 edges to [[_COMMUNITY_Community 159]]
- 2 edges to [[_COMMUNITY_Community 280]]
- 2 edges to [[_COMMUNITY_Community 87]]
- 1 edge to [[_COMMUNITY_Community 106]]
- 1 edge to [[_COMMUNITY_Community 107]]
- 1 edge to [[_COMMUNITY_Community 150]]
- 1 edge to [[_COMMUNITY_Community 188]]
- 1 edge to [[_COMMUNITY_Community 250]]
- 1 edge to [[_COMMUNITY_Community 258]]
- 1 edge to [[_COMMUNITY_Community 259]]
- 1 edge to [[_COMMUNITY_Community 330]]
- 1 edge to [[_COMMUNITY_Community 343]]
- 1 edge to [[_COMMUNITY_Community 370]]
- 1 edge to [[_COMMUNITY_Community 371]]
- 1 edge to [[_COMMUNITY_Community 402]]
- 1 edge to [[_COMMUNITY_Community 459]]
- 1 edge to [[_COMMUNITY_Community 478]]
- 1 edge to [[_COMMUNITY_Community 479]]
- 1 edge to [[_COMMUNITY_Community 513]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Community 180]]

## Top bridge nodes
- [[test_paper.py]] - degree 46, connects to 24 communities
- [[TestMaxOrderLatency]] - degree 6, connects to 1 community
- [[TestGetDailyPnlNoneSettledAt]] - degree 4, connects to 1 community
- [[TestUndoLastTradePeakBalance]] - degree 4, connects to 1 community
- [[TestValidatePaperTradesIntegrity]] - degree 4, connects to 1 community