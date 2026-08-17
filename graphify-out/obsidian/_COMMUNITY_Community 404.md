---
type: community
cohesion: 0.25
members: 9
---

# Community 404

**Cohesion:** 0.25 - loosely connected
**Members:** 9 nodes

## Members
- [[Append a single entry dict as a JSONL line to the entries log.]] - rationale - execution_log.py
- [[Path_17]] - code
- [[Return today's accumulated live loss in dollars (UTC date). Fails closed if a…]] - rationale - execution_log.py
- [[True if a prior add_live_loss() failure left today's total untrustworthy.]] - rationale - execution_log.py
- [[_degraded_flag_path()]] - code - execution_log.py
- [[_degraded_for_today()]] - code - execution_log.py
- [[_set_degraded_flag()]] - code - execution_log.py
- [[append_entry()]] - code - execution_log.py
- [[get_today_live_loss()]] - code - execution_log.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_404
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 42]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 170]]
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 7]]
- 1 edge to [[_COMMUNITY_Community 44]]

## Top bridge nodes
- [[get_today_live_loss()]] - degree 9, connects to 4 communities
- [[append_entry()]] - degree 5, connects to 3 communities
- [[_degraded_flag_path()]] - degree 5, connects to 1 community
- [[_degraded_for_today()]] - degree 4, connects to 1 community
- [[_set_degraded_flag()]] - degree 4, connects to 1 community