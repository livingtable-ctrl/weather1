---
type: community
cohesion: 0.09
members: 29
---

# Community 96

**Cohesion:** 0.09 - loosely connected
**Members:** 29 nodes

## Members
- [[dot-_seed()_6]] - code - tests/test_ml_bias.py
- [[dot-_seed()_7]] - code - tests/test_ml_bias.py
- [[dot-_seed()_8]] - code - tests/test_ml_bias.py
- [[dot-test_directional_bias_warning_labels_global_and_condition()]] - code - tests/test_ml_bias.py
- [[dot-test_directional_bias_warning_labels_sameday_and_hourly()]] - code - tests/test_ml_bias.py
- [[dot-test_hourly_pool_below_min_samples_not_trained()]] - code - tests/test_ml_bias.py
- [[dot-test_hourly_rows_excluded_from_sameday_pool()]] - code - tests/test_ml_bias.py
- [[dot-test_hurricane_rows_excluded_from_global_pool()]] - code - tests/test_ml_bias.py
- [[dot-test_rain_rows_excluded_from_global_pool()]] - code - tests/test_ml_bias.py
- [[dot-test_sameday_fit_excludes_metar_lockout_rows()]] - code - tests/test_ml_bias.py
- [[dot-test_skips_emos_covered_keys_while_emos_is_active()]] - code - tests/test_ml_bias.py
- [[dot-test_snow_rows_excluded_from_global_pool()]] - code - tests/test_ml_bias.py
- [[dot-test_snow_rows_excluded_from_sameday_pool()]] - code - tests/test_ml_bias.py
- [[dot-test_sql_paren_regression_multiday_hourly_row_excluded_from_sameday()]] - code - tests/test_ml_bias.py
- [[24 rows all predicting 0.4 while the actual settle rate is 0.75 -- unfixable by…]] - rationale - tests/test_ml_bias.py
- [[Opus-review-caught (2026-08-07) this exclusion list was never extended for…]] - rationale - tests/test_ml_bias.py
- [[Opus-review-caught gap the global pool's exclusion above (line ~604 in…]] - rationale - tests/test_ml_bias.py
- [[Regression test _fit_T's callers used to log a generic T fit no better than…]] - rationale - tests/test_ml_bias.py
- [[Same directional-bias shape as above, seeded into the sameday and hourly pools…]] - rationale - tests/test_ml_bias.py
- [[Targets the exact SQL operator-precedence risk directly SQL's AND binds…]] - rationale - tests/test_ml_bias.py
- [[TestTrainAllTemperatureScalingHourlyPool]] - code - tests/test_ml_bias.py
- [[TestTrainAllTemperatureScalingRainExclusion]] - code - tests/test_ml_bias.py
- [[TestTrainAllTemperatureScalingSkipLogging]] - code - tests/test_ml_bias.py
- [[While EMOS is live, globalabovebelowbetween must not be refit -- overwriting…]] - rationale - tests/test_ml_bias.py
- [[_KXTEMP_HOURLY_CITY]] - code - weather_markets.py
- [[backlog.txt HOURLY-DIRECTIONAL TEMPERATURE MARKETS Step 2 handoff item 4…]] - rationale - tests/test_ml_bias.py
- [[backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2 handoff item (ml_bias.py…]] - rationale - tests/test_ml_bias.py
- [[backlog.txt Snow Step 2 the identical leak-prevention check, mirrored for…]] - rationale - tests/test_ml_bias.py
- [[train_all_temperature_scaling's sameday T fit must not train on…]] - rationale - tests/test_ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_96
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 99]]
- 3 edges to [[_COMMUNITY_Community 3]]
- 3 edges to [[_COMMUNITY_Community 226]]
- 2 edges to [[_COMMUNITY_Community 101]]
- 1 edge to [[_COMMUNITY_Community 2]]
- 1 edge to [[_COMMUNITY_Community 23]]

## Top bridge nodes
- [[TestTrainAllTemperatureScalingRainExclusion]] - degree 10, connects to 4 communities
- [[TestTrainAllTemperatureScalingHourlyPool]] - degree 10, connects to 3 communities
- [[dot-_seed()_8]] - degree 13, connects to 1 community
- [[TestTrainAllTemperatureScalingSkipLogging]] - degree 7, connects to 1 community
- [[dot-test_snow_rows_excluded_from_sameday_pool()]] - degree 4, connects to 1 community