---
type: community
cohesion: 0.16
members: 14
---

# Community 250

**Cohesion:** 0.16 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-_mock_climate_history()]] - code - tests/test_climatology.py
- [[dot-test_missing_cities_helper_returns_empty_when_all_present()]] - code - tests/test_climatology.py
- [[dot-test_missing_cities_helper_treats_absent_file_as_all_missing()]] - code - tests/test_climatology.py
- [[dot-test_missing_cities_helper_treats_corrupt_file_as_all_missing()]] - code - tests/test_climatology.py
- [[dot-test_missing_cities_helper_treats_empty_entry_as_missing()]] - code - tests/test_climatology.py
- [[dot-test_missing_cities_helper_treats_non_dict_json_as_all_missing()]] - code - tests/test_climatology.py
- [[dot-test_second_call_for_same_cities_does_not_recompute()]] - code - tests/test_climatology.py
- [[dot-test_sequential_per_city_preload_all_calls_build_full_table()]] - code - tests/test_climatology.py
- [[Once a city is already in the fresh cache, a later preload_all() call for that…]] - rationale - tests/test_climatology.py
- [[TestPreloadAllSigmaGate]] - code - tests/test_climatology.py
- [[The exact backlog scenario main.py's wizard calls preload_all({city…]] - rationale - tests/test_climatology.py
- [[backlog.txt PRELOAD_ALL CAN PERMANENTLY TRUNCATE forecast_sigma.json TO ONE…]] - rationale - tests/test_climatology.py
- [[opus-review-caught 2026-08-07 a city KEY present in the file with no real…]] - rationale - tests/test_climatology.py
- [[opus-review-caught 2026-08-07 valid JSON that isn't an object (null, a list,…]] - rationale - tests/test_climatology.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_250
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestPreloadAllSigmaGate]] - degree 10, connects to 1 community