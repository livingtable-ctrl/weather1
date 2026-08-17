---
type: community
cohesion: 0.14
members: 19
---

# Community 175

**Cohesion:** 0.14 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-test_censoring_at_one_shrinks_toward_half()]] - code - tests/test_weather_markets.py
- [[dot-test_censoring_at_zero_shrinks_toward_half()]] - code - tests/test_weather_markets.py
- [[dot-test_correction_formula_values()]] - code - tests/test_weather_markets.py
- [[dot-test_empty_list_returns_half()]] - code - tests/test_weather_markets.py
- [[dot-test_exactly_at_threshold_applies_correction()]] - code - tests/test_weather_markets.py
- [[dot-test_no_censoring_returns_mean_unchanged()]] - code - tests/test_weather_markets.py
- [[dot-test_result_clamped_between_zero_and_one()]] - code - tests/test_weather_markets.py
- [[5% zeros  1% censor_pct threshold → correction applies (result != raw mean).]] - rationale - tests/test_weather_markets.py
- [[Correct ensemble probability for member censoring at 0 or 1 (23). When …]] - rationale - weather_markets.py
- [[Corrected probability must always be in 0, 1.]] - rationale - tests/test_weather_markets.py
- [[Empty prob list returns 0.5 (maximally uncertain).]] - rationale - tests/test_weather_markets.py
- [[Many ones (5% censored at 1) → result  raw mean (pulled toward 0.5).]] - rationale - tests/test_weather_markets.py
- [[Many zeros (5% censored at 0) → result  raw mean (pulled toward 0.5).]] - rationale - tests/test_weather_markets.py
- [[Probs spread across (0, 1) with no censoring → corrected == raw mean.]] - rationale - tests/test_weather_markets.py
- [[TestCensoringCorrection]] - code - tests/test_weather_markets.py
- [[TestCensoringCorrection (23)]] - code - tests/test_weather_markets.py
- [[Tests for censoring_correction() in weather_markets (23).]] - rationale - tests/test_weather_markets.py
- [[Verify the Tobit-style formula numerically.]] - rationale - tests/test_weather_markets.py
- [[censoring_correction()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_175
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 11]]
- 1 edge to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 33]]

## Top bridge nodes
- [[censoring_correction()]] - degree 12, connects to 3 communities
- [[TestCensoringCorrection]] - degree 9, connects to 1 community