---
type: community
cohesion: 0.14
members: 14
---

# Community 252

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_ecmwf_in_extended_ensemble()]] - code - tests/test_ecmwf.py
- [[dot-test_ecmwf_spread_computation()]] - code - tests/test_ecmwf.py
- [[dot-test_fetch_temperature_ecmwf_all_null_treated_as_failure()]] - code - tests/test_ecmwf.py
- [[dot-test_fetch_temperature_ecmwf_negative_caches_failure()]] - code - tests/test_ecmwf.py
- [[dot-test_fetch_temperature_ecmwf_none_on_failure()]] - code - tests/test_ecmwf.py
- [[dot-test_fetch_temperature_ecmwf_returns_float_or_none()]] - code - tests/test_ecmwf.py
- [[dot-test_spread_single_valid_member_returns_zero()]] - code - tests/test_ecmwf.py
- [[A dead model returns HTTP 200 with every hourly value null — this must be…]] - rationale - tests/test_ecmwf.py
- [[A failed fetch must be negative-cached -- a second call within the TTL must not…_1]] - rationale - tests/test_ecmwf.py
- [[ENSEMBLE_MODELS_EXTENDED includes an ecmwf entry.]] - rationale - tests/test_ecmwf.py
- [[TestECMWFAIFS]] - code - tests/test_ecmwf.py
- [[_compute_ensemble_spread returns 0.0 when only one member is valid.]] - rationale - tests/test_ecmwf.py
- [[ensemble_spread computed when ECMWF included raises no error.]] - rationale - tests/test_ecmwf.py
- [[fetch_temperature_ecmwf returns a float or None.]] - rationale - tests/test_ecmwf.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_252
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 9]]
- 3 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestECMWFAIFS]] - degree 9, connects to 2 communities
- [[dot-test_fetch_temperature_ecmwf_returns_float_or_none()]] - degree 4, connects to 2 communities
- [[dot-test_ecmwf_spread_computation()]] - degree 3, connects to 1 community
- [[dot-test_fetch_temperature_ecmwf_all_null_treated_as_failure()]] - degree 3, connects to 1 community
- [[dot-test_fetch_temperature_ecmwf_negative_caches_failure()]] - degree 3, connects to 1 community