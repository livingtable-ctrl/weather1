---
type: community
cohesion: 0.07
members: 45
---

# Community 39

**Cohesion:** 0.07 - loosely connected
**Members:** 45 nodes

## Members
- [[dot-_candle()]] - code - tests/test_tracker.py
- [[dot-_seed_market()]] - code - tests/test_tracker.py
- [[dot-_trade()_4]] - code - tests/test_tracker.py
- [[dot-_trade()_3]] - code - tests/test_tracker.py
- [[dot-setUp()_35]] - code - tests/test_tracker.py
- [[dot-setUp()_34]] - code - tests/test_tracker.py
- [[dot-tearDown()_35]] - code - tests/test_tracker.py
- [[dot-tearDown()_34]] - code - tests/test_tracker.py
- [[dot-test_below_min_markets_reports_n_but_r_is_none()]] - code - tests/test_tracker.py
- [[dot-test_block_trade_flag_stored_as_one()]] - code - tests/test_tracker.py
- [[dot-test_dedup_via_unique_trade_id_is_idempotent()]] - code - tests/test_tracker.py
- [[dot-test_different_trade_ids_both_stored()]] - code - tests/test_tracker.py
- [[dot-test_early_trade_count_floor_is_enforced()]] - code - tests/test_tracker.py
- [[dot-test_empty_trades_list_is_noop()]] - code - tests/test_tracker.py
- [[dot-test_get_trade_history_orders_by_created_time()]] - code - tests/test_tracker.py
- [[dot-test_last_candle_null_close_walks_back_to_prior_real_close()]] - code - tests/test_tracker.py
- [[dot-test_logs_and_retrieves_trade()]] - code - tests/test_tracker.py
- [[dot-test_mid_candle_null_close_walks_forward_to_next_real_close()]] - code - tests/test_tracker.py
- [[dot-test_missing_price_close_is_skipped()]] - code - tests/test_tracker.py
- [[dot-test_mixed_period_interval_candles_are_filtered()]] - code - tests/test_tracker.py
- [[dot-test_no_data_returns_zero()]] - code - tests/test_tracker.py
- [[dot-test_no_real_price_at_or_after_midpoint_is_skipped_not_inverted()]] - code - tests/test_tracker.py
- [[dot-test_perfect_correlation_across_three_markets()]] - code - tests/test_tracker.py
- [[dot-test_thin_market_too_few_candles_is_skipped_and_counted()]] - code - tests/test_tracker.py
- [[dot-test_thin_market_too_few_trades_is_skipped_and_counted()]] - code - tests/test_tracker.py
- [[dot-test_trade_missing_trade_id_is_skipped()]] - code - tests/test_tracker.py
- [[dot-test_trades_without_matching_price_history_are_excluded_by_join()]] - code - tests/test_tracker.py
- [[dot-test_unparseable_price_stored_as_none()]] - code - tests/test_tracker.py
- [[dot-test_zero_early_volume_is_skipped()]] - code - tests/test_tracker.py
- [[dot-test_zero_variance_guardrail_returns_r_none()]] - code - tests/test_tracker.py
- [[1 early trade (count=100, so early_total  0 on its own) plus 3 late trades -…]] - rationale - tests/test_tracker.py
- [[2 early trades (t=_EARLY_EPOCH, sides from early_sides) + 2 late trades…]] - rationale - tests/test_tracker.py
- [[3 markets share the exact same early_flow (1.0) -- stddev of the flow series is…]] - rationale - tests/test_tracker.py
- [[A malformed price string must not crash the bulk insert -- fail soft on that…]] - rationale - tests/test_tracker.py
- [[A ticker with an extra candle logged at a different period_interval (never…]] - rationale - tests/test_tracker.py
- [[A ticker with trade_history but no price_history at all must not appear in…]] - rationale - tests/test_tracker.py
- [[A trailing candle with no trades in its period reports price_close=None (real…]] - rationale - tests/test_tracker.py
- [[All 4 trades share one identical timestamp - mid_epoch equals that timestamp…]] - rationale - tests/test_tracker.py
- [[Every candle atafter the trade-series midpoint has a NULL close; only candles…]] - rationale - tests/test_tracker.py
- [[Re-inserting the same trade_id is a no-op -- Kalshi's trade_id is globally…]] - rationale - tests/test_tracker.py
- [[TestTradeFlowSettlementCorrelation]] - code - tests/test_tracker.py
- [[TestTradeHistory]] - code - tests/test_tracker.py
- [[The candle landing exactly at the trade-series midpoint has no real close --…]] - rationale - tests/test_tracker.py
- [[get_trade_flow_settlement_correlation -- the PUBLIC TRADE-FLOW SIGNAL did…]] - rationale - tests/test_tracker.py
- [[log_trades  get_trade_history -- PUBLIC TRADES REST BACKFILL storage.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_39
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestTradeFlowSettlementCorrelation]] - degree 21, connects to 1 community
- [[TestTradeHistory]] - degree 13, connects to 1 community