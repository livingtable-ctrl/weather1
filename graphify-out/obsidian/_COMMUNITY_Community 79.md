---
type: community
cohesion: 0.08
members: 32
---

# Community 79

**Cohesion:** 0.08 - loosely connected
**Members:** 32 nodes

## Members
- [[13 - get_market_calibration() must use equal-frequency buckets and accept…]] - rationale - tests/test_tracker.py
- [[dot-_seed()_4]] - code - tests/test_tracker.py
- [[dot-_seed()_5]] - code - tests/test_tracker.py
- [[dot-setUp()_40]] - code - tests/test_tracker.py
- [[dot-setUp()_41]] - code - tests/test_tracker.py
- [[dot-tearDown()_39]] - code - tests/test_tracker.py
- [[dot-tearDown()_40]] - code - tests/test_tracker.py
- [[dot-test_city_isolation()_1]] - code - tests/test_tracker.py
- [[dot-test_falls_back_to_global_when_quintile_empty()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calibration_bucket_fields()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calibration_buckets_equal_frequency()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calibration_default_n_buckets_is_10()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calibration_empty_returns_empty_buckets()]] - code - tests/test_tracker.py
- [[dot-test_grpb_calibration_n_buckets_param_accepted()]] - code - tests/test_tracker.py
- [[dot-test_quintile_boundary_0_maps_to_first_bucket()]] - code - tests/test_tracker.py
- [[dot-test_quintile_boundary_1_maps_to_last_bucket()]] - code - tests/test_tracker.py
- [[dot-test_quintile_specific_bias_returned()]] - code - tests/test_tracker.py
- [[dot-test_returns_zero_when_no_data_at_all()]] - code - tests/test_tracker.py
- [[Bias for a well-populated quintile differs from the global bias.]] - rationale - tests/test_tracker.py
- [[Buckets should be roughly equal in count (quantile, not equal-width).]] - rationale - tests/test_tracker.py
- [[Default call (no args) should use 10 buckets.]] - rationale - tests/test_tracker.py
- [[E1 per-quintile bias correction.]] - rationale - tests/test_tracker.py
- [[Each bucket must have the required keys.]] - rationale - tests/test_tracker.py
- [[Empty DB → both global and quintile bias return 0.0.]] - rationale - tests/test_tracker.py
- [[Insert n settled predictions at our_prob in quintile of our_prob.]] - rationale - tests/test_tracker.py
- [[Quintile bias for NYC does not bleed into CHI.]] - rationale - tests/test_tracker.py
- [[TestGetQuintileBias]] - code - tests/test_tracker.py
- [[TestMarketCalibrationQuantile]] - code - tests/test_tracker.py
- [[With no data in the target quintile, returns global bias.]] - rationale - tests/test_tracker.py
- [[forecast_prob=0.0 maps to quintile 0 (0.0–0.20).]] - rationale - tests/test_tracker.py
- [[forecast_prob=1.0 maps to quintile 4 (0.80–1.0).]] - rationale - tests/test_tracker.py
- [[n_buckets parameter should control number of output buckets.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_79
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 35]]

## Top bridge nodes
- [[TestGetQuintileBias]] - degree 11, connects to 1 community
- [[TestMarketCalibrationQuantile]] - degree 10, connects to 1 community