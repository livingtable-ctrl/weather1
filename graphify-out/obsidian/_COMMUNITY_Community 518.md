---
type: community
cohesion: 0.33
members: 6
---

# Community 518

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_monday_check_uses_utc_weekday()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_naive_timestamp_treated_as_utc()]] - code - tests/test_phase2_batch_h.py
- [[A naive ISO timestamp from DB must be interpreted as UTC, not local.]] - rationale - tests/test_phase2_batch_h.py
- [[P2-18 _check_startup_orders must treat naive DB timestamps as UTC.]] - rationale - tests/test_phase2_batch_h.py
- [[TestCronStartupOrdersUtc]] - code - tests/test_phase2_batch_h.py
- [[Weekly DB sweep must fire on UTC Monday, not local Monday.]] - rationale - tests/test_phase2_batch_h.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_518
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]

## Top bridge nodes
- [[TestCronStartupOrdersUtc]] - degree 4, connects to 1 community