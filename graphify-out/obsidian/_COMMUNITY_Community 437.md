---
type: community
cohesion: 0.25
members: 8
---

# Community 437

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_bucket_fields()]] - code - tests/test_tracker.py
- [[dot-test_clustered_data_n_buckets_5()]] - code - tests/test_tracker.py
- [[dot-test_empty_returns_empty_buckets()]] - code - tests/test_tracker.py
- [[dot-test_returns_buckets_key()]] - code - tests/test_tracker.py
- [[30 predictions clustered near 0.50, n_buckets=5 → = 5 buckets returned.]] - rationale - tests/test_tracker.py
- [[Each bucket should have required fields.]] - rationale - tests/test_tracker.py
- [[TestMarketCalibrationAdaptive]] - code - tests/test_tracker.py
- [[Tests for get_market_calibration() quantile-based bucketing (13).]] - rationale - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_437
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 135]]
- 1 edge to [[_COMMUNITY_Community 313]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]

## Top bridge nodes
- [[TestMarketCalibrationAdaptive]] - degree 7, connects to 2 communities
- [[dot-test_bucket_fields()]] - degree 3, connects to 1 community
- [[dot-test_clustered_data_n_buckets_5()]] - degree 3, connects to 1 community