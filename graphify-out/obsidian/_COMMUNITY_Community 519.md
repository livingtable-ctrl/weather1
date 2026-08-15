---
type: community
cohesion: 0.33
members: 6
---

# Community 519

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-test_days_out_uses_utc()]] - code - tests/test_phase2_batch_h.py
- [[dot-test_nws_imports_utc_today()]] - code - tests/test_phase2_batch_h.py
- [[P2-18P2-25 nws.nws_prob must use UTC date for days_out.]] - rationale - tests/test_phase2_batch_h.py
- [[Patching _utc_today in nws changes the days_out computation.]] - rationale - tests/test_phase2_batch_h.py
- [[TestNwsUtcDate]] - code - tests/test_phase2_batch_h.py
- [[nws module must have _utc_today symbol (imported from utils).]] - rationale - tests/test_phase2_batch_h.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_519
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]

## Top bridge nodes
- [[TestNwsUtcDate]] - degree 4, connects to 1 community