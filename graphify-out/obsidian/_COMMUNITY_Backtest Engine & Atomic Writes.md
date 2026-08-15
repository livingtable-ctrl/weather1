---
type: community
cohesion: 0.04
members: 71
---

# Backtest Engine & Atomic Writes

**Cohesion:** 0.04 - loosely connected
**Members:** 71 nodes

## Members
- [[dot-_market()_6]] - code - tests/test_weather.py
- [[dot-test_above_temp()]] - code - tests/test_weather.py
- [[dot-test_all_models_present_in_tracker_map_values()]] - code - tests/test_backtest.py
- [[dot-test_api_error_prints_message_not_traceback()]] - code - tests/test_backtest.py
- [[dot-test_below_temp()]] - code - tests/test_weather.py
- [[dot-test_bucket()]] - code - tests/test_weather.py
- [[dot-test_derived_from_known_weather_series_not_a_second_copy()]] - code - tests/test_backtest.py
- [[dot-test_precip_any()]] - code - tests/test_weather.py
- [[dot-test_returns_empty_for_unknown_city()]] - code - tests/test_backtest.py
- [[dot-test_returns_empty_on_api_error()]] - code - tests/test_backtest.py
- [[dot-test_returns_list_of_floats()]] - code - tests/test_backtest.py
- [[dot-test_run_backtest_accepts_use_previous_runs_flag()]] - code - tests/test_backtest.py
- [[dot-test_stale_known_weather_series_raises_at_import()]] - code - tests/test_backtest.py
- [[dot-test_t_bucket_tiles_with_adjacent_between_bucket()]] - code - tests/test_weather.py
- [[dot-test_unrecognised_returns_none()]] - code - tests/test_weather.py
- [[dot-test_zero_in_bracket_probability_is_clamped_not_zero()]] - code - tests/test_backtest.py
- [[A narrow 'between' bracket scored against a small discrete archive sample very…]] - rationale - tests/test_backtest.py
- [[API errors must return empty list, never raise.]] - rationale - tests/test_backtest.py
- [[Aliasing to KNOWN_WEATHER_SERIES only fixed the one already-known LA incident…]] - rationale - tests/test_backtest.py
- [[Atomic JSON write with retry and fallback location.]] - rationale - safe_io.py
- [[Backtesting engine — replays historical Kalshi weather markets using Open-Meteo…]] - rationale - backtest.py
- [[CITY_COORDS]] - code - weather_markets.py
- [[Estimate precipitation probability for target_date using the prior window_days…]] - rationale - backtest.py
- [[Every _ALLOWLIST entry must name a real file, a positive expected count, and a…]] - rationale - tests/test_bare_os_replace_guard.py
- [[Fetch actual model output at forecast time using the Previous Runs API. Returns…]] - rationale - backtest.py
- [[Fetch finalized weather markets from Kalshi, then simulate our model's…]] - rationale - backtest.py
- [[Fetch historical daily highlow temperatures from Open-Meteo archive. Returns a…]] - rationale - backtest.py
- [[Fetch settled Kalshi weather markets by iterating known weather series.…]] - rationale - backtest.py
- [[KNOWN_WEATHER_SERIES]] - code - weather_markets.py
- [[No .py file outside safe_io.py should call os.replace()_os.replace() directly…]] - rationale - tests/test_bare_os_replace_guard.py
- [[Parse what outcome a market is asking about from its ticker and title. Returns…]] - rationale - weather_markets.py
- [[Path_15]] - code
- [[Phase 4 Forecasting Plan]] - document - docs/plans/2026-04-10-phase4-forecasting.md
- [[Previous Runs API call must return a list of floats.]] - rationale - tests/test_backtest.py
- [[TEMPERATURE_MARKET_CITIES]] - code - weather_markets.py
- [[TestBetweenMarketProbabilityClamp]] - code - tests/test_backtest.py
- [[TestCmdBacktestErrorHandling]] - code - tests/test_backtest.py
- [[TestFetchPreviousRunEnsemble]] - code - tests/test_backtest.py
- [[TestParseMarketCondition]] - code - tests/test_weather.py
- [[TestPrevRunModelsMatchTracker]] - code - tests/test_backtest.py
- [[TestWeatherSeriesDerivation]] - code - tests/test_backtest.py
- [[Tests for backtest ensemble and archive temperature helpers.]] - rationale - tests/test_backtest_stratified.py
- [[Tests for cmd_simulate status parameter.]] - rationale - tests/test_backtest.py
- [[Unknown city must return empty list (no crash).]] - rationale - tests/test_backtest.py
- [[Walk-forward validation slide a fixed-size window across the history, scoring…]] - rationale - backtest.py
- [[When backtest finds no scoreable markets, cmd_backtest prints a funnel…]] - rationale - tests/test_backtest.py
- [[_WEATHER_SERIES must be weather_markets.KNOWN_WEATHER_SERIES itself, not an…]] - rationale - tests/test_backtest.py
- [[_all_source_files()]] - code - tests/test_bare_os_replace_guard.py
- [[_fetch_settled_markets()]] - code - backtest.py
- [[_parse_market_condition()]] - code - weather_markets.py
- [[atomic_write_json()_1]] - code - safe_io.py
- [[backtest._PREV_RUN_MODELS and tracker._PREVIOUS_RUN_MODEL_MAP both hardcode…]] - rationale - tests/test_backtest.py
- [[backtest.py]] - code - backtest.py
- [[backtest.py_1]] - code - backtest.py
- [[cmd_backtest must catch API errors and print a readable message.]] - rationale - tests/test_backtest.py
- [[date]] - code
- [[fetch_archive_precip_prob()]] - code - backtest.py
- [[fetch_archive_temps()]] - code - backtest.py
- [[fetch_previous_run_ensemble()]] - code - backtest.py
- [[rAutomated guard against the bare-os.replace() anti-pattern reappearing…]] - rationale - tests/test_bare_os_replace_guard.py
- [[run_backtest()]] - code - backtest.py
- [[run_backtest() must accept use_previous_runs keyword without raising TypeError.]] - rationale - tests/test_backtest.py
- [[run_walk_forward()]] - code - backtest.py
- [[safe_io.py]] - code - safe_io.py
- [[stratified_train_test_split()]] - code - backtest.py
- [[test_allowlist_entries_still_exist_and_are_justified()]] - code - tests/test_bare_os_replace_guard.py
- [[test_backtest.py]] - code - tests/test_backtest.py
- [[test_backtest_reports_funnel_breakdown_when_empty()]] - code - tests/test_backtest.py
- [[test_backtest_stratified.py]] - code - tests/test_backtest_stratified.py
- [[test_bare_os_replace_guard.py]] - code - tests/test_bare_os_replace_guard.py
- [[test_no_new_bare_os_replace_sites()]] - code - tests/test_bare_os_replace_guard.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Backtest_Engine__Atomic_Writes
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 8 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 7 edges to [[_COMMUNITY_Black Swan Halt State]]
- 7 edges to [[_COMMUNITY_Community 47]]
- 6 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 5 edges to [[_COMMUNITY_Community 37]]
- 5 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 5 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 4 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 4 edges to [[_COMMUNITY_Community 59]]
- 4 edges to [[_COMMUNITY_Community 36]]
- 2 edges to [[_COMMUNITY_Community 62]]
- 2 edges to [[_COMMUNITY_Community 245]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Kelly Sizing Property-Based Tests]]
- 2 edges to [[_COMMUNITY_Community 420]]
- 2 edges to [[_COMMUNITY_Community 57]]
- 2 edges to [[_COMMUNITY_Community 109]]
- 2 edges to [[_COMMUNITY_Community 103]]
- 2 edges to [[_COMMUNITY_Community 89]]
- 1 edge to [[_COMMUNITY_Community 94]]
- 1 edge to [[_COMMUNITY_Community 118]]
- 1 edge to [[_COMMUNITY_Community 182]]
- 1 edge to [[_COMMUNITY_Community 55]]
- 1 edge to [[_COMMUNITY_Community 181]]
- 1 edge to [[_COMMUNITY_Community 96]]
- 1 edge to [[_COMMUNITY_Community 145]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Community 540]]
- 1 edge to [[_COMMUNITY_Community 358]]
- 1 edge to [[_COMMUNITY_Community 391]]
- 1 edge to [[_COMMUNITY_Community 541]]
- 1 edge to [[_COMMUNITY_Community 293]]
- 1 edge to [[_COMMUNITY_Community 243]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]

## Top bridge nodes
- [[safe_io.py]] - degree 32, connects to 17 communities
- [[backtest.py]] - degree 30, connects to 10 communities
- [[run_backtest()]] - degree 23, connects to 8 communities
- [[test_backtest.py]] - degree 21, connects to 8 communities
- [[test_bare_os_replace_guard.py]] - degree 12, connects to 6 communities