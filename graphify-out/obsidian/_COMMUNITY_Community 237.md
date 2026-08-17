---
type: community
cohesion: 0.19
members: 15
---

# Community 237

**Cohesion:** 0.19 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-_mock_session_get()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_empty_obs_time_returns_none()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_missing_obs_time_returns_none()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_null_obstime_is_rejected_not_fabricated()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_result_obs_time_is_utc_aware()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_unparseable_obs_time_returns_none()]] - code - tests/test_phase2_batch_j.py
- [[dot-test_valid_obs_time_returns_result()]] - code - tests/test_phase2_batch_j.py
- [[A valid recent obsTime must produce a proper result dict.]] - rationale - tests/test_phase2_batch_j.py
- [[TestMetarFetchNoFabricatedTimestamp]] - code - tests/test_phase2_batch_j.py
- [[When obsTime is empty string, fetch_metar must return None.]] - rationale - tests/test_phase2_batch_j.py
- [[When obsTime is not ISO-parseable, fetch_metar must return None.]] - rationale - tests/test_phase2_batch_j.py
- [[When obsTime key is absent, fetch_metar must return None.]] - rationale - tests/test_phase2_batch_j.py
- [[fetch_metar must not fabricate a timestamp — None obsTime → return None.]] - rationale - tests/test_phase2_batch_j.py
- [[fetch_metar must return None when obsTime is absent or unparseable.]] - rationale - tests/test_phase2_batch_j.py
- [[obs_time in the result must be timezone-aware.]] - rationale - tests/test_phase2_batch_j.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_237
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 303]]

## Top bridge nodes
- [[TestMetarFetchNoFabricatedTimestamp]] - degree 9, connects to 1 community