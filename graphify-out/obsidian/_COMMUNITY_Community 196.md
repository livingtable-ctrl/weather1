---
type: community
cohesion: 0.22
members: 17
---

# Community 196

**Cohesion:** 0.22 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-test_days_out_defaults_to_zero_when_absent()]] - code - tests/test_near_settlement_log.py
- [[dot-test_dedup_within_same_hour_via_unique_index()]] - code - tests/test_near_settlement_log.py
- [[dot-test_missing_side_and_entry_prob_reproduces_the_original_silent_failure()]] - code - tests/test_near_settlement_log.py
- [[dot-test_multiple_trades_all_written()]] - code - tests/test_near_settlement_log.py
- [[dot-test_writes_row_with_real_trade_field_names()]] - code - tests/test_near_settlement_log.py
- [[Mutation-style regression a trade record shaped like the analysis dict the old…]] - rationale - tests/test_near_settlement_log.py
- [[Older trade records (pre-days_out field) must still satisfy the NOT NULL…]] - rationale - tests/test_near_settlement_log.py
- [[Path_9]] - code
- [[Regression tests for cron._log_near_settlement_trades. Backstory (backlog.txt…]] - rationale - tests/test_near_settlement_log.py
- [[Shape of a stored paper-trade record, per paper.place_paper_order.]] - rationale - tests/test_near_settlement_log.py
- [[Shape of one check_expiring_trades() entry.]] - rationale - tests/test_near_settlement_log.py
- [[TestLogNearSettlementTrades]] - code - tests/test_near_settlement_log.py
- [[Write near-settlement snapshot rows for future calibration analysis. `near` is…]] - rationale - cron.py
- [[_log_near_settlement_trades()]] - code - cron.py
- [[_near()]] - code - tests/test_near_settlement_log.py
- [[_real_trade()]] - code - tests/test_near_settlement_log.py
- [[test_near_settlement_log.py]] - code - tests/test_near_settlement_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_196
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 40]]

## Top bridge nodes
- [[_log_near_settlement_trades()]] - degree 10, connects to 1 community
- [[test_near_settlement_log.py]] - degree 6, connects to 1 community