---
source_file: "circuit_breaker.py"
type: "code"
community: "Circuit Breaker Fault Tolerance"
location: "L40"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/Circuit_Breaker_Fault_Tolerance
---

# CircuitBreaker

## Connections
- [[.__init__()_2]] - `method` [EXTRACTED]
- [[._load_state()]] - `method` [EXTRACTED]
- [[._save_state()]] - `method` [EXTRACTED]
- [[.execute()]] - `method` [EXTRACTED]
- [[.failure_count()]] - `method` [EXTRACTED]
- [[.is_open()]] - `method` [EXTRACTED]
- [[.record_failure()]] - `method` [EXTRACTED]
- [[.record_success()]] - `method` [EXTRACTED]
- [[.seconds_open()]] - `method` [EXTRACTED]
- [[.seconds_until_retry()]] - `method` [EXTRACTED]
- [[.suppress_probe()]] - `method` [EXTRACTED]
- [[CircuitBreaker_1]] - `uses` [INFERRED]
- [[KalshiClient_1]] - `uses` [INFERRED]
- [[KalshiClient_4]] - `uses` [INFERRED]
- [[Lock]] - `uses` [INFERRED]
- [[Path_3]] - `uses` [INFERRED]
- [[Path_11]] - `uses` [INFERRED]
- [[Response]] - `uses` [INFERRED]
- [[Response_1]] - `uses` [INFERRED]
- [[Session]] - `uses` [INFERRED]
- [[Session_1]] - `uses` [INFERRED]
- [[TestCircuitBreakerBackoff]] - `uses` [INFERRED]
- [[TestCircuitBreakerBasic]] - `uses` [INFERRED]
- [[TestCircuitBreakerBurstWindow]] - `uses` [INFERRED]
- [[TestCircuitBreakerExecute]] - `uses` [INFERRED]
- [[TestCircuitBreakerHalfOpen]] - `uses` [INFERRED]
- [[TestKalshiCircuitBreakerSplit]] - `uses` [INFERRED]
- [[_cb()]] - `calls` [EXTRACTED]
- [[bool_4]] - `uses` [INFERRED]
- [[bool_10]] - `uses` [INFERRED]
- [[bool_24]] - `uses` [INFERRED]
- [[circuit_breaker.py]] - `contains` [EXTRACTED]
- [[climatology.py]] - `imports` [EXTRACTED]
- [[date_2]] - `uses` [INFERRED]
- [[date_4]] - `uses` [INFERRED]
- [[date_7]] - `uses` [INFERRED]
- [[datetime_1]] - `uses` [INFERRED]
- [[float_6]] - `uses` [INFERRED]
- [[float_14]] - `uses` [INFERRED]
- [[float_22]] - `uses` [INFERRED]
- [[float_31]] - `uses` [INFERRED]
- [[int_17]] - `uses` [INFERRED]
- [[int_26]] - `uses` [INFERRED]
- [[kalshi_client.py]] - `imports` [EXTRACTED]
- [[nws.py]] - `imports` [EXTRACTED]
- [[object]] - `uses` [INFERRED]
- [[str_6]] - `uses` [INFERRED]
- [[str_13]] - `uses` [INFERRED]
- [[str_21]] - `uses` [INFERRED]
- [[str_33]] - `uses` [INFERRED]
- [[test_circuit_allows_call_when_closed()]] - `calls` [EXTRACTED]
- [[test_circuit_breaker.py]] - `imports` [EXTRACTED]
- [[test_circuit_opens_after_threshold()]] - `calls` [EXTRACTED]
- [[test_circuit_recovers_after_timeout()]] - `calls` [EXTRACTED]
- [[test_circuit_resets_on_success()]] - `calls` [EXTRACTED]
- [[test_climatology_cb_skips_when_open()]] - `calls` [EXTRACTED]
- [[test_infrastructure.py]] - `imports` [EXTRACTED]
- [[test_nws_cb_records_failure_on_exception()]] - `calls` [EXTRACTED]
- [[test_nws_cb_skips_when_open()]] - `calls` [EXTRACTED]
- [[test_phase3_batch_b.py]] - `imports` [EXTRACTED]
- [[weather_markets.py]] - `imports` [EXTRACTED]

#graphify/code #graphify/INFERRED #community/Circuit_Breaker_Fault_Tolerance