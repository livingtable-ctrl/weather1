---
type: community
cohesion: 0.04
members: 66
---

# ML Bias Multiday-Predictions Filter

**Cohesion:** 0.04 - loosely connected
**Members:** 66 nodes

## Members
- [[dot-test_emos_exceedance_prob_called_via_load_emos_params()]] - code - tests/test_ml_bias.py
- [[dot-test_emos_exceedance_prob_in_bounds()]] - code - tests/test_ml_bias.py
- [[dot-test_emos_exceedance_prob_monotone()]] - code - tests/test_ml_bias.py
- [[dot-test_emos_interval_and_exceedance_consistent()]] - code - tests/test_ml_bias.py
- [[dot-test_emos_interval_prob_in_bounds()]] - code - tests/test_ml_bias.py
- [[dot-test_fit_emos_returns_four_floats()]] - code - tests/test_ml_bias.py
- [[dot-test_get_emos_training_data_excludes_null_ens_mean()]] - code - tests/test_ml_bias.py
- [[dot-test_load_emos_params_returns_none_when_file_missing()]] - code - tests/test_ml_bias.py
- [[dot-test_save_and_reload_emos_params()]] - code - tests/test_ml_bias.py
- [[A=1.0, B=0.0 (identity) returns approximately the input probability.]] - rationale - tests/test_ml_bias.py
- [[Apply per-city Platt calibration; returns raw_prob unchanged if no model.]] - rationale - ml_bias.py
- [[Apply temperature calibration; returns prob unchanged if no model is trained.…]] - rationale - ml_bias.py
- [[Compute HMAC-SHA256 of data using MODEL_HMAC_SECRET.]] - rationale - ml_bias.py
- [[Fit EMOS parameters (a, b, c, d) minimising mean CRPS. Model T ~ N(mu,…]] - rationale - ml_bias.py
- [[Higher threshold → lower exceedance probability.]] - rationale - tests/test_ml_bias.py
- [[I1 multiday_predictions View Filter]] - document - docs/grade_audit/outputs
- [[Load bias models from disk after HMAC verification. Refuses to deserialise if…]] - rationale - ml_bias.py
- [[Load the temperature scaling table from disk. Supports two file formats - New…]] - rationale - ml_bias.py
- [[ML-based probability calibration — GradientBoosting per-city correction of…]] - rationale - ml_bias.py
- [[P(T  threshold) from a fitted EMOS Gaussian distribution. CRITICAL pass…]] - rationale - ml_bias.py
- [[P(Tthreshold) + P(lowTthreshold) should equal P(Tlow).]] - rationale - tests/test_ml_bias.py
- [[P(low  T  high) from a fitted EMOS Gaussian — for 'between' markets.…]] - rationale - ml_bias.py
- [[P2-I apply_platt_per_city must preserve monotonic ordering. If raw_p1  raw_p2…]] - rationale - tests/test_ml_bias.py
- [[Persist EMOS parameters and clear the in-process cache.]] - rationale - ml_bias.py
- [[Return cached (a, b, c, d) from emos_params.json, or None if not trained.]] - rationale - ml_bias.py
- [[Return the HMAC secret from env. Empty string disables verification (dev only).]] - rationale - ml_bias.py
- [[TestEmos]] - code - tests/test_ml_bias.py
- [[Tests for ML-based bias correction.]] - rationale - tests/test_ml_bias.py
- [[Two-stage EMOS fit mean calibration (a,b) from all rows, variance (c,d) from…]] - rationale - main.py
- [[Unknown city returns raw prob unchanged.]] - rationale - tests/test_ml_bias.py
- [[Write HMAC sidecar for a freshly serialised pickle.]] - rationale - ml_bias.py
- [[_cmd_emos_train()]] - code - main.py
- [[_compute_hmac()]] - code - ml_bias.py
- [[_hmac_secret()]] - code - ml_bias.py
- [[_load_emos_params must return the cache when _EMOS_CACHE is populated.]] - rationale - tests/test_ml_bias.py
- [[_load_emos_params()]] - code - ml_bias.py
- [[_load_models()]] - code - ml_bias.py
- [[_load_temperature_scale()]] - code - ml_bias.py
- [[_load_temperature_scale() RF1 Bare Except No Log (510)]] - document - docs/grade_audit/outputs/ml_bias.py.md
- [[_logit()]] - code - ml_bias.py
- [[_sigmoid()]] - code - ml_bias.py
- [[_write_hmac()]] - code - ml_bias.py
- [[apply_ml_prob_correction() RF1 DEBUG on Model Failure (610)]] - document - docs/grade_audit/outputs/ml_bias.py.md
- [[apply_platt_per_city()]] - code - ml_bias.py
- [[apply_temperature_scaling()]] - code - ml_bias.py
- [[emos_exceedance_prob Function]] - code - ml_bias.py
- [[emos_exceedance_prob()]] - code - ml_bias.py
- [[emos_interval_prob Function]] - code - ml_bias.py
- [[emos_interval_prob()]] - code - ml_bias.py
- [[fit_emos Function]] - code - ml_bias.py
- [[fit_emos()]] - code - ml_bias.py
- [[ml_bias.py]] - code - ml_bias.py
- [[ml_bias.py_1]] - code - ml_bias.py
- [[ml_bias.py File Grade median 810, 2 mandatory fixes]] - document - docs/grade_audit/outputs/ml_bias.py.md
- [[ml_bias.py Grade Audit]] - document - docs/grade_audit/outputs/ml_bias.py.md
- [[ndarray]] - code
- [[save_emos_params Function]] - code - ml_bias.py
- [[save_emos_params()]] - code - ml_bias.py
- [[test_apply_platt_identity_calibration()]] - code - tests/test_ml_bias.py
- [[test_apply_platt_per_city_monotonicity()]] - code - tests/test_ml_bias.py
- [[test_apply_platt_per_city_unknown_city_unchanged()]] - code - tests/test_ml_bias.py
- [[test_ml_bias.py]] - code - tests/test_ml_bias.py
- [[test_train_platt_per_city_returns_coefficients()]] - code - tests/test_ml_bias.py
- [[train_bias_model() NULL our_prob Silently Substituted as 0.0 (710)]] - document - docs/grade_audit/outputs/ml_bias.py.md
- [[train_platt_per_city returns {city (A, B)} for cities with =200 samples.]] - rationale - tests/test_ml_bias.py
- [[weather_markets._KXTEMP_HOURLY_CITY]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/ML_Bias_Multiday-Predictions_Filter
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 4 edges to [[_COMMUNITY_Black Swan Halt State]]
- 4 edges to [[_COMMUNITY_Community 353]]
- 4 edges to [[_COMMUNITY_Community 79]]
- 3 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 3 edges to [[_COMMUNITY_Community 120]]
- 3 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 3 edges to [[_COMMUNITY_Community 32]]
- 3 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 2 edges to [[_COMMUNITY_Community 214]]
- 2 edges to [[_COMMUNITY_Community 47]]
- 2 edges to [[_COMMUNITY_Community 195]]
- 1 edge to [[_COMMUNITY_Community 103]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 113]]
- 1 edge to [[_COMMUNITY_Community 471]]
- 1 edge to [[_COMMUNITY_Community 184]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]

## Top bridge nodes
- [[test_ml_bias.py]] - degree 28, connects to 11 communities
- [[ml_bias.py]] - degree 30, connects to 9 communities
- [[apply_temperature_scaling()]] - degree 10, connects to 3 communities
- [[_load_models()]] - degree 8, connects to 3 communities
- [[_cmd_emos_train()]] - degree 8, connects to 2 communities