---
type: community
cohesion: 0.05
members: 53
---

# Community 26

**Cohesion:** 0.05 - loosely connected
**Members:** 53 nodes

## Members
- [[dot-test_50pct_at_mean()]] - code - tests/test_gaussian_prob.py
- [[dot-test_all_calibrated_sigmas_in_rmse_range()]] - code - tests/test_gaussian_prob.py
- [[dot-test_below_direction()]] - code - tests/test_gaussian_prob.py
- [[dot-test_chicago_returns_calibrated_not_default()]] - code - tests/test_gaussian_prob.py
- [[dot-test_dallas_returns_calibrated_not_default()]] - code - tests/test_gaussian_prob.py
- [[dot-test_denver_returns_calibrated_not_default()]] - code - tests/test_gaussian_prob.py
- [[dot-test_get_historical_sigma_returns_float()]] - code - tests/test_gaussian_prob.py
- [[dot-test_get_historical_sigma_unknown_city_default()]] - code - tests/test_gaussian_prob.py
- [[dot-test_high_prob_when_mean_well_above_threshold()]] - code - tests/test_gaussian_prob.py
- [[dot-test_la_returns_calibrated_not_default()]] - code - tests/test_gaussian_prob.py
- [[dot-test_miami_returns_calibrated_not_default()]] - code - tests/test_gaussian_prob.py
- [[dot-test_probability_clamped_to_unit_interval()]] - code - tests/test_gaussian_prob.py
- [[dot-test_wider_sigma_flattens_probability()]] - code - tests/test_gaussian_prob.py
- [[50th-percentile threshold → P(above) near 0.50.]] - rationale - tests/test_gaussian_prob.py
- [[Chicago must return its calibrated sigma, not the 3.5°F default. L8-C bug…]] - rationale - tests/test_gaussian_prob.py
- [[Compute P(T  threshold) or P(T  threshold) using a Gaussian distribution.…]] - rationale - weather_markets.py
- [[Convert month (1-12) to season index (1=Winter, 2=Spring, 3=Summer, 4=Fall).]] - rationale - weather_markets.py
- [[Dallas must return its calibrated sigma (was keyed 'DAL', city is 'Dallas').]] - rationale - tests/test_gaussian_prob.py
- [[Denver must return its calibrated sigma (was keyed 'DEN', city is 'Denver').]] - rationale - tests/test_gaussian_prob.py
- [[Every calibrated sigma must be in the NWS Day-3 RMSE range (1.5–5°F).]] - rationale - tests/test_gaussian_prob.py
- [[Grade Audit Module Doc nws.py]] - document - docs/grade_audit/modules/nws.md
- [[Grade Audit Module Doc weather_markets.py]] - document - docs/grade_audit/modules/weather_markets.md
- [[Higher sigma → probability closer to 0.5.]] - rationale - tests/test_gaussian_prob.py
- [[LA must return its calibrated sigma (was keyed 'LAX', city is 'LA').]] - rationale - tests/test_gaussian_prob.py
- [[Lazily load+memoize per-city, per-month sigma computed from the 30yr climate…]] - rationale - weather_markets.py
- [[Miami must return its calibrated sigma (was keyed 'MIA', city is 'Miami').]] - rationale - tests/test_gaussian_prob.py
- [[NWS Sigma Ladder (days_out-based)]] - document - docs/grade_audit/modules/nws.md
- [[P(T  threshold) is complement of above.]] - rationale - tests/test_gaussian_prob.py
- [[P(T  65) ≈ 84% when mean=70, sigma=5 (1 sigma above).]] - rationale - tests/test_gaussian_prob.py
- [[P(T  threshold) = 50% when threshold equals the forecast mean.]] - rationale - tests/test_gaussian_prob.py
- [[P(between) counts members in range.]] - rationale - tests/test_gaussian_prob.py
- [[Return forecast RMSE sigma (°F) for a citymonth. Prefers dynamic values…]] - rationale - weather_markets.py
- [[TestGaussianProbability]] - code - tests/test_gaussian_prob.py
- [[Tests for Gaussian probability distribution method.]] - rationale - tests/test_gaussian_prob.py
- [[Threshold below all members → P(above) near 1.0.]] - rationale - tests/test_gaussian_prob.py
- [[Unknown city returns the default sigma in the NWS RMSE range.]] - rationale - tests/test_gaussian_prob.py
- [[When get_ensemble_members succeeds, blend_sources includes 'ensemble_cdf'.]] - rationale - tests/test_gaussian_prob.py
- [[_load_dynamic_sigma()]] - code - weather_markets.py
- [[_month_to_season()_1]] - code - weather_markets.py
- [[gaussian_probability always returns a value in 0, 1.]] - rationale - tests/test_gaussian_prob.py
- [[gaussian_probability()]] - code - weather_markets.py
- [[get_ensemble_members returns None when the API errors.]] - rationale - tests/test_gaussian_prob.py
- [[get_ensemble_members returns a list of ≥10 floats on success.]] - rationale - tests/test_gaussian_prob.py
- [[get_historical_sigma returns a positive float in the NWS RMSE range (2-5°F).]] - rationale - tests/test_gaussian_prob.py
- [[get_historical_sigma()]] - code - weather_markets.py
- [[test_analyze_trade_includes_ensemble_cdf_in_blend_sources()]] - code - tests/test_gaussian_prob.py
- [[test_ensemble_cdf_prob_above_at_median()]] - code - tests/test_gaussian_prob.py
- [[test_ensemble_cdf_prob_below_threshold_below_all()]] - code - tests/test_gaussian_prob.py
- [[test_ensemble_cdf_prob_between()]] - code - tests/test_gaussian_prob.py
- [[test_fetch_ensemble_members_returns_list()]] - code - tests/test_gaussian_prob.py
- [[test_gaussian_prob.py]] - code - tests/test_gaussian_prob.py
- [[test_get_ensemble_members_returns_none_on_failure()]] - code - tests/test_gaussian_prob.py
- [[test_signal_quality.py_1]] - code - tests/test_signal_quality.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_26
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 3 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 2 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 2 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 2 edges to [[_COMMUNITY_Community 257]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Test Fixture Cache Clearing (conftest)]]
- 1 edge to [[_COMMUNITY_Community 217]]
- 1 edge to [[_COMMUNITY_Community 163]]
- 1 edge to [[_COMMUNITY_Community 465]]
- 1 edge to [[_COMMUNITY_Community 277]]
- 1 edge to [[_COMMUNITY_Community 41]]
- 1 edge to [[_COMMUNITY_Community 575]]
- 1 edge to [[_COMMUNITY_Community 82]]
- 1 edge to [[_COMMUNITY_Community 497]]
- 1 edge to [[_COMMUNITY_Community 211]]
- 1 edge to [[_COMMUNITY_Community 109]]

## Top bridge nodes
- [[Grade Audit Module Doc weather_markets.py]] - degree 10, connects to 8 communities
- [[test_gaussian_prob.py]] - degree 21, connects to 7 communities
- [[get_historical_sigma()]] - degree 15, connects to 3 communities
- [[gaussian_probability()]] - degree 11, connects to 3 communities
- [[Grade Audit Module Doc nws.py]] - degree 4, connects to 2 communities