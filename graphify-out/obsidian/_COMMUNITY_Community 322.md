---
type: community
cohesion: 0.17
members: 12
---

# Community 322

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-setUp()_22]] - code - tests/test_tracker.py
- [[dot-tearDown()_21]] - code - tests/test_tracker.py
- [[dot-test_candle_missing_end_period_ts_is_skipped()]] - code - tests/test_tracker.py
- [[dot-test_dedup_via_unique_index_is_idempotent()]] - code - tests/test_tracker.py
- [[dot-test_empty_candlesticks_list_is_noop()]] - code - tests/test_tracker.py
- [[dot-test_get_price_history_orders_by_end_period_ts()]] - code - tests/test_tracker.py
- [[dot-test_logs_and_retrieves_candle()]] - code - tests/test_tracker.py
- [[dot-test_null_price_field_stored_as_none()]] - code - tests/test_tracker.py
- [[A candle with no trades in-period has price=None (only bidask quotes).]] - rationale - tests/test_tracker.py
- [[Re-inserting the same tickerperiodend_ts candle is a no-op.]] - rationale - tests/test_tracker.py
- [[TestPriceHistory]] - code - tests/test_tracker.py
- [[log_price_candles  get_price_history — OHLC candlestick storage.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_322
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 35]]

## Top bridge nodes
- [[TestPriceHistory]] - degree 10, connects to 1 community