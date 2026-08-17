---
type: community
cohesion: 0.20
members: 10
---

# Community 361

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[Fetch PDO and PNA indices from NOAA and save to datapdo_pna.json.]] - rationale - climate_indices.py
- [[Map calendar month (1-12) to meteorological season abbreviation.]] - rationale - climate_indices.py
- [[Parse a NOAA teleconnections CSV (Date=YYYYMM, Value columns). Returns {YYYYMM…]] - rationale - climate_indices.py
- [[Return current PDO and PNA values. Reads from file; fetches if stale or absent.…]] - rationale - climate_indices.py
- [[Return temperature bias correction (degrees F) based on PDOPNA for city and…]] - rationale - climate_indices.py
- [[_fetch_noaa_csv_index()]] - code - climate_indices.py
- [[_month_to_season()]] - code - climate_indices.py
- [[apply_pdo_pna_correction()]] - code - climate_indices.py
- [[fetch_pdo_pna()]] - code - climate_indices.py
- [[get_pdo_pna()]] - code - climate_indices.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_361
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 177]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 38]]
- 1 edge to [[_COMMUNITY_Community 8]]

## Top bridge nodes
- [[apply_pdo_pna_correction()]] - degree 10, connects to 4 communities
- [[fetch_pdo_pna()]] - degree 7, connects to 3 communities
- [[get_pdo_pna()]] - degree 4, connects to 1 community
- [[_fetch_noaa_csv_index()]] - degree 3, connects to 1 community
- [[_month_to_season()]] - degree 3, connects to 1 community