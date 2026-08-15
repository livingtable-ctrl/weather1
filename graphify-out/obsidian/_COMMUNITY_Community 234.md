---
type: community
cohesion: 0.13
members: 15
---

# Community 234

**Cohesion:** 0.13 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-test_fetch_temperature_nbm_negative_caches_failure()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_prefers_real_nbm_over_openmeteo()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_returns_float_or_none()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_returns_none_on_error()]] - code - tests/test_nbm.py
- [[dot-test_fetch_temperature_nbm_unknown_station_skips_iem()]] - code - tests/test_nbm.py
- [[dot-test_nbm_in_ensemble_models()]] - code - tests/test_nbm.py
- [[dot-test_openmeteo_fallback_does_not_clobber_iem_value_for_other_var()]] - code - tests/test_nbm.py
- [[2026-07-17 (opus review finding) NBS has per-var coverage gaps at its ~3-day…]] - rationale - tests/test_nbm.py
- [[2026-07-17 fetch_temperature_nbm must try the real-NBM IEM path first and use…]] - rationale - tests/test_nbm.py
- [[A city with no ASOS station mapping must skip straight to Open-Meteo rather…]] - rationale - tests/test_nbm.py
- [[A failed fetch (both IEM and Open-Meteo unavailable) must be negative-cached --…]] - rationale - tests/test_nbm.py
- [[ENSEMBLE_MODELS_EXTENDED includes NBM.]] - rationale - tests/test_nbm.py
- [[Returns None gracefully when both the IEM and Open-Meteo paths fail.]] - rationale - tests/test_nbm.py
- [[TestNBMFetch]] - code - tests/test_nbm.py
- [[fetch_temperature_nbm falls back to Open-Meteo best_match when the real-NBM IEM…]] - rationale - tests/test_nbm.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_234
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 51]]
- 6 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 182]]

## Top bridge nodes
- [[TestNBMFetch]] - degree 9, connects to 2 communities
- [[dot-test_fetch_temperature_nbm_negative_caches_failure()]] - degree 4, connects to 2 communities
- [[dot-test_fetch_temperature_nbm_prefers_real_nbm_over_openmeteo()]] - degree 4, connects to 2 communities
- [[dot-test_fetch_temperature_nbm_returns_float_or_none()]] - degree 4, connects to 2 communities
- [[dot-test_fetch_temperature_nbm_returns_none_on_error()]] - degree 4, connects to 2 communities