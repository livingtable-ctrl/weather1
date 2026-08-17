---
type: community
cohesion: 0.14
members: 14
---

# Community 259

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_bare_ticker_dict_hits_no_city_not_the_old_guard()_1]] - code - tests/test_snow_markets.py
- [[dot-test_daily_high_ticker_unaffected()_1]] - code - tests/test_snow_markets.py
- [[dot-test_days_out_at_snow_max_boundary_passes_days_out_gate()]] - code - tests/test_snow_markets.py
- [[dot-test_days_out_beyond_snow_max_gates_out()]] - code - tests/test_snow_markets.py
- [[dot-test_no_forecast_no_date_past_date_gates_never_fire_for_snow()]] - code - tests/test_snow_markets.py
- [[dot-test_past_close_time_gates_out()_1]] - code - tests/test_snow_markets.py
- [[dot-test_rain_ticker_unaffected()]] - code - tests/test_snow_markets.py
- [[Confirms the Step 1 guard is actually gone, not just renamed -- a bare…]] - rationale - tests/test_snow_markets.py
- [[Off-by-one check exactly SNOW_MAX_DAYS_OUT days out must NOT hit the days_out…]] - rationale - tests/test_snow_markets.py
- [[Regression control an ordinary daily HIGH ticker with no forecast data must…_1]] - rationale - tests/test_snow_markets.py
- [[Regression control the new snow gating must not collide with the existing…]] - rationale - tests/test_snow_markets.py
- [[Snow Step 2 Step 1's unconditional return-None guard is gone. Snow tickers now…]] - rationale - tests/test_snow_markets.py
- [[TestAnalyzeTradeMonthlySnowGating]] - code - tests/test_snow_markets.py
- [[The daily-specific gates this ticker family is exempted from must genuinely…_1]] - rationale - tests/test_snow_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_259
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 317]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestAnalyzeTradeMonthlySnowGating]] - degree 9, connects to 1 community
- [[dot-test_days_out_at_snow_max_boundary_passes_days_out_gate()]] - degree 3, connects to 1 community
- [[dot-test_no_forecast_no_date_past_date_gates_never_fire_for_snow()]] - degree 3, connects to 1 community
- [[dot-test_days_out_beyond_snow_max_gates_out()]] - degree 2, connects to 1 community
- [[dot-test_past_close_time_gates_out()_1]] - degree 2, connects to 1 community