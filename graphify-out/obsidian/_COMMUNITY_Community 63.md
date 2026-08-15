---
type: community
cohesion: 0.12
members: 35
---

# Community 63

**Cohesion:** 0.12 - loosely connected
**Members:** 35 nodes

## Members
- [[dot-_call()_3]] - code - tests/test_phase2_batch_n.py
- [[dot-_call()_4]] - code - tests/test_phase2_batch_o.py
- [[dot-_paper_spend()]] - code - tests/test_phase2_batch_o.py
- [[dot-_sameday_spend()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_combined_totals_add_up()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_empty_trades()]] - code - tests/test_phase2_batch_n.py
- [[dot-test_empty_trades()_1]] - code - tests/test_phase2_batch_o.py
- [[dot-test_legacy_none_days_out_included()]] - code - tests/test_phase2_batch_n.py
- [[dot-test_legacy_none_excluded()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_mixed_only_sameday_summed()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_mixed_same_day_and_multiday()]] - code - tests/test_phase2_batch_n.py
- [[dot-test_multiday_trade_excluded()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_multiday_trade_not_counted_in_sameday()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_multiday_trades_included()]] - code - tests/test_phase2_batch_n.py
- [[dot-test_multiple_multiday_summed()]] - code - tests/test_phase2_batch_n.py
- [[dot-test_multiple_sameday_summed()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_same_day_trades_excluded()]] - code - tests/test_phase2_batch_n.py
- [[dot-test_same_trade_not_counted_in_both()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_sameday_trade_counted()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_yesterday_sameday_not_counted()]] - code - tests/test_phase2_batch_o.py
- [[dot-test_yesterday_trades_not_counted()]] - code - tests/test_phase2_batch_n.py
- [[Phase 2 Batch N Daily Spend Tests]] - code - tests/test_phase2_batch_n.py
- [[Phase 2 Batch O Same-Day Spend Tests]] - code - tests/test_phase2_batch_o.py
- [[Sum of same-day paper trade costs placed today (UTC date). Used for same-day…]] - rationale - order_executor.py
- [[TestCapIndependence]] - code - tests/test_phase2_batch_o.py
- [[TestDailyPaperSpend]] - code - tests/test_phase2_batch_n.py
- [[TestDailySamedaySpend]] - code - tests/test_phase2_batch_o.py
- [[The two caps read from non-overlapping trade subsets — no double-counting.]] - rationale - tests/test_phase2_batch_o.py
- [[_daily_paper_spend() must only sum multi-day trade costs.]] - rationale - tests/test_phase2_batch_n.py
- [[_daily_sameday_spend()]] - code - order_executor.py
- [[_daily_sameday_spend() must only sum days_out==0 trade costs.]] - rationale - tests/test_phase2_batch_o.py
- [[_make_trade()_5]] - code - tests/test_phase2_batch_n.py
- [[_make_trade()_6]] - code - tests/test_phase2_batch_o.py
- [[test_phase2_batch_n.py — Tests for order_executor daily spend cap separation.…]] - rationale - tests/test_phase2_batch_n.py
- [[test_phase2_batch_o.py — Tests for same-day spend cap (MAX_SAME_DAY_SPEND).…]] - rationale - tests/test_phase2_batch_o.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_63
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]

## Top bridge nodes
- [[_daily_sameday_spend()]] - degree 7, connects to 2 communities
- [[dot-_call()_3]] - degree 9, connects to 1 community
- [[Phase 2 Batch O Same-Day Spend Tests]] - degree 7, connects to 1 community
- [[Phase 2 Batch N Daily Spend Tests]] - degree 6, connects to 1 community
- [[dot-_paper_spend()]] - degree 5, connects to 1 community