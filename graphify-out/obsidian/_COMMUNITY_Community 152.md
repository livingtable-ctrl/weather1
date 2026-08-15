---
type: community
cohesion: 0.17
members: 21
---

# Community 152

**Cohesion:** 0.17 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-_mock_acis()]] - code - tests/test_rain_markets.py
- [[dot-_pin_today()]] - code - tests/test_rain_markets.py
- [[dot-test_boundary_exactly_16_day_horizon_does_fetch()]] - code - tests/test_rain_markets.py
- [[dot-test_boundary_just_over_16_days_skips_fetch()]] - code - tests/test_rain_markets.py
- [[dot-test_ensemble_fetch_none_fails_open()]] - code - tests/test_rain_markets.py
- [[dot-test_fetch_exception_fails_open_not_raised()]] - code - tests/test_rain_markets.py
- [[dot-test_full_coverage_logs_signal_without_changing_forecast_prob()]] - code - tests/test_rain_markets.py
- [[dot-test_remaining_window_exceeds_16_days_skips_signal()]] - code - tests/test_rain_markets.py
- [[dot-test_thin_member_count_fails_open()]] - code - tests/test_rain_markets.py
- [[dot-test_ticket_checked_after_month_end_does_not_crash()]] - code - tests/test_rain_markets.py
- [[A raw exception inside the ensemble fetch must be caught by the new block's own…]] - rationale - tests/test_rain_markets.py
- [[Fetch failure  fully-outside-horizon (returns None) must not affect the trade…]] - rationale - tests/test_rain_markets.py
- [[Fewer than 15 members (the bootstrap_ci_month_total-matching trust floor) must…]] - rationale - tests/test_rain_markets.py
- [[Freeze weather_markets.datetime.now() to 2026-07-day 1200, honoring the…]] - rationale - tests/test_rain_markets.py
- [[Inverse of the above today=Jul 16 - (Jul 31 - Jul 16).days == 15, exactly at…]] - rationale - tests/test_rain_markets.py
- [[Opus-review-caught gap only two widely-separated points (11 and 30 days via…]] - rationale - tests/test_rain_markets.py
- [[Opus-review-caught reachability a July-accrual ticket can be analyzed after…]] - rationale - tests/test_rain_markets.py
- [[Remaining window (Jul 1-31 = 31 days) exceeds the 16-day forecast horizon --…]] - rationale - tests/test_rain_markets.py
- [[Remaining window (Jul 20-31 = 12 days) fits entirely inside the 16-day forecast…]] - rationale - tests/test_rain_markets.py
- [[TestRainForecastBlendSignal]] - code - tests/test_rain_markets.py
- [[backlog.txt RAIN MARKETS -- MONTHLY MODEL HAS NO DAY-SPECIFIC FORECAST…]] - rationale - tests/test_rain_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_152
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 139]]
- 3 edges to [[_COMMUNITY_Community 165]]
- 1 edge to [[_COMMUNITY_Community 237]]

## Top bridge nodes
- [[TestRainForecastBlendSignal]] - degree 14, connects to 2 communities
- [[dot-_mock_acis()]] - degree 10, connects to 1 community
- [[dot-test_boundary_exactly_16_day_horizon_does_fetch()]] - degree 5, connects to 1 community
- [[dot-test_boundary_just_over_16_days_skips_fetch()]] - degree 5, connects to 1 community
- [[dot-test_ensemble_fetch_none_fails_open()]] - degree 5, connects to 1 community