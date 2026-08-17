---
type: community
cohesion: 0.05
members: 63
---

# Community 16

**Cohesion:** 0.05 - loosely connected
**Members:** 63 nodes

## Members
- [[dot-_daily_market()]] - code - tests/test_rain_markets.py
- [[dot-_history_all_years_value()]] - code - tests/test_rain_markets.py
- [[dot-_history_all_years_value()_1]] - code - tests/test_rain_markets.py
- [[dot-_mock_acis()]] - code - tests/test_rain_markets.py
- [[dot-_pin_today()]] - code - tests/test_rain_markets.py
- [[dot-_rain_market()]] - code - tests/test_rain_markets.py
- [[dot-test_after_month_end_any_missing_day_fails_closed()]] - code - tests/test_rain_markets.py
- [[dot-test_bare_ticker_dict_hits_no_city_not_the_old_guard()]] - code - tests/test_rain_markets.py
- [[dot-test_bias_correction_keyed_on_close_dt_month_not_accrual_month()]] - code - tests/test_rain_markets.py
- [[dot-test_boundary_exactly_16_day_horizon_does_fetch()]] - code - tests/test_rain_markets.py
- [[dot-test_boundary_just_over_16_days_skips_fetch()]] - code - tests/test_rain_markets.py
- [[dot-test_daily_high_ticker_unaffected()]] - code - tests/test_rain_markets.py
- [[dot-test_days_out_at_rain_max_boundary_passes_days_out_gate()]] - code - tests/test_rain_markets.py
- [[dot-test_days_out_beyond_rain_max_gates_out()]] - code - tests/test_rain_markets.py
- [[dot-test_ensemble_fetch_none_fails_open()]] - code - tests/test_rain_markets.py
- [[dot-test_fetch_exception_fails_open_not_raised()]] - code - tests/test_rain_markets.py
- [[dot-test_full_coverage_logs_signal_without_changing_forecast_prob()]] - code - tests/test_rain_markets.py
- [[dot-test_full_pipeline_produces_real_result()]] - code - tests/test_rain_markets.py
- [[dot-test_mixed_list_daily_fit_unaffected_by_rain_siblings()]] - code - tests/test_rain_markets.py
- [[dot-test_month_to_date_any_missing_day_fails_closed()]] - code - tests/test_rain_markets.py
- [[dot-test_month_to_date_fetch_failure_fails_closed_not_zero()]] - code - tests/test_rain_markets.py
- [[dot-test_month_to_date_zero_missing_still_trades()]] - code - tests/test_rain_markets.py
- [[dot-test_no_forecast_no_date_past_date_gates_never_fire_for_rain()]] - code - tests/test_rain_markets.py
- [[dot-test_no_historical_data_returns_none()]] - code - tests/test_rain_markets.py
- [[dot-test_past_close_time_gates_out()]] - code - tests/test_rain_markets.py
- [[dot-test_rain_key_used_even_if_parse_city_date_were_patched()]] - code - tests/test_rain_markets.py
- [[dot-test_rain_only_list_produces_a_real_distribution()]] - code - tests/test_rain_markets.py
- [[dot-test_remaining_window_exceeds_16_days_skips_signal()]] - code - tests/test_rain_markets.py
- [[dot-test_seasonal_tilt_applied_reaches_full_pipeline()]] - code - tests/test_rain_markets.py
- [[dot-test_thin_member_count_fails_open()]] - code - tests/test_rain_markets.py
- [[dot-test_ticket_checked_after_month_end_does_not_crash()]] - code - tests/test_rain_markets.py
- [[dot-test_too_few_historical_years_returns_none()]] - code - tests/test_rain_markets.py
- [[dot-test_unmapped_city_station_returns_none()]] - code - tests/test_rain_markets.py
- [[A raw exception inside the ensemble fetch must be caught by the new block's own…]] - rationale - tests/test_rain_markets.py
- [[Calling analyze_trade() directly with a bare {ticker ...} dict (no…]] - rationale - tests/test_rain_markets.py
- [[Control for the guard above zero missing days must NOT be refused -- confirms…]] - rationale - tests/test_rain_markets.py
- [[Fetch failure  fully-outside-horizon (returns None) must not affect the trade…]] - rationale - tests/test_rain_markets.py
- [[Fewer than 15 members (the bootstrap_ci_month_total-matching trust floor) must…]] - rationale - tests/test_rain_markets.py
- [[Freeze weather_markets.datetime.now() to 2026-07-day 1200, honoring the…]] - rationale - tests/test_rain_markets.py
- [[Inverse of the above today=Jul 16 - (Jul 31 - Jul 16).days == 15, exactly at…]] - rationale - tests/test_rain_markets.py
- [[Off-by-one check exactly RAIN_MAX_DAYS_OUT days out must NOT hit the days_out…]] - rationale - tests/test_rain_markets.py
- [[Opus-review-caught HIGH finding (Snow Step 2 review, identical gap in this…]] - rationale - tests/test_rain_markets.py
- [[Opus-review-caught gap only two widely-separated points (11 and 30 days via…]] - rationale - tests/test_rain_markets.py
- [[Opus-review-caught reachability a July-accrual ticket can be analyzed after…]] - rationale - tests/test_rain_markets.py
- [[Opus-review-caught test gap (round 2) the already past month-end branch…]] - rationale - tests/test_rain_markets.py
- [[Rain siblings must not leak into the temperature event's own fit -- they're…]] - rationale - tests/test_rain_markets.py
- [[Regression control an ordinary daily HIGH ticker with no forecast data must…]] - rationale - tests/test_rain_markets.py
- [[Regression guard for the routing order rain tickers must be routed to…]] - rationale - tests/test_rain_markets.py
- [[Remaining window (Jul 1-31 = 31 days) exceeds the 16-day forecast horizon --…]] - rationale - tests/test_rain_markets.py
- [[Remaining window (Jul 20-31 = 12 days) fits entirely inside the 16-day forecast…]] - rationale - tests/test_rain_markets.py
- [[Resolved-decision 3 (backlog.txt Step 2 plan) get_quintile_bias must be…]] - rationale - tests/test_rain_markets.py
- [[Review-caught gap every other end-to-end test mocks…]] - rationale - tests/test_rain_markets.py
- [[Review-caught gap fetch_month_to_date_actual() returns (None, 0) both when…]] - rationale - tests/test_rain_markets.py
- [[Step 2 Step 1's unconditional return-None guard is gone. Rain tickers now…]] - rationale - tests/test_rain_markets.py
- [[TestAnalyzeMonthlyRainTradeEndToEnd]] - code - tests/test_rain_markets.py
- [[TestAnalyzeTradeMonthlyRainGating]] - code - tests/test_rain_markets.py
- [[TestComputeMarketImpliedGroupsMonthlyRain]] - code - tests/test_rain_markets.py
- [[TestRainForecastBlendSignal]] - code - tests/test_rain_markets.py
- [[The actual regression this backlog entry fixes a rain-only ladder must now be…]] - rationale - tests/test_rain_markets.py
- [[The daily-specific gates this ticker family is exempted from must genuinely…]] - rationale - tests/test_rain_markets.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 handoff item 1 the real…]] - rationale - tests/test_rain_markets.py
- [[backlog.txt RAIN MARKETS -- LADDERSIBLING GROUPING FOR MARKET- IMPLIED…]] - rationale - tests/test_rain_markets.py
- [[backlog.txt RAIN MARKETS -- MONTHLY MODEL HAS NO DAY-SPECIFIC FORECAST…]] - rationale - tests/test_rain_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_16
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestRainForecastBlendSignal]] - degree 14, connects to 1 community
- [[TestAnalyzeMonthlyRainTradeEndToEnd]] - degree 12, connects to 1 community
- [[TestAnalyzeTradeMonthlyRainGating]] - degree 8, connects to 1 community
- [[TestComputeMarketImpliedGroupsMonthlyRain]] - degree 7, connects to 1 community