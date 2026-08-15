---
type: community
cohesion: 0.20
members: 14
---

# Community 264

**Cohesion:** 0.20 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-_add_member()]] - code - tests/test_tracker.py
- [[dot-test_basic_accuracy()]] - code - tests/test_tracker.py
- [[dot-test_city_filter()]] - code - tests/test_tracker.py
- [[dot-test_returns_none_when_empty()]] - code - tests/test_tracker.py
- [[dot-test_season_filter_summer()]] - code - tests/test_tracker.py
- [[dot-test_season_filter_winter()]] - code - tests/test_tracker.py
- [[dot-test_season_filter_winter_vs_summer_different_mae()]] - code - tests/test_tracker.py
- [[City filter returns only data for that city.]] - rationale - tests/test_tracker.py
- [[Returns model MAE dict for available data.]] - rationale - tests/test_tracker.py
- [[Summer filter returns only Apr-Sep data.]] - rationale - tests/test_tracker.py
- [[TestEnsembleMemberAccuracy]] - code - tests/test_tracker.py
- [[Tests for get_ensemble_member_accuracy() (18).]] - rationale - tests/test_tracker.py
- [[Winter and summer MAEs differ for the same model.]] - rationale - tests/test_tracker.py
- [[Winter filter returns only Oct-Mar data.]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_264
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 313]]

## Top bridge nodes
- [[TestEnsembleMemberAccuracy]] - degree 10, connects to 2 communities