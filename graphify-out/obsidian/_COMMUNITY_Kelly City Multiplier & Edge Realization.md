---
type: community
cohesion: 0.05
members: 51
---

# Kelly City Multiplier & Edge Realization

**Cohesion:** 0.05 - loosely connected
**Members:** 51 nodes

## Members
- [[dot-_make_multiday_trade()]] - code - tests/test_backlog_batch.py
- [[dot-_make_open_trade()]] - code - tests/test_backlog_batch.py
- [[dot-_make_trade()]] - code - tests/test_backlog_batch.py
- [[dot-_mult()]] - code - tests/test_backlog_batch.py
- [[dot-_seed_state()]] - code - tests/test_backlog_batch.py
- [[dot-test_allows_when_under_date_cap()]] - code - tests/test_backlog_batch.py
- [[dot-test_applied_in_portfolio_kelly_fraction()]] - code - tests/test_backlog_batch.py
- [[dot-test_blocks_when_date_cap_reached()]] - code - tests/test_backlog_batch.py
- [[dot-test_buckets_reflect_win_rates()]] - code - tests/test_backlog_batch.py
- [[dot-test_different_dates_are_independent()]] - code - tests/test_backlog_batch.py
- [[dot-test_duplicate_blocked_when_ticker_already_open()]] - code - tests/test_backlog_batch.py
- [[dot-test_excellent_brier_no_reduction()]] - code - tests/test_backlog_batch.py
- [[dot-test_good_brier_slight_reduction()]] - code - tests/test_backlog_batch.py
- [[dot-test_ignores_trades_without_net_edge()]] - code - tests/test_backlog_batch.py
- [[dot-test_ignores_unsettled_trades()]] - code - tests/test_backlog_batch.py
- [[dot-test_multiday_directional_accuracy_excludes_undated_trades()]] - code - tests/test_backlog_batch.py
- [[dot-test_multiday_directional_accuracy_no_zero_division_on_empty()]] - code - tests/test_backlog_batch.py
- [[dot-test_multiday_directional_accuracy_none_below_min_samples()]] - code - tests/test_backlog_batch.py
- [[dot-test_multiday_directional_accuracy_uses_only_recent_window()]] - code - tests/test_backlog_batch.py
- [[dot-test_multiday_directional_accuracy_window_param_controls_size()]] - code - tests/test_backlog_batch.py
- [[dot-test_near_random_brier_meaningful_reduction()]] - code - tests/test_backlog_batch.py
- [[dot-test_neutral_when_city_is_none()]] - code - tests/test_backlog_batch.py
- [[dot-test_neutral_when_city_not_in_cal()]] - code - tests/test_backlog_batch.py
- [[dot-test_neutral_when_insufficient_samples()]] - code - tests/test_backlog_batch.py
- [[dot-test_no_duplicate_when_settled()]] - code - tests/test_backlog_batch.py
- [[dot-test_not_calibrated_below_threshold()]] - code - tests/test_backlog_batch.py
- [[dot-test_poor_brier_heavy_reduction()]] - code - tests/test_backlog_batch.py
- [[dot-test_positive_correlation_when_edge_predicts_wins()]] - code - tests/test_backlog_batch.py
- [[dot-test_returns_empty_when_too_few_trades()]] - code - tests/test_backlog_batch.py
- [[dot-test_tracker_exception_returns_neutral()]] - code - tests/test_backlog_batch.py
- [[A smaller window should be able to see a different (worse) recent streak than a…]] - rationale - tests/test_backlog_batch.py
- [[Below min_samples, return None rather than a noisy small-sample figure —…]] - rationale - tests/test_backlog_batch.py
- [[Cap is per-date 4 positions on May-20 don't block a May-21 trade.]] - rationale - tests/test_backlog_batch.py
- [[Correlation  0.10 should not be marked as calibrated.]] - rationale - tests/test_backlog_batch.py
- [[Higher edge trades should show higher win rate → positive correlation.]] - rationale - tests/test_backlog_batch.py
- [[Settled trades with the same ticker should not block re-entry.]] - rationale - tests/test_backlog_batch.py
- [[System Audit Findings 2026-06-04]] - document - docs/audit_findings_2026-06-04.md
- [[TestCityKellyMultiplier]] - code - tests/test_backlog_batch.py
- [[TestEdgeRealizationRate]] - code - tests/test_backlog_batch.py
- [[TestMaxPositionsPerDate]] - code - tests/test_backlog_batch.py
- [[TestPlacePaperOrderDuplicateGuard]] - code - tests/test_backlog_batch.py
- [[Tests for backlog items 6, 4, 1, 2. 6 - City-level Kelly scaling from…]] - rationale - tests/test_backlog_batch.py
- [[The last `window` trades (by settled_at) should win 100%; the older trades…]] - rationale - tests/test_backlog_batch.py
- [[Trades missing settled_at (a real historical data state) must be excluded…]] - rationale - tests/test_backlog_batch.py
- [[When 4 positions already expire on a date, a 5th is rejected.]] - rationale - tests/test_backlog_batch.py
- [[With only 2 positions on the date, a 3rd is allowed (cap=4).]] - rationale - tests/test_backlog_batch.py
- [[Write a paper state JSON with an optional open trade.]] - rationale - tests/test_backlog_batch.py
- [[_city_kelly_multiplier is called inside portfolio_kelly_fraction.]] - rationale - tests/test_backlog_batch.py
- [[min_samples=0 with zero trades must not raise ZeroDivisionError — the old…]] - rationale - tests/test_backlog_batch.py
- [[place_paper_order raises ValueError if the same ticker is already open.]] - rationale - tests/test_backlog_batch.py
- [[test_backlog_batch.py]] - code - tests/test_backlog_batch.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Kelly_City_Multiplier__Edge_Realization
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 40]]

## Top bridge nodes
- [[test_backlog_batch.py]] - degree 7, connects to 2 communities
- [[System Audit Findings 2026-06-04]] - degree 1, connects to 1 community