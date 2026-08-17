---
type: community
cohesion: 0.13
members: 27
---

# Community 102

**Cohesion:** 0.13 - loosely connected
**Members:** 27 nodes

## Members
- [[NOTE this gate only protects preload_all()'s own (always force=True)]] - rationale - climatology.py
- [[Cities in city_coords not yet present -- or present with no real computed data,…]] - rationale - climatology.py
- [[Compute per-month forecast sigma (°F) from 30yr climate archive for one city.…]] - rationale - climatology.py
- [[Download 30 years of daily highlow for a city and cache to disk. Auto-…]] - rationale - climatology.py
- [[Fetch and cache historical data for all cities. Refreshes stale caches.]] - rationale - climatology.py
- [[Grade Audit Output climatology.py]] - document - docs/grade_audit/outputs/climatology.py.md
- [[Historical climatology from Open-Meteo archive API. Fetches 30 years of daily…]] - rationale - climatology.py
- [[Path_2]] - code
- [[Probability of the market condition based purely on historical observations.…]] - rationale - climatology.py
- [[Read _SIGMA_CACHE_PATH and return its dict content, or {} on any readparse…]] - rationale - climatology.py
- [[Return True if the cache file is missing or older than CACHE_MAX_AGE seconds.]] - rationale - climatology.py
- [[Return per-city, per-month forecast sigmas computed from 30yr climate archive.…]] - rationale - climatology.py
- [[True if a per-city sigma cache entry has at least one real computed month…]] - rationale - climatology.py
- [[_cache_is_stale()]] - code - climatology.py
- [[_cache_path()]] - code - climatology.py
- [[_climatological_prob_inner()]] - code - climatology.py
- [[_load_sigma_cache_file()]] - code - climatology.py
- [[_sigma_cache_missing_cities()]] - code - climatology.py
- [[_sigma_entry_has_data()]] - code - climatology.py
- [[climatological_prob()]] - code - climatology.py
- [[climatology.py]] - code - climatology.py
- [[compute_sigma_from_climate()]] - code - climatology.py
- [[date_1]] - code
- [[fetch_historical()]] - code - climatology.py
- [[fetch_historical() RF1 Silent API-Failure Swallow]] - document - docs/grade_audit/outputs/climatology.py.md
- [[load_all_sigmas()]] - code - climatology.py
- [[preload_all()]] - code - climatology.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_102
SORT file.name ASC
```

## Connections to other communities
- 11 edges to [[_COMMUNITY_Community 4]]
- 9 edges to [[_COMMUNITY_Community 6]]
- 6 edges to [[_COMMUNITY_Community 5]]
- 5 edges to [[_COMMUNITY_Community 8]]
- 4 edges to [[_COMMUNITY_Community 23]]
- 3 edges to [[_COMMUNITY_Community 9]]
- 3 edges to [[_COMMUNITY_Community 0]]
- 2 edges to [[_COMMUNITY_Community 7]]
- 2 edges to [[_COMMUNITY_Community 69]]
- 2 edges to [[_COMMUNITY_Community 38]]
- 2 edges to [[_COMMUNITY_Community 89]]
- 1 edge to [[_COMMUNITY_Community 1]]

## Top bridge nodes
- [[climatology.py]] - degree 38, connects to 9 communities
- [[load_all_sigmas()]] - degree 15, connects to 5 communities
- [[fetch_historical()]] - degree 12, connects to 3 communities
- [[_climatological_prob_inner()]] - degree 7, connects to 3 communities
- [[preload_all()]] - degree 11, connects to 2 communities