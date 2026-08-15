---
type: community
cohesion: 0.19
members: 15
---

# Community 241

**Cohesion:** 0.19 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-_condition()_3]] - code - tests/test_weather_markets.py
- [[dot-test_below_condition_widens_sigma_in_gaussian_branch()]] - code - tests/test_weather_markets.py
- [[dot-test_below_ten_members_uses_gaussian_not_emos()]] - code - tests/test_weather_markets.py
- [[dot-test_emos_falls_back_to_raw_fraction_when_untrained()]] - code - tests/test_weather_markets.py
- [[dot-test_emos_used_when_params_trained()]] - code - tests/test_weather_markets.py
- [[dot-test_exactly_ten_members_uses_emos_or_ensemble_not_gaussian()]] - code - tests/test_weather_markets.py
- [[dot-test_nine_members_uses_gaussian()]] - code - tests/test_weather_markets.py
- [[10 members must take the Gaussian branch (_forecast_probability), never EMOS…]] - rationale - tests/test_weather_markets.py
- [[=10 members with EMOS params available must use method='emos', not the raw-…]] - rationale - tests/test_weather_markets.py
- [[=10 members with no EMOS params must use the raw exceedance fraction fallback,…]] - rationale - tests/test_weather_markets.py
- [[Dedicated unit tests for _compute_ensemble_prob(), extracted from…]] - rationale - tests/test_weather_markets.py
- [[One below the boundary must still take the Gaussian branch.]] - rationale - tests/test_weather_markets.py
- [[TestComputeEnsembleProbRefactorSafetyNet]] - code - tests/test_weather_markets.py
- [[The =10 boundary is inclusive -- exactly 10 members must take the EMOSraw-…]] - rationale - tests/test_weather_markets.py
- [[below' condition type widens sigma by 1.5x in the Gaussian branch (empirical…]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_241
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]

## Top bridge nodes
- [[TestComputeEnsembleProbRefactorSafetyNet]] - degree 9, connects to 1 community