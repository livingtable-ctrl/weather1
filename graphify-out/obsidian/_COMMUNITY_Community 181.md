---
type: community
cohesion: 0.11
members: 19
---

# Community 181

**Cohesion:** 0.11 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-setup_method()_15]] - code - tests/test_phase2_batch_d.py
- [[dot-test_6h_fallback_converts_correctly()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_cache_expires_after_obs_ttl()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_circuit_breaker_open_returns_none()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_exception_triggers_circuit_breaker_failure()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_precip_cache_exported()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_result_cached_within_obs_ttl()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_thread_safe_no_errors()]] - code - tests/test_phase2_batch_d.py
- [[A fetch exception must call record_failure on the circuit breaker.]] - rationale - tests/test_phase2_batch_d.py
- [[After OBS_TTL the function must re-fetch.]] - rationale - tests/test_phase2_batch_d.py
- [[Concurrent calls for different cities must not raise.]] - rationale - tests/test_phase2_batch_d.py
- [[P2-15 get_live_precip_obs must have caching, thread safety, and circuit…]] - rationale - tests/test_phase2_batch_d.py
- [[Reset nws circuit breaker and precip cache to clean state.]] - rationale - tests/test_phase2_batch_d.py
- [[Second call within OBS_TTL must not fetch from network.]] - rationale - tests/test_phase2_batch_d.py
- [[TestGetLivePrecipObs]] - code - tests/test_phase2_batch_d.py
- [[When circuit is open, must return None without fetching.]] - rationale - tests/test_phase2_batch_d.py
- [[_precip_cache must exist as a module-level ForecastCache in nws.]] - rationale - tests/test_phase2_batch_d.py
- [[_reset_nws_cb()]] - code - tests/test_phase2_batch_d.py
- [[precipitationLast6Hours must divide by 6 and convert mm→inches.]] - rationale - tests/test_phase2_batch_d.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_181
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 9]]

## Top bridge nodes
- [[TestGetLivePrecipObs]] - degree 11, connects to 2 communities
- [[_reset_nws_cb()]] - degree 3, connects to 1 community