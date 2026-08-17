---
type: community
cohesion: 0.20
members: 10
---

# Community 386

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_city_weights_file_exists()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_city_weights_values_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_condition_weights_file_exists()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_condition_weights_has_all_types()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_condition_weights_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_seasonal_weights_file_exists()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_seasonal_weights_has_all_seasons()]] - code - tests/test_phase2_batch_c.py
- [[dot-test_seasonal_weights_sum_to_1()]] - code - tests/test_phase2_batch_c.py
- [[P2-7 seasonal, condition, and city weight files must be present.]] - rationale - tests/test_phase2_batch_c.py
- [[TestWeightFilesExist]] - code - tests/test_phase2_batch_c.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_386
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[TestWeightFilesExist]] - degree 11, connects to 2 communities