---
type: community
cohesion: 0.40
members: 5
---

# Community 538

**Cohesion:** 0.40 - moderately connected
**Members:** 5 nodes

## Members
- [[Mock market in conftest must include every field production code reads.]] - rationale - tests/test_schema_drift.py
- [[Schema drift detection ensure mock market data used in conftest matches the…]] - rationale - tests/test_schema_drift.py
- [[mock_market fixture]] - code - tests/conftest.py
- [[test_conftest_mock_market_has_all_required_fields()]] - code - tests/test_schema_drift.py
- [[test_schema_drift.py]] - code - tests/test_schema_drift.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_538
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]

## Top bridge nodes
- [[mock_market fixture]] - degree 2, connects to 1 community