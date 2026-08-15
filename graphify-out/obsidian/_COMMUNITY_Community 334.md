---
type: community
cohesion: 0.20
members: 11
---

# Community 334

**Cohesion:** 0.20 - loosely connected
**Members:** 11 nodes

## Members
- [[EDGE_CALC_VERSION must be a non-empty string constant.]] - rationale - tests/test_edge_version.py
- [[Every non-None analyze_trade result must carry an edge_calc_version key.]] - rationale - tests/test_edge_version.py
- [[Minimal enriched dict that produces a non-None analyze_trade result.]] - rationale - tests/test_edge_version.py
- [[Precipitation fast-path returns must also carry edge_calc_version.]] - rationale - tests/test_edge_version.py
- [[Tests for P0.2 — EDGE_CALC_VERSION constant and analyze_trade stamp.]] - rationale - tests/test_edge_version.py
- [[_enriched()_1]] - code - tests/test_edge_version.py
- [[test_analyze_trade_returns_edge_version()]] - code - tests/test_edge_version.py
- [[test_edge_calc_version_is_string()]] - code - tests/test_edge_version.py
- [[test_edge_version.py]] - code - tests/test_edge_version.py
- [[test_precip_fast_path_stamps_edge_version()]] - code - tests/test_edge_version.py
- [[weather_markets.EDGE_CALC_VERSION]] - code - weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_334
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]

## Top bridge nodes
- [[test_edge_version.py]] - degree 8, connects to 1 community
- [[test_analyze_trade_returns_edge_version()]] - degree 4, connects to 1 community
- [[test_precip_fast_path_stamps_edge_version()]] - degree 3, connects to 1 community