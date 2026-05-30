---
type: community
cohesion: 0.40
members: 5
---

# Module: sem

**Cohesion:** 0.40 - moderately connected
**Members:** 5 nodes

## Members
- [[Kalshi WebSocket (real-time orderbook cache)]] - code - kalshi_ws.py
- [[METAR (same-day observation lock-in)]] - code - metar.py
- [[Safe IO (atomic writes + CRC integrity)]] - code - safe_io.py
- [[Settlement Monitor (auto-settle via METARNWS)]] - code - settlement_monitor.py
- [[Settlement Monitor Test Suite]] - code - tests/test_settlement_monitor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Module_sem
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Module sem]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module sem]]

## Top bridge nodes
- [[Settlement Monitor (auto-settle via METARNWS)]] - degree 6, connects to 3 communities
- [[Safe IO (atomic writes + CRC integrity)]] - degree 3, connects to 1 community
- [[METAR (same-day observation lock-in)]] - degree 2, connects to 1 community