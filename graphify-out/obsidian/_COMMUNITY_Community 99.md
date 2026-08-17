---
type: community
cohesion: 0.08
members: 28
---

# Community 99

**Cohesion:** 0.08 - loosely connected
**Members:** 28 nodes

## Members
- [[A corrupted settled_yes value (anything other than exactly 0 or 1) must refuse…]] - rationale - tests/test_ml_bias.py
- [[A=1.0, B=0.0 (identity) returns approximately the input probability.]] - rationale - tests/test_ml_bias.py
- [[Floor is on the MINORITY class count (EPV -- events per predictor variable),…]] - rationale - tests/test_ml_bias.py
- [[Must include only days_out=0, method='metar_lockout', non-excluded…]] - rationale - tests/test_ml_bias.py
- [[P2-I apply_platt_per_city must preserve monotonic ordering. If raw_p1  raw_p2…]] - rationale - tests/test_ml_bias.py
- [[Regression test for this repo's real production data (2026-08-16) 27 YES-locks…]] - rationale - tests/test_ml_bias.py
- [[Synthesize {our_prob, settled_yes} rows shaped like real METAR lock-in data…]] - rationale - tests/test_ml_bias.py
- [[Tests for ML-based bias correction.]] - rationale - tests/test_ml_bias.py
- [[The mirror case minority class exactly atabove the floor must succeed --…]] - rationale - tests/test_ml_bias.py
- [[Unknown city returns raw prob unchanged.]] - rationale - tests/test_ml_bias.py
- [[When a==b (fit_metar_calibration's Platt-only result is always this form),…]] - rationale - tests/test_ml_bias.py
- [[_metar_rows()]] - code - tests/test_ml_bias.py
- [[_sigmoid must not raise OverflowError for a large-magnitude logit -- reachable…]] - rationale - tests/test_ml_bias.py
- [[numpy_1]] - concept
- [[test_apply_metar_calibration_matches_hand_computed_value()]] - code - tests/test_ml_bias.py
- [[test_apply_metar_calibration_platt_special_case_matches_apply_platt()]] - code - tests/test_ml_bias.py
- [[test_apply_platt_identity_calibration()]] - code - tests/test_ml_bias.py
- [[test_apply_platt_per_city_monotonicity()]] - code - tests/test_ml_bias.py
- [[test_apply_platt_per_city_unknown_city_unchanged()]] - code - tests/test_ml_bias.py
- [[test_fit_metar_calibration_at_epv_floor_succeeds()]] - code - tests/test_ml_bias.py
- [[test_fit_metar_calibration_below_epv_floor_returns_none()]] - code - tests/test_ml_bias.py
- [[test_fit_metar_calibration_on_real_repo_data()]] - code - tests/test_ml_bias.py
- [[test_fit_metar_calibration_rejects_non_binary_labels()]] - code - tests/test_ml_bias.py
- [[test_get_metar_lockout_calibration_data_scopes_correctly()]] - code - tests/test_ml_bias.py
- [[test_ml_bias.py]] - code - tests/test_ml_bias.py
- [[test_sigmoid_does_not_overflow_on_extreme_input()]] - code - tests/test_ml_bias.py
- [[test_train_platt_per_city_returns_coefficients()]] - code - tests/test_ml_bias.py
- [[train_platt_per_city returns {city (A, B)} for cities with =200 samples.]] - rationale - tests/test_ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_99
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 55]]
- 3 edges to [[_COMMUNITY_Community 96]]
- 3 edges to [[_COMMUNITY_Community 230]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 101]]
- 1 edge to [[_COMMUNITY_Community 226]]
- 1 edge to [[_COMMUNITY_Community 508]]
- 1 edge to [[_COMMUNITY_Community 621]]
- 1 edge to [[_COMMUNITY_Community 622]]
- 1 edge to [[_COMMUNITY_Community 23]]
- 1 edge to [[_COMMUNITY_Community 82]]

## Top bridge nodes
- [[test_ml_bias.py]] - degree 37, connects to 10 communities
- [[numpy_1]] - degree 2, connects to 1 community