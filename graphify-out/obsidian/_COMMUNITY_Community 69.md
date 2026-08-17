---
type: community
cohesion: 0.07
members: 33
---

# Community 69

**Cohesion:** 0.07 - loosely connected
**Members:** 33 nodes

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
- [[Chicago must return its calibrated sigma, not the 3.5°F default. L8-C bug…]] - rationale - tests/test_gaussian_prob.py
- [[Convert month (1-12) to season index (1=Winter, 2=Spring, 3=Summer, 4=Fall).]] - rationale - weather_markets.py
- [[Dallas must return its calibrated sigma (was keyed 'DAL', city is 'Dallas').]] - rationale - tests/test_gaussian_prob.py
- [[Denver must return its calibrated sigma (was keyed 'DEN', city is 'Denver').]] - rationale - tests/test_gaussian_prob.py
- [[Every calibrated sigma must be in the NWS Day-3 RMSE range (1.5–5°F).]] - rationale - tests/test_gaussian_prob.py
- [[Higher sigma → probability closer to 0.5.]] - rationale - tests/test_gaussian_prob.py
- [[LA must return its calibrated sigma (was keyed 'LAX', city is 'LA').]] - rationale - tests/test_gaussian_prob.py
- [[Lazily load+memoize per-city, per-month sigma computed from the 30yr climate…]] - rationale - weather_markets.py
- [[Miami must return its calibrated sigma (was keyed 'MIA', city is 'Miami').]] - rationale - tests/test_gaussian_prob.py
- [[P(T  threshold) is complement of above.]] - rationale - tests/test_gaussian_prob.py
- [[P(T  65) ≈ 84% when mean=70, sigma=5 (1 sigma above).]] - rationale - tests/test_gaussian_prob.py
- [[P(T  threshold) = 50% when threshold equals the forecast mean.]] - rationale - tests/test_gaussian_prob.py
- [[Return forecast RMSE sigma (°F) for a citymonth. Prefers dynamic values…]] - rationale - weather_markets.py
- [[TestGaussianProbability]] - code - tests/test_gaussian_prob.py
- [[Unknown city returns the default sigma in the NWS RMSE range.]] - rationale - tests/test_gaussian_prob.py
- [[_load_dynamic_sigma()]] - code - weather_markets.py
- [[_month_to_season()_1]] - code - weather_markets.py
- [[gaussian_probability always returns a value in 0, 1.]] - rationale - tests/test_gaussian_prob.py
- [[get_historical_sigma returns a positive float in the NWS RMSE range (2-5°F).]] - rationale - tests/test_gaussian_prob.py
- [[get_historical_sigma()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_69
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 5]]
- 2 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 102]]
- 1 edge to [[_COMMUNITY_Community 38]]

## Top bridge nodes
- [[get_historical_sigma()]] - degree 15, connects to 4 communities
- [[_load_dynamic_sigma()]] - degree 4, connects to 2 communities
- [[TestGaussianProbability]] - degree 14, connects to 1 community
- [[dot-test_50pct_at_mean()]] - degree 3, connects to 1 community
- [[dot-test_below_direction()]] - degree 3, connects to 1 community