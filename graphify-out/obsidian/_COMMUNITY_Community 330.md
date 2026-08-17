---
type: community
cohesion: 0.23
members: 12
---

# Community 330

**Cohesion:** 0.23 - loosely connected
**Members:** 12 nodes

## Members
- [[dot-_make_analysis()]] - code - tests/test_weather.py
- [[dot-test_ci_adjusted_kelly_minimum_confidence()]] - code - tests/test_weather.py
- [[dot-test_ci_adjusted_kelly_no_reduction_on_zero_ci()]] - code - tests/test_weather.py
- [[dot-test_ci_adjusted_kelly_nonnegative()]] - code - tests/test_weather.py
- [[dot-test_ci_adjusted_kelly_reduces_on_wide_ci()]] - code - tests/test_weather.py
- [[CI width  0.75 → confidence floored at 0.25.]] - rationale - tests/test_weather.py
- [[Simulate an analyze_trade return dict with specific CI and Kelly values.]] - rationale - tests/test_weather.py
- [[TestCIAdjustedKelly]] - code - tests/test_weather.py
- [[Tests that CI width correctly scales the fee-adjusted Kelly fraction.]] - rationale - tests/test_weather.py
- [[Wide CI (width=0.5) reduces Kelly by 50%.]] - rationale - tests/test_weather.py
- [[Zero CI width → no reduction (confidence=1.0).]] - rationale - tests/test_weather.py
- [[ci_adjusted_kelly should never be negative.]] - rationale - tests/test_weather.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_330
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 396]]

## Top bridge nodes
- [[TestCIAdjustedKelly]] - degree 7, connects to 1 community