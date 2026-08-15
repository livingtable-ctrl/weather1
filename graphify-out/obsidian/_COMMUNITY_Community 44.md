---
type: community
cohesion: 0.07
members: 43
---

# Community 44

**Cohesion:** 0.07 - loosely connected
**Members:** 43 nodes

## Members
- [[dot-__init__()_6]] - code - circuit_breaker.py
- [[dot-_load_state()]] - code - circuit_breaker.py
- [[dot-_save_state()]] - code - circuit_breaker.py
- [[dot-execute()]] - code - circuit_breaker.py
- [[dot-failure_count()]] - code - circuit_breaker.py
- [[dot-is_open()]] - code - circuit_breaker.py
- [[dot-record_failure()]] - code - circuit_breaker.py
- [[dot-record_success()]] - code - circuit_breaker.py
- [[dot-seconds_open()]] - code - circuit_breaker.py
- [[dot-seconds_until_retry()]] - code - circuit_breaker.py
- [[dot-suppress_probe()]] - code - circuit_breaker.py
- [[dot-test_backoff_capped_at_24h()]] - code - tests/test_circuit_breaker.py
- [[dot-test_backoff_persists_through_success()]] - code - tests/test_circuit_breaker.py
- [[dot-test_failure_count_property()]] - code - tests/test_circuit_breaker.py
- [[dot-test_first_trip_uses_base_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_half_open_after_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_initially_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_multiplier_1_gives_constant_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_opens_after_threshold()]] - code - tests/test_circuit_breaker.py
- [[dot-test_second_trip_doubles_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_open_increases_when_open()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_open_is_zero_when_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_until_retry_positive_when_open()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_until_retry_zero_when_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_success_resets_to_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_third_trip_quadruples_timeout()]] - code - tests/test_circuit_breaker.py
- [[A network error inside get_live_observation increments the CB failure count.]] - rationale - tests/test_infrastructure.py
- [[Any_2]] - code
- [[Backoff accumulates across openclose cycles — success does not reset it.]] - rationale - tests/test_circuit_breaker.py
- [[Call fn(args, kwargs) with automatic circuit protection. Raises…]] - rationale - circuit_breaker.py
- [[CircuitBreaker]] - code - circuit_breaker.py
- [[Prevent automatic probing for the rest of this process lifetime. Call this…]] - rationale - circuit_breaker.py
- [[Seconds remaining before the circuit allows a probe; 0.0 if closed or half-open.]] - rationale - circuit_breaker.py
- [[TestCircuitBreakerBackoff]] - code - tests/test_circuit_breaker.py
- [[TestCircuitBreakerBasic]] - code - tests/test_circuit_breaker.py
- [[Wall-clock seconds since the circuit opened; 0.0 if currently closed.]] - rationale - circuit_breaker.py
- [[_SignalRegistryEntry]] - code - weather_markets.py
- [[backoff_multiplier=1.0 (default) never changes recovery_timeout.]] - rationale - tests/test_circuit_breaker.py
- [[climatological_prob returns None immediately when its CB is open.]] - rationale - tests/test_infrastructure.py
- [[get_live_observation returns None immediately when its CB is open.]] - rationale - tests/test_infrastructure.py
- [[test_climatology_cb_skips_when_open()]] - code - tests/test_infrastructure.py
- [[test_nws_cb_records_failure_on_exception()]] - code - tests/test_infrastructure.py
- [[test_nws_cb_skips_when_open()]] - code - tests/test_infrastructure.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_44
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 6 edges to [[_COMMUNITY_Community 293]]
- 6 edges to [[_COMMUNITY_Community 84]]
- 2 edges to [[_COMMUNITY_Black Swan Halt State]]
- 2 edges to [[_COMMUNITY_Community 226]]
- 2 edges to [[_COMMUNITY_Community 62]]
- 2 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 2 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 351]]
- 1 edge to [[_COMMUNITY_Community 167]]

## Top bridge nodes
- [[CircuitBreaker]] - degree 59, connects to 12 communities
- [[_SignalRegistryEntry]] - degree 4, connects to 3 communities
- [[TestCircuitBreakerBasic]] - degree 11, connects to 1 community
- [[TestCircuitBreakerBackoff]] - degree 8, connects to 1 community
- [[dot-execute()]] - degree 7, connects to 1 community