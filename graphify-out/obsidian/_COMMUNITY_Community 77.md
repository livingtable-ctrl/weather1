---
type: community
cohesion: 0.10
members: 32
---

# Community 77

**Cohesion:** 0.10 - loosely connected
**Members:** 32 nodes

## Members
- [[dot-_candles()]] - code - tests/test_tracker.py
- [[dot-_settle()_1]] - code - tests/test_tracker.py
- [[dot-_settle()]] - code - tests/test_tracker.py
- [[dot-setUp()_43]] - code - tests/test_tracker.py
- [[dot-setUp()_42]] - code - tests/test_tracker.py
- [[dot-tearDown()_42]] - code - tests/test_tracker.py
- [[dot-tearDown()_41]] - code - tests/test_tracker.py
- [[dot-test_backfills_settled_tickers_missing_price_history()]] - code - tests/test_tracker.py
- [[dot-test_candlestick_fetch_failure_for_one_ticker_does_not_abort_the_pass()]] - code - tests/test_tracker.py
- [[dot-test_corrects_stale_proxy_value_from_expiration_value()]] - code - tests/test_tracker.py
- [[dot-test_disputed_rows_are_included()]] - code - tests/test_tracker.py
- [[dot-test_disputed_settled_tickers_are_included()]] - code - tests/test_tracker.py
- [[dot-test_empty_candle_list_does_not_count_as_filled()]] - code - tests/test_tracker.py
- [[dot-test_failed_fetch_leaves_prior_value_untouched()]] - code - tests/test_tracker.py
- [[dot-test_one_get_market_failure_does_not_abort_the_whole_pass()]] - code - tests/test_tracker.py
- [[dot-test_one_ticker_failure_does_not_abort_the_whole_pass()]] - code - tests/test_tracker.py
- [[dot-test_rows_with_null_settled_temp_f_are_not_selected()]] - code - tests/test_tracker.py
- [[dot-test_skips_ticker_with_no_open_time_cleanly_no_warning()]] - code - tests/test_tracker.py
- [[dot-test_skips_tickers_that_already_have_price_history()]] - code - tests/test_tracker.py
- [[dot-test_uses_real_series_ticker_when_get_market_provides_one()]] - code - tests/test_tracker.py
- [[dot-test_zero_when_nothing_has_settled_temp_f()]] - code - tests/test_tracker.py
- [[dot-test_zero_when_nothing_settled()]] - code - tests/test_tracker.py
- [[A ticker whose candles are genuinely unavailable (e.g. past the endpoint's…]] - rationale - tests/test_tracker.py
- [[Deliberately the OPPOSITE of a first-draft version of this test (which asserted…]] - rationale - tests/test_tracker.py
- [[Matches backfill_price_history's own reasoning (see…]] - rationale - tests/test_tracker.py
- [[Missing open_time is a genuine, expected skip condition (not an error) -- must…]] - rationale - tests/test_tracker.py
- [[Rows that never got a settled_temp_f (e.g. hourlymonthly-precip tickers, or a…]] - rationale - tests/test_tracker.py
- [[TestBackfillDailyTempSettlement]] - code - tests/test_tracker.py
- [[TestBackfillPriceHistory]] - code - tests/test_tracker.py
- [[The row already has an (old, ASOS-proxy-derived) settled_temp_f; re-running…]] - rationale - tests/test_tracker.py
- [[tracker.backfill_daily_temp_settlement() -- the one-off recovery pass…]] - rationale - tests/test_tracker.py
- [[tracker.backfill_price_history(client) -- the one-off recovery pass for…]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_77
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestBackfillPriceHistory]] - degree 15, connects to 1 community
- [[TestBackfillDailyTempSettlement]] - degree 11, connects to 1 community