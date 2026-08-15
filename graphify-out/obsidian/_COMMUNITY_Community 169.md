---
type: community
cohesion: 0.11
members: 19
---

# Community 169

**Cohesion:** 0.11 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-test_apply_pdo_pna_correction_clamped()]] - code - tests/test_forecasting.py
- [[dot-test_apply_pdo_pna_correction_la_winter()]] - code - tests/test_forecasting.py
- [[dot-test_apply_pdo_pna_correction_unknown_city_zero()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_pdo_pna_parses_csv()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_pdo_pna_write_failure_still_returns_fetched_data()]] - code - tests/test_forecasting.py
- [[dot-test_fetch_pdo_pna_writes_via_atomic_helper()]] - code - tests/test_forecasting.py
- [[dot-test_get_pdo_pna_survives_refresh_write_failure_with_stale_cache()]] - code - tests/test_forecasting.py
- [[dot-test_pdopna_inactive_below_threshold()]] - code - tests/test_forecasting.py
- [[dot-test_pdopna_inactive_without_index_file()]] - code - tests/test_forecasting.py
- [[A cache-write failure (opus-review-caught 2026-08-08 the initial version of…]] - rationale - tests/test_forecasting.py
- [[Cities not in coefficient tables return 0.0.]] - rationale - tests/test_forecasting.py
- [[Extreme index values (PDO=10) are clamped to +-3 degrees F.]] - rationale - tests/test_forecasting.py
- [[LA in DJF with PDO=+1 - approximately +0.8 degrees F correction.]] - rationale - tests/test_forecasting.py
- [[TestPDOPNA]] - code - tests/test_forecasting.py
- [[The user-visible behavior test_fetch_pdo_pna_write_failure_still_…]] - rationale - tests/test_forecasting.py
- [[_pdopna_blend_active returns False when pdo_pna.json is absent.]] - rationale - tests/test_forecasting.py
- [[_pdopna_blend_active returns False when west-coast count  20.]] - rationale - tests/test_forecasting.py
- [[backlog.txt climate_indices.py's PDOPNA CACHE AND backtest.py's OWN CACHE…]] - rationale - tests/test_forecasting.py
- [[fetch_pdo_pna correctly parses NOAA CSV and writes pdo_pna.json.]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_169
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[TestPDOPNA]] - degree 11, connects to 2 communities
- [[dot-test_apply_pdo_pna_correction_clamped()]] - degree 3, connects to 1 community
- [[dot-test_apply_pdo_pna_correction_la_winter()]] - degree 3, connects to 1 community
- [[dot-test_apply_pdo_pna_correction_unknown_city_zero()]] - degree 3, connects to 1 community