---
type: community
cohesion: 0.03
members: 105
---

# Community 8

**Cohesion:** 0.03 - loosely connected
**Members:** 105 nodes

## Members
- [[dot-test_all_models_present_in_tracker_map_values()]] - code - tests/test_backtest.py
- [[dot-test_api_error_prints_message_not_traceback()]] - code - tests/test_backtest.py
- [[dot-test_read_settlement_signals_empty_on_no_file()]] - code - tests/test_settlement_monitor.py
- [[dot-test_returns_empty_for_unknown_city()]] - code - tests/test_backtest.py
- [[dot-test_returns_empty_on_api_error()]] - code - tests/test_backtest.py
- [[dot-test_returns_list_of_floats()]] - code - tests/test_backtest.py
- [[dot-test_run_backtest_accepts_use_previous_runs_flag()]] - code - tests/test_backtest.py
- [[dot-test_signal_structure()]] - code - tests/test_settlement_monitor.py
- [[dot-test_signals_expire_after_window()]] - code - tests/test_settlement_monitor.py
- [[dot-test_write_settlement_signals_creates_file()]] - code - tests/test_settlement_monitor.py
- [[dot-test_zero_in_bracket_probability_is_clamped_not_zero()]] - code - tests/test_backtest.py
- [[A narrow 'between' bracket scored against a small discrete archive sample very…]] - rationale - tests/test_backtest.py
- [[API errors must return empty list, never raise.]] - rationale - tests/test_backtest.py
- [[Atomic JSON write with retry and fallback location.]] - rationale - safe_io.py
- [[Atomic Write Pattern (os.replace)]] - document - docs/grade_audit/modules/safe_io.md
- [[AtomicWriteError]] - code - safe_io.py
- [[Build a settlement lag signal dict.]] - rationale - settlement_monitor.py
- [[Build a settlement lag signal dict._1]] - rationale - settlement_monitor.py
- [[CITY_COORDS]] - code - weather_markets.py
- [[Check send_system_alert()'s persisted cooldown for `cooldown_key` and, if…]] - rationale - notify.py
- [[Daily Loss Check Dead Letter (int timestamp bug)]] - document - docs/grade_audit/outputs/alerts.py.md
- [[Does not expose emergency_copy -- this function exists specifically to preserve…]] - rationale - safe_io.py
- [[Estimate precipitation probability for target_date using the prior window_days…]] - rationale - backtest.py
- [[Every _ALLOWLIST entry must name a real file, a positive expected count, and a…_1]] - rationale - tests/test_bare_os_replace_guard.py
- [[Exception_1]] - code
- [[Fetch actual model output at forecast time using the Previous Runs API. Returns…]] - rationale - backtest.py
- [[Fetch finalized weather markets from Kalshi, then simulate our model's…]] - rationale - backtest.py
- [[Fetch historical daily highlow temperatures from Open-Meteo archive. Returns a…]] - rationale - backtest.py
- [[Grade Audit Module Doc cron.py]] - document - docs/grade_audit/modules/cron.md
- [[Grade Audit Module Doc safe_io.py]] - document - docs/grade_audit/modules/safe_io.md
- [[Grade Audit Output alerts.py]] - document - docs/grade_audit/outputs/alerts.py.md
- [[Implicit brier_score min_days_out Default Gap]] - document - docs/grade_audit/outputs/alerts.py.md
- [[KNOWN_WEATHER_SERIES_1]] - code - weather_markets.py
- [[METAR Settlement Lag Monitor — Phase D Settlement & Monitoring. Runs from 5 PM…]] - rationale - settlement_monitor.py
- [[No .py file outside safe_io.py should call os.replace()_os.replace() directly…]] - rationale - tests/test_bare_os_replace_guard.py
- [[Path_27]] - code
- [[Path_28]] - code
- [[Path_29]] - code
- [[Per-Order Kill Switch Check]] - document - docs/grade_audit/modules/cron.md
- [[Previous Runs API call must return a list of floats.]] - rationale - tests/test_backtest.py
- [[Price alerts — notify when a market's YES price crosses a user-set threshold.…]] - rationale - alerts.py
- [[Read active settlement signals, filtering out expired ones. Args…]] - rationale - settlement_monitor.py
- [[Read active settlement signals, filtering out expired ones. Args…_1]] - rationale - settlement_monitor.py
- [[Return info about any real recovery copies sitting in the emergency- copy…]] - rationale - safe_io.py
- [[Return the main project root directory, resolving git worktrees correctly. When…]] - rationale - safe_io.py
- [[Run the settlement lag monitoring loop. Polls METAR every…]] - rationale - settlement_monitor.py
- [[Run the settlement lag monitoring loop. Polls METAR every…_1]] - rationale - settlement_monitor.py
- [[Shared write-tempfsyncrenameretryemergency-copy core for atomic_write_json…]] - rationale - safe_io.py
- [[Signals older than max_age_minutes are filtered out.]] - rationale - tests/test_settlement_monitor.py
- [[TEMPERATURE_MARKET_CITIES]] - code - weather_markets.py
- [[TestBetweenMarketProbabilityClamp]] - code - tests/test_backtest.py
- [[TestBuildSettlementSignal]] - code - tests/test_settlement_monitor.py
- [[TestCmdBacktestErrorHandling]] - code - tests/test_backtest.py
- [[TestFetchPreviousRunEnsemble]] - code - tests/test_backtest.py
- [[TestPrevRunModelsMatchTracker]] - code - tests/test_backtest.py
- [[Tests for backtest ensemble and archive temperature helpers.]] - rationale - tests/test_backtest_stratified.py
- [[Tests for cmd_simulate status parameter.]] - rationale - tests/test_backtest.py
- [[Unknown city must return empty list (no crash).]] - rationale - tests/test_backtest.py
- [[When backtest finds no scoreable markets, cmd_backtest prints a funnel…]] - rationale - tests/test_backtest.py
- [[Write alerts list to path using safe_io for resilient disk writes (8). P3-9…]] - rationale - alerts.py
- [[Write data to path atomically (write temp → fsync → rename). Retries up to…]] - rationale - safe_io.py
- [[Write raw text to path atomically -- same write-tempfsyncrename, retry, and…]] - rationale - safe_io.py
- [[Write signals list to the signals file (atomic write).]] - rationale - settlement_monitor.py
- [[Write signals list to the signals file (atomic write)._1]] - rationale - settlement_monitor.py
- [[_all_source_files()_1]] - code - tests/test_bare_os_replace_guard.py
- [[_atomic_write_payload()]] - code - safe_io.py
- [[_replace_with_retry()]] - code - safe_io.py
- [[_system_cooldown_elapsed()]] - code - notify.py
- [[alerts.py]] - code - alerts.py
- [[atomic_write_json()]] - code - safe_io.py
- [[atomic_write_json_with_history()]] - code - safe_io.py
- [[atomic_write_text()]] - code - safe_io.py
- [[backtest._PREV_RUN_MODELS and tracker._PREVIOUS_RUN_MODEL_MAP both hardcode…]] - rationale - tests/test_backtest.py
- [[build_settlement_signal returns dict with required keys.]] - rationale - tests/test_settlement_monitor.py
- [[build_settlement_signal()]] - code - settlement_monitor.py
- [[check_alerts() RF1 Silent Exception Swallow]] - document - docs/grade_audit/outputs/alerts.py.md
- [[check_emergency_copies()]] - code - safe_io.py
- [[cmd_backtest must catch API errors and print a readable message.]] - rationale - tests/test_backtest.py
- [[date_11]] - code
- [[fetch_archive_precip_prob()]] - code - backtest.py
- [[fetch_archive_temps()]] - code - backtest.py
- [[fetch_previous_run_ensemble()]] - code - backtest.py
- [[hurricane_climatology.py HURDAT2 text cache]] - code - hurricane_climatology.py
- [[os.replace(src, dst), retrying briefly on PermissionError. Self-caught…]] - rationale - safe_io.py
- [[paper._acquire_file_lock()  msvcrt retry loop]] - code - paper.py
- [[project_root()]] - code - safe_io.py
- [[rAutomated guard against the bare-os.replace() anti-pattern reappearing…]] - rationale - tests/test_bare_os_replace_guard.py
- [[read_settlement_signals returns  when file does not exist.]] - rationale - tests/test_settlement_monitor.py
- [[read_settlement_signals()]] - code - settlement_monitor.py
- [[run_backtest()]] - code - backtest.py
- [[run_backtest() must accept use_previous_runs keyword without raising TypeError.]] - rationale - tests/test_backtest.py
- [[run_settlement_monitor()]] - code - settlement_monitor.py
- [[safe_io.py_1]] - code - safe_io.py
- [[safe_io.py]] - code - safe_io.py
- [[save_alerts()]] - code - alerts.py
- [[settlement_monitor.py]] - code - settlement_monitor.py
- [[test_allowlist_entries_still_exist_and_are_justified()_1]] - code - tests/test_bare_os_replace_guard.py
- [[test_atomic_write_json_with_history_keeps_previous_versions()]] - code - tests/test_cleanup_data_dir.py
- [[test_backtest.py]] - code - tests/test_backtest.py
- [[test_backtest_reports_funnel_breakdown_when_empty()]] - code - tests/test_backtest.py
- [[test_backtest_stratified.py]] - code - tests/test_backtest_stratified.py
- [[test_bare_os_replace_guard.py]] - code - tests/test_bare_os_replace_guard.py
- [[test_no_new_bare_os_replace_sites()]] - code - tests/test_bare_os_replace_guard.py
- [[write_settlement_signals writes JSON to signals file.]] - rationale - tests/test_settlement_monitor.py
- [[write_settlement_signals()]] - code - settlement_monitor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_8
SORT file.name ASC
```

## Connections to other communities
- 29 edges to [[_COMMUNITY_Community 4]]
- 27 edges to [[_COMMUNITY_Community 6]]
- 17 edges to [[_COMMUNITY_Community 3]]
- 10 edges to [[_COMMUNITY_Community 5]]
- 9 edges to [[_COMMUNITY_Community 32]]
- 8 edges to [[_COMMUNITY_Community 0]]
- 7 edges to [[_COMMUNITY_Community 1]]
- 7 edges to [[_COMMUNITY_Community 7]]
- 7 edges to [[_COMMUNITY_Community 23]]
- 6 edges to [[_COMMUNITY_Community 51]]
- 5 edges to [[_COMMUNITY_Community 102]]
- 5 edges to [[_COMMUNITY_Community 2]]
- 4 edges to [[_COMMUNITY_Community 85]]
- 4 edges to [[_COMMUNITY_Community 108]]
- 3 edges to [[_COMMUNITY_Community 142]]
- 3 edges to [[_COMMUNITY_Community 55]]
- 3 edges to [[_COMMUNITY_Community 53]]
- 2 edges to [[_COMMUNITY_Community 457]]
- 2 edges to [[_COMMUNITY_Community 13]]
- 2 edges to [[_COMMUNITY_Community 148]]
- 2 edges to [[_COMMUNITY_Community 269]]
- 2 edges to [[_COMMUNITY_Community 359]]
- 2 edges to [[_COMMUNITY_Community 43]]
- 2 edges to [[_COMMUNITY_Community 64]]
- 2 edges to [[_COMMUNITY_Community 89]]
- 2 edges to [[_COMMUNITY_Community 82]]
- 2 edges to [[_COMMUNITY_Community 81]]
- 2 edges to [[_COMMUNITY_Community 41]]
- 2 edges to [[_COMMUNITY_Community 31]]
- 2 edges to [[_COMMUNITY_Community 176]]
- 1 edge to [[_COMMUNITY_Community 336]]
- 1 edge to [[_COMMUNITY_Community 368]]
- 1 edge to [[_COMMUNITY_Community 371]]
- 1 edge to [[_COMMUNITY_Community 411]]
- 1 edge to [[_COMMUNITY_Community 604]]
- 1 edge to [[_COMMUNITY_Community 605]]
- 1 edge to [[_COMMUNITY_Community 606]]
- 1 edge to [[_COMMUNITY_Community 126]]
- 1 edge to [[_COMMUNITY_Community 14]]
- 1 edge to [[_COMMUNITY_Community 170]]
- 1 edge to [[_COMMUNITY_Community 227]]
- 1 edge to [[_COMMUNITY_Community 329]]
- 1 edge to [[_COMMUNITY_Community 361]]
- 1 edge to [[_COMMUNITY_Community 389]]
- 1 edge to [[_COMMUNITY_Community 398]]
- 1 edge to [[_COMMUNITY_Community 54]]
- 1 edge to [[_COMMUNITY_Community 88]]
- 1 edge to [[_COMMUNITY_Community 251]]
- 1 edge to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Community 71]]

## Top bridge nodes
- [[atomic_write_json()]] - degree 55, connects to 18 communities
- [[alerts.py]] - degree 42, connects to 13 communities
- [[safe_io.py]] - degree 38, connects to 11 communities
- [[run_backtest()]] - degree 23, connects to 10 communities
- [[settlement_monitor.py]] - degree 24, connects to 9 communities