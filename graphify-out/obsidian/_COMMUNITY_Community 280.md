---
type: community
cohesion: 0.19
members: 13
---

# Community 280

**Cohesion:** 0.19 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-test_dew_point_temp_correction_at_saturation()]] - code - tests/test_metar.py
- [[dot-test_dew_point_temp_correction_dry_city_no_effect()]] - code - tests/test_metar.py
- [[dot-test_dew_point_temp_correction_dry_conditions_no_effect()]] - code - tests/test_metar.py
- [[dot-test_dew_point_temp_correction_miami()]] - code - tests/test_metar.py
- [[dot-test_fetch_metar_includes_dew_point_f()]] - code - tests/test_metar.py
- [[At depression=0 (saturated), correction is exactly -3.0 (the formula max).]] - rationale - tests/test_metar.py
- [[Denver (not in sensitive set) must return 0.0 regardless of dew point.]] - rationale - tests/test_metar.py
- [[Even for a sensitive city, depression = 20°F means no correction.]] - rationale - tests/test_metar.py
- [[Miami humid day dew=76, forecast=90 → depression=14°F  20°F → negative…]] - rationale - tests/test_metar.py
- [[Return a bias correction (°F, negative = cooler) based on dew point depression.…]] - rationale - weather_markets.py
- [[TestDewPointCorrection]] - code - tests/test_metar.py
- [[_dew_point_temp_correction()]] - code - weather_markets.py
- [[fetch_metar result dict must include dew_point_f key.]] - rationale - tests/test_metar.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_280
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 9]]
- 2 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 3]]

## Top bridge nodes
- [[_dew_point_temp_correction()]] - degree 8, connects to 2 communities
- [[TestDewPointCorrection]] - degree 7, connects to 2 communities
- [[dot-test_fetch_metar_includes_dew_point_f()]] - degree 4, connects to 2 communities