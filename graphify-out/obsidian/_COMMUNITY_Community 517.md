---
type: community
cohesion: 0.33
members: 6
---

# Community 517

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_future_trade_not_skipped()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_past_date_skip_uses_utc()]] - code - tests/test_phase2_batch_h.py
- [[A trade dated in the future must NOT be skipped.]] - rationale - tests/test_phase2_batch_h.py
- [[A trade dated yesterday UTC must be skipped.]] - rationale - tests/test_phase2_batch_h.py
- [[P2-25 monte_carlo skips past-date trades using UTC date.]] - rationale - tests/test_phase2_batch_h.py
- [[TestMonteCarloUtcDate]] - code - tests/test_phase2_batch_h.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_517
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]

## Top bridge nodes
- [[TestMonteCarloUtcDate]] - degree 4, connects to 1 community