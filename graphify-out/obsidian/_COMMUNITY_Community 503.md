---
type: community
cohesion: 0.33
members: 6
---

# Community 503

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[Dead man's switch — run manually to check bot health py watchdog.py If the…]] - rationale - watchdog.py
- [[is_heartbeat_stale()]] - code - watchdog.py
- [[send_alert()]] - code - watchdog.py
- [[test_dead_man.py]] - code - tests/test_dead_man.py
- [[test_heartbeat_stale_detection()]] - code - tests/test_dead_man.py
- [[watchdog.py]] - code - watchdog.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_503
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]

## Top bridge nodes
- [[watchdog.py]] - degree 5, connects to 2 communities