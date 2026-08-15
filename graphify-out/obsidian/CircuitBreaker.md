---
source_file: "circuit_breaker.py"
type: "code"
community: "Community 44"
location: "L42"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_44
---

# CircuitBreaker

## Connections
- [[dot-__init__()_7]] - `method` [EXTRACTED]
- [[dot-_load_state()]] - `method` [EXTRACTED]
- [[dot-_save_state()]] - `method` [EXTRACTED]
- [[dot-execute()]] - `method` [EXTRACTED]
- [[dot-failure_count()]] - `method` [EXTRACTED]
- [[dot-is_open()]] - `method` [EXTRACTED]
- [[dot-record_failure()]] - `method` [EXTRACTED]
- [[dot-record_success()]] - `method` [EXTRACTED]
- [[dot-seconds_open()]] - `method` [EXTRACTED]
- [[dot-seconds_until_retry()]] - `method` [EXTRACTED]
- [[dot-suppress_probe()]] - `method` [EXTRACTED]
- [[dot-test_backoff_capped_at_24h()]] - `calls` [EXTRACTED]
- [[dot-test_backoff_persists_through_success()]] - `calls` [EXTRACTED]
- [[dot-test_failure_count_property()]] - `calls` [EXTRACTED]
- [[dot-test_first_trip_uses_base_timeout()]] - `calls` [EXTRACTED]
- [[dot-test_half_open_after_timeout()]] - `calls` [EXTRACTED]
- [[dot-test_initially_closed()]] - `calls` [EXTRACTED]
- [[dot-test_multiplier_1_gives_constant_timeout()]] - `calls` [EXTRACTED]
- [[dot-test_opens_after_threshold()]] - `calls` [EXTRACTED]
- [[dot-test_parallel_failures_count_as_one_event()]] - `calls` [EXTRACTED]
- [[dot-test_read_failures_do_not_open_write_cb()]] - `calls` [EXTRACTED]
- [[dot-test_second_trip_doubles_timeout()]] - `calls` [EXTRACTED]
- [[dot-test_seconds_open_increases_when_open()]] - `calls` [EXTRACTED]
- [[dot-test_seconds_open_is_zero_when_closed()]] - `calls` [EXTRACTED]
- [[dot-test_seconds_until_retry_positive_when_open()]] - `calls` [EXTRACTED]
- [[dot-test_seconds_until_retry_zero_when_closed()]] - `calls` [EXTRACTED]
- [[dot-test_sequential_failures_outside_window_each_count()]] - `calls` [EXTRACTED]
- [[dot-test_success_resets_to_closed()]] - `calls` [EXTRACTED]
- [[dot-test_third_trip_quadruples_timeout()]] - `calls` [EXTRACTED]
- [[ForecastCache]] - `semantically_similar_to` [INFERRED]
- [[KalshiClient]] - `uses` [INFERRED]
- [[Phase 3 Batch B Circuit Breaker Tests]] - `imports` [EXTRACTED]
- [[TestCircuitBreakerBackoff]] - `uses` [INFERRED]
- [[TestCircuitBreakerBasic]] - `uses` [INFERRED]
- [[TestCircuitBreakerBurstWindow]] - `uses` [INFERRED]
- [[TestCircuitBreakerExecute]] - `uses` [INFERRED]
- [[TestCircuitBreakerHalfOpen]] - `uses` [INFERRED]
- [[TestKalshiCircuitBreakerSplit]] - `uses` [INFERRED]
- [[_SignalRegistryEntry]] - `uses` [INFERRED]
- [[_cb()]] - `references` [EXTRACTED]
- [[acis_precip.py]] - `imports` [EXTRACTED]
- [[acis_snow.py]] - `imports` [EXTRACTED]
- [[check_black_swan_conditions()]] - `semantically_similar_to` [INFERRED]
- [[circuit_breaker.py]] - `contains` [EXTRACTED]
- [[climatology.py]] - `imports` [EXTRACTED]
- [[kalshi_client._kalshi_cb_read  _kalshi_cb_write  _request_with_retry]] - `calls` [EXTRACTED]
- [[kalshi_client.py]] - `imports` [EXTRACTED]
- [[load_all_sigmas()]] - `semantically_similar_to` [INFERRED]
- [[nws.py]] - `imports` [EXTRACTED]
- [[test_circuit_allows_call_when_closed()]] - `calls` [EXTRACTED]
- [[test_circuit_breaker.py]] - `imports` [EXTRACTED]
- [[test_circuit_opens_after_threshold()]] - `calls` [EXTRACTED]
- [[test_circuit_recovers_after_timeout()]] - `calls` [EXTRACTED]
- [[test_circuit_resets_on_success()]] - `calls` [EXTRACTED]
- [[test_climatology_cb_skips_when_open()]] - `calls` [EXTRACTED]
- [[test_infrastructure.py]] - `imports` [EXTRACTED]
- [[test_nws_cb_records_failure_on_exception()]] - `calls` [EXTRACTED]
- [[test_nws_cb_skips_when_open()]] - `calls` [EXTRACTED]
- [[weather_markets.py]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_44