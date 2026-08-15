---
type: community
cohesion: 0.14
members: 20
---

# Community 160

**Cohesion:** 0.14 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-test_basic()]] - code - tests/test_weather.py
- [[dot-test_empty()]] - code - tests/test_weather.py
- [[dot-test_empty_list_returns_empty_dict()]] - code - tests/test_weather_markets.py
- [[dot-test_mean_std_correct()]] - code - tests/test_weather_markets.py
- [[dot-test_min_max_correct()]] - code - tests/test_weather_markets.py
- [[dot-test_p10_less_than_p90()]] - code - tests/test_weather_markets.py
- [[dot-test_returns_all_required_keys()]] - code - tests/test_weather_markets.py
- [[dot-test_single()]] - code - tests/test_weather.py
- [[dot-test_single_element_std_is_zero()]] - code - tests/test_weather_markets.py
- [[Group A Testing Plan]] - document - docs/superpowers/plans/2026-04-10-group-a-testing.md
- [[Result must contain n, mean, std, min, max, p10, p90.]] - rationale - tests/test_weather_markets.py
- [[Single-element ensemble std=0, min=max=mean=the value.]] - rationale - tests/test_weather_markets.py
- [[Summary statistics for a list of ensemble member temperatures.]] - rationale - weather_markets.py
- [[TestEnsembleStats_1]] - code - tests/test_weather_markets.py
- [[TestEnsembleStats]] - code - tests/test_weather.py
- [[Verify mean and std match statistics module on known data.]] - rationale - tests/test_weather_markets.py
- [[ensemble_stats()]] - code - weather_markets.py
- [[ensemble_stats() must return {} not raise.]] - rationale - tests/test_weather_markets.py
- [[min and max match the actual extremes.]] - rationale - tests/test_weather_markets.py
- [[p10 = mean = p90 for a non-degenerate ensemble.]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_160
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 3 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 3 edges to [[_COMMUNITY_Community 59]]
- 2 edges to [[_COMMUNITY_Weather Probability Math Tests]]
- 1 edge to [[_COMMUNITY_Community 230]]
- 1 edge to [[_COMMUNITY_Community 271]]
- 1 edge to [[_COMMUNITY_Community 173]]
- 1 edge to [[_COMMUNITY_Community 388]]
- 1 edge to [[_COMMUNITY_Legacy Static Dashboard JS Pages]]
- 1 edge to [[_COMMUNITY_Community 36]]

## Top bridge nodes
- [[ensemble_stats()]] - degree 24, connects to 9 communities
- [[Group A Testing Plan]] - degree 3, connects to 2 communities
- [[TestEnsembleStats_1]] - degree 7, connects to 1 community
- [[TestEnsembleStats]] - degree 4, connects to 1 community