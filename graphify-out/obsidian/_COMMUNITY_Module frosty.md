---
type: community
cohesion: 1.00
members: 2
---

# Module: frosty

**Cohesion:** 1.00 - tightly connected
**Members:** 2 nodes

## Members
- [[Load non-expired entries from disk into the in-memory cache on startup.]] - rationale - weather_markets.py
- [[_load_forecast_disk_cache()]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Module_frosty
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Forecast Analysis Engine]]

## Top bridge nodes
- [[_load_forecast_disk_cache()]] - degree 2, connects to 1 community