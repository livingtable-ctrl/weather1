---
type: community
cohesion: 0.29
members: 7
---

# Community 507

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_fresh_entry_returns_price()]] - code - tests/test_kalshi_ws.py
- [[dot-test_missing_ts_returns_none()]] - code - tests/test_kalshi_ws.py
- [[dot-test_stale_entry_returns_none()]] - code - tests/test_kalshi_ws.py
- [[An entry timestamped 15 min ago is returned normally.]] - rationale - tests/test_kalshi_ws.py
- [[An entry timestamped WS_CACHE_TTL_SECS ago returns None.]] - rationale - tests/test_kalshi_ws.py
- [[An entry with no ts field is treated as stale.]] - rationale - tests/test_kalshi_ws.py
- [[TestCacheStaleness]] - code - tests/test_kalshi_ws.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_507
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 30]]

## Top bridge nodes
- [[TestCacheStaleness]] - degree 4, connects to 1 community