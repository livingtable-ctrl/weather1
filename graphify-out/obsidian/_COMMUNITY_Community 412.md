---
type: community
cohesion: 0.28
members: 9
---

# Community 412

**Cohesion:** 0.28 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-_insert_raw()]] - code - tests/test_tracker.py
- [[dot-setUp()_30]] - code - tests/test_tracker.py
- [[dot-tearDown()_29]] - code - tests/test_tracker.py
- [[dot-test_trend_bucket_uses_market_date_week()]] - code - tests/test_tracker.py
- [[dot-test_trend_returns_list_of_dicts_with_week_brier_n()]] - code - tests/test_tracker.py
- [[Each trend entry must have week, brier, and n keys.]] - rationale - tests/test_tracker.py
- [[TestCalibrationTrendUsesMarketDate]] - code - tests/test_tracker.py
- [[Two predictions made in same analysis week but different market-date weeks must…]] - rationale - tests/test_tracker.py
- [[Verify get_calibration_trend groups by market_date, not predicted_at (54).]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_412
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestCalibrationTrendUsesMarketDate]] - degree 7, connects to 1 community