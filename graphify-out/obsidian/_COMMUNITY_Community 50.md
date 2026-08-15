---
type: community
cohesion: 0.06
members: 40
---

# Community 50

**Cohesion:** 0.06 - loosely connected
**Members:** 40 nodes

## Members
- [[dot-test_save_retired_strategies_propagates_atomic_write_failure()]] - code - tests/test_p9_p10.py
- [[dot-test_save_strategy_pins_propagates_atomic_write_failure()]] - code - tests/test_p9_p10.py
- [[A LOW-market ticker from a correlated city must not leak into a var='max'…]] - rationale - tests/test_p9_p10.py
- [[A correlated city's settlement outside the lookback window is excluded.]] - rationale - tests/test_p9_p10.py
- [[A disputed correlated-city settlement must not pollute the pooled bias (same…]] - rationale - tests/test_p9_p10.py
- [[A disputed settlement must not pollute the correlation computation (backlog.txt…]] - rationale - tests/test_p9_p10.py
- [[A ticker re-logged across multiple cron cycles (one predictions row per day…]] - rationale - tests/test_p9_p10.py
- [[Boston (corr 0.85) and Washington (corr 0.75) both ran 2F warm on NYC's HIGH…]] - rationale - tests/test_p9_p10.py
- [[Boston (corr 0.85, error +4F) and Philadelphia (corr 0.80, error -2F) disagree…]] - rationale - tests/test_p9_p10.py
- [[Helper log a prediction with forecast_temp_f + a matching settled outcome,…]] - rationale - tests/test_p9_p10.py
- [[NYC has a correlated group but the DB is empty — (0.0, 0).]] - rationale - tests/test_p9_p10.py
- [[Regression coverage for the OTHER bare os.replace() CALL SITES backlog entry…_1]] - rationale - tests/test_p9_p10.py
- [[Seattle has no _CORRELATED_CITY_GROUPS entry (deliberately standalone) — must…]] - rationale - tests/test_p9_p10.py
- [[TestPersistenceRoutesThroughSafeIO]] - code - tests/test_p9_p10.py
- [[Tests for P9P10 features - P9.1 Strategy versioning (get_brier_by_version,…]] - rationale - tests/test_p9_p10.py
- [[_log_settled()]] - code - tests/test_p9_p10.py
- [[as_of lets a caller ask 'what would this have returned at time T' without a…]] - rationale - tests/test_p9_p10.py
- [[get_recent_city_correlations returns city-pair correlations when enough data…]] - rationale - tests/test_p9_p10.py
- [[get_recent_city_correlations returns {} when DB has no settled multiday trades.]] - rationale - tests/test_p9_p10.py
- [[get_recent_city_correlations skips pairs with fewer than min_pairs common dates.]] - rationale - tests/test_p9_p10.py
- [[heat_wave_failure scenario only counts DallasHoustonPhoenixAtlantaAustin…]] - rationale - tests/test_p9_p10.py
- [[run_stress_test returns an error dict for unknown scenario names.]] - rationale - tests/test_p9_p10.py
- [[test_get_recent_city_correlations_computes_correlation()]] - code - tests/test_p9_p10.py
- [[test_get_recent_city_correlations_excludes_disputed()]] - code - tests/test_p9_p10.py
- [[test_get_recent_city_correlations_returns_empty_when_no_data()]] - code - tests/test_p9_p10.py
- [[test_get_recent_city_correlations_skips_below_min_pairs()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_as_of_avoids_lookahead()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_computes_weighted_mean()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_dedups_to_latest_prediction_per_ticker()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_excludes_disputed()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_no_correlated_group()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_no_data()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_respects_hours_window()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_var_filters_high_low()]] - code - tests/test_p9_p10.py
- [[test_get_regional_recent_bias_weights_by_pair_correlation()]] - code - tests/test_p9_p10.py
- [[test_p9_p10.py]] - code - tests/test_p9_p10.py
- [[test_run_stress_test_heat_wave_filters_southern_cities()]] - code - tests/test_p9_p10.py
- [[test_run_stress_test_total_model_failure_includes_all_cities()]] - code - tests/test_p9_p10.py
- [[test_run_stress_test_unknown_scenario_returns_error()]] - code - tests/test_p9_p10.py
- [[total_model_failure scenario counts all open positions regardless of city.]] - rationale - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_50
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 3 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 2 edges to [[_COMMUNITY_Community 167]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 40]]
- 2 edges to [[_COMMUNITY_Community 101]]
- 2 edges to [[_COMMUNITY_Community 164]]
- 2 edges to [[_COMMUNITY_Community 342]]
- 2 edges to [[_COMMUNITY_Community 384]]
- 1 edge to [[_COMMUNITY_Community 369]]
- 1 edge to [[_COMMUNITY_Community 431]]
- 1 edge to [[_COMMUNITY_Community 476]]
- 1 edge to [[_COMMUNITY_Community 279]]
- 1 edge to [[_COMMUNITY_Community 576]]
- 1 edge to [[_COMMUNITY_Community 430]]
- 1 edge to [[_COMMUNITY_Community 475]]

## Top bridge nodes
- [[test_p9_p10.py]] - degree 46, connects to 16 communities