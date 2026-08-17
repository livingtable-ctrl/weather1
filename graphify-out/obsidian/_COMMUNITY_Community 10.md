---
type: community
cohesion: 0.03
members: 83
---

# Community 10

**Cohesion:** 0.03 - loosely connected
**Members:** 83 nodes

## Members
- [[dot-_add()]] - code - tests/test_tracker.py
- [[dot-_add_typed()]] - code - tests/test_tracker.py
- [[dot-setUp()]] - code - tests/test_tracker.py
- [[dot-tearDown()]] - code - tests/test_tracker.py
- [[dot-test_bias_no_condition_type_includes_all()]] - code - tests/test_tracker.py
- [[dot-test_bucket_fields()]] - code - tests/test_tracker.py
- [[dot-test_clustered_data_n_buckets_5()]] - code - tests/test_tracker.py
- [[dot-test_empty_condition_type_filter()]] - code - tests/test_tracker.py
- [[dot-test_empty_has_threshold()]] - code - tests/test_tracker.py
- [[dot-test_empty_returns_empty_buckets()]] - code - tests/test_tracker.py
- [[dot-test_get_sameday_calibration_still_includes_between()]] - code - tests/test_tracker.py
- [[dot-test_grpb_bias_condition_type_filters_rows()]] - code - tests/test_tracker.py
- [[dot-test_grpb_bias_unknown_condition_type_returns_zero()]] - code - tests/test_tracker.py
- [[dot-test_market_level_model_near_zero()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_bucket_grouping()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_empty()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_excludes_between()]] - code - tests/test_tracker.py
- [[dot-test_multiday_calibration_cli_excludes_sameday_rows()]] - code - tests/test_tracker.py
- [[dot-test_no_filter_returns_all()]] - code - tests/test_tracker.py
- [[dot-test_nyc_high_vs_precip_different_bias()]] - code - tests/test_tracker.py
- [[dot-test_perfect_model_positive_bss()]] - code - tests/test_tracker.py
- [[dot-test_returns_buckets_key()]] - code - tests/test_tracker.py
- [[dot-test_returns_dict_with_correct_keys()]] - code - tests/test_tracker.py
- [[dot-test_returns_dict_with_exactly_20_samples()]] - code - tests/test_tracker.py
- [[dot-test_returns_dict_with_settled_data()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_below_10_samples()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_below_10_samples()_1]] - code - tests/test_tracker.py
- [[dot-test_returns_none_with_10_samples()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_with_19_samples()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_with_no_data()]] - code - tests/test_tracker.py
- [[dot-test_sameday_calibration_cli_empty()]] - code - tests/test_tracker.py
- [[dot-test_sameday_calibration_cli_excludes_between()]] - code - tests/test_tracker.py
- [[dot-test_sameday_calibration_cli_excludes_multiday_rows()]] - code - tests/test_tracker.py
- [[dot-test_small_sample_has_wider_interval_than_large_sample()]] - code - tests/test_tracker.py
- [[dot-test_threshold_60_vs_80()]] - code - tests/test_tracker.py
- [[dot-test_threshold_in_return_dict()]] - code - tests/test_tracker.py
- [[dot-test_threshold_within_range()]] - code - tests/test_tracker.py
- [[10 samples (old guard) must now return None (guard raised to 20).]] - rationale - tests/test_tracker.py
- [[19 samples ( 20) must return None.]] - rationale - tests/test_tracker.py
- [[30 predictions clustered near 0.50, n_buckets=5 → = 5 buckets returned.]] - rationale - tests/test_tracker.py
- [[A days_out=0 row must not appear in the multiday population.]] - rationale - tests/test_tracker.py
- [[A days_out=1 row must not appear in the sameday population.]] - rationale - tests/test_tracker.py
- [[BSS returns None with  10 samples.]] - rationale - tests/test_tracker.py
- [[Dashboard-facing get_sameday_calibration() must NOT change behavior — it still…]] - rationale - tests/test_tracker.py
- [[Each bucket should have required fields.]] - rationale - tests/test_tracker.py
- [[Empty DB still returns threshold in dict.]] - rationale - tests/test_tracker.py
- [[Exactly 20 samples must return a result dict.]] - rationale - tests/test_tracker.py
- [[Filtering by HIGH vs PRECIP gives different bias values.]] - rationale - tests/test_tracker.py
- [[Filtering by a condition_type with no matching rows returns 0.0.]] - rationale - tests/test_tracker.py
- [[Filtering by non-existent condition_type returns empty dict.]] - rationale - tests/test_tracker.py
- [[Helper log prediction + outcome.]] - rationale - tests/test_tracker.py
- [[Model matching market_prob exactly gives BSS ≈ 0.]] - rationale - tests/test_tracker.py
- [[NYC HIGH vs NYC PRECIP should have different bias.]] - rationale - tests/test_tracker.py
- [[Optimal threshold should be between 0.05 and 0.95.]] - rationale - tests/test_tracker.py
- [[Perfect model (our_prob=1.0, settled YES) gives BSS  0.]] - rationale - tests/test_tracker.py
- [[Regression for the 69-row scenario found in production data 'between' sameday…]] - rationale - tests/test_tracker.py
- [[Return dict must include 'threshold' key.]] - rationale - tests/test_tracker.py
- [[Returns dict with threshold_f1 and best_f1.]] - rationale - tests/test_tracker.py
- [[Rows land in the correct 0.2-wide probability buckets.]] - rationale - tests/test_tracker.py
- [[Shared setUptearDown for Phase 3 test classes.]] - rationale - tests/test_tracker.py
- [[TestBrierSkillScore]] - code - tests/test_tracker.py
- [[TestCalibrationByCityConditionType]] - code - tests/test_tracker.py
- [[TestCliCalibrationSplit]] - code - tests/test_tracker.py
- [[TestConfusionMatrixThreshold]] - code - tests/test_tracker.py
- [[TestGetBiasConditionType]] - code - tests/test_tracker.py
- [[TestGetOptimalThreshold]] - code - tests/test_tracker.py
- [[TestGetRollingWinRateCI]] - code - tests/test_tracker.py
- [[TestMarketCalibrationAdaptive]] - code - tests/test_tracker.py
- [[TestOptimalThresholdGuard20]] - code - tests/test_tracker.py
- [[Tests for brier_skill_score() (11).]] - rationale - tests/test_tracker.py
- [[Tests for get_bias() stratified by condition_type (10).]] - rationale - tests/test_tracker.py
- [[Tests for get_calibration_by_city() with condition_type (54, 56).]] - rationale - tests/test_tracker.py
- [[Tests for get_confusion_matrix() with configurable threshold (12).]] - rationale - tests/test_tracker.py
- [[Tests for get_market_calibration() quantile-based bucketing (13).]] - rationale - tests/test_tracker.py
- [[Tests for get_multiday_calibration_cli()  get_sameday_calibration_cli() and a…]] - rationale - tests/test_tracker.py
- [[Tests for get_optimal_threshold() (60).]] - rationale - tests/test_tracker.py
- [[Verify get_optimal_threshold returns None below 20 data points (60).]] - rationale - tests/test_tracker.py
- [[Without condition_type filter, bias uses all rows.]] - rationale - tests/test_tracker.py
- [[Without condition_type, all predictions are included.]] - rationale - tests/test_tracker.py
- [[_Phase3Base]] - code - tests/test_tracker.py
- [[condition_type='between' rows must not affect nbrier.]] - rationale - tests/test_tracker.py
- [[get_rolling_win_rate_ci() pairs get_rolling_win_rate's real (win_rate, count)…]] - rationale - tests/test_tracker.py
- [[prob=0.7, settled YES threshold=0.6 → TP; threshold=0.8 → FN.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_10
SORT file.name ASC
```

## Connections to other communities
- 10 edges to [[_COMMUNITY_Community 35]]
- 2 edges to [[_COMMUNITY_Community 320]]
- 1 edge to [[_COMMUNITY_Community 260]]

## Top bridge nodes
- [[_Phase3Base]] - degree 16, connects to 3 communities
- [[dot-_add()]] - degree 27, connects to 1 community
- [[TestCliCalibrationSplit]] - degree 11, connects to 1 community
- [[TestGetBiasConditionType]] - degree 7, connects to 1 community
- [[TestMarketCalibrationAdaptive]] - degree 7, connects to 1 community