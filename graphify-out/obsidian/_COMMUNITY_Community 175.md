---
type: community
cohesion: 0.11
members: 19
---

# Community 175

**Cohesion:** 0.11 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-test_bias_table_exists()]] - code - tests/test_station_bias.py
- [[dot-test_denver_bias_negative()]] - code - tests/test_station_bias.py
- [[dot-test_las_vegas_bias_matches_phoenix()]] - code - tests/test_station_bias.py
- [[dot-test_los_angeles_no_bias()]] - code - tests/test_station_bias.py
- [[dot-test_miami_bias_negative()]] - code - tests/test_station_bias.py
- [[dot-test_new_orleans_bias_matches_houston()]] - code - tests/test_station_bias.py
- [[dot-test_nyc_bias_negative()]] - code - tests/test_station_bias.py
- [[dot-test_unknown_city_no_change()]] - code - tests/test_station_bias.py
- [[Denver has a -2°F bias correction.]] - rationale - tests/test_station_bias.py
- [[LA has no known systematic bias.]] - rationale - tests/test_station_bias.py
- [[Las Vegas has no settled-observation history yet — uses Phoenix's desert-…]] - rationale - tests/test_station_bias.py
- [[Miami has a -3°F bias correction.]] - rationale - tests/test_station_bias.py
- [[NYC has a -1°F bias correction (subtract from model).]] - rationale - tests/test_station_bias.py
- [[New Orleans has no settled-observation history yet — uses Houston's Gulf humid-…]] - rationale - tests/test_station_bias.py
- [[TestStationBiasTables]] - code - tests/test_station_bias.py
- [[Tests for the per-city static station-bias tables. Rewritten 2026-07-12…]] - rationale - tests/test_station_bias.py
- [[Unknown cities have no bias table entry -- callers fall back to 0.0.]] - rationale - tests/test_station_bias.py
- [[_STATION_BIAS (legacy alias for _STATION_BIAS_HIGH) is importable.]] - rationale - tests/test_station_bias.py
- [[test_station_bias.py]] - code - tests/test_station_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_175
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]

## Top bridge nodes
- [[test_station_bias.py]] - degree 3, connects to 1 community