---
type: community
cohesion: 0.02
members: 116
---

# Community 7

**Cohesion:** 0.02 - loosely connected
**Members:** 116 nodes

## Members
- [[dot-__init__()_11]] - code - circuit_breaker.py
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
- [[dot-test_delete_uses_write_cb()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_failure_count_property()]] - code - tests/test_circuit_breaker.py
- [[dot-test_first_trip_uses_base_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_get_uses_read_cb()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_half_open_after_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_initially_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_multiplier_1_gives_constant_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_opens_after_threshold()]] - code - tests/test_circuit_breaker.py
- [[dot-test_parallel_failures_count_as_one_event()]] - code - tests/test_circuit_breaker.py
- [[dot-test_post_uses_write_cb()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_read_and_write_cbs_are_separate_objects()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_read_cb_name_distinct_from_write()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_read_failures_do_not_open_write_cb()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_second_trip_doubles_timeout()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_open_increases_when_open()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_open_is_zero_when_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_until_retry_positive_when_open()]] - code - tests/test_circuit_breaker.py
- [[dot-test_seconds_until_retry_zero_when_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_sequential_failures_outside_window_each_count()]] - code - tests/test_circuit_breaker.py
- [[dot-test_success_resets_to_closed()]] - code - tests/test_circuit_breaker.py
- [[dot-test_third_trip_quadruples_timeout()]] - code - tests/test_circuit_breaker.py
- [[3 simultaneous failures within burst_window must not count as 3 events.…]] - rationale - tests/test_circuit_breaker.py
- [[A cache miss fetches from the network, stores the result in _station_cache, and…]] - rationale - tests/test_infrastructure.py
- [[A cached (lat, lon) - station_id lookup must not hit the network.]] - rationale - tests/test_infrastructure.py
- [[A network error inside get_live_observation increments the CB failure count.]] - rationale - tests/test_infrastructure.py
- [[A timeout mid-fetch must return whatever partial results were already collected…]] - rationale - tests/test_infrastructure.py
- [[After init_db(), PRAGMA user_version equals _SCHEMA_VERSION.]] - rationale - tests/test_infrastructure.py
- [[Any_2]] - code
- [[Backoff accumulates across openclose cycles — success does not reset it.]] - rationale - tests/test_circuit_breaker.py
- [[Call fn(args, kwargs) with automatic circuit protection. Raises…]] - rationale - circuit_breaker.py
- [[CircuitBreaker]] - code - circuit_breaker.py
- [[CircuitBreaker class_1]] - code - circuit_breaker.py
- [[CircuitOpenError]] - code - circuit_breaker.py
- [[DELETE requests go through the write circuit breaker.]] - rationale - tests/test_phase3_batch_b.py
- [[Exception]] - code
- [[Failures spaced further apart than burst_window each increment the counter.]] - rationale - tests/test_circuit_breaker.py
- [[GET requests go through the read circuit breaker.]] - rationale - tests/test_phase3_batch_b.py
- [[If both primary and tmp writes fail, AtomicWriteError is raised.]] - rationale - tests/test_infrastructure.py
- [[Loading paper trades with a correct checksum does not raise.]] - rationale - tests/test_infrastructure.py
- [[Loading paper trades with a corrupted checksum raises ValueError.]] - rationale - tests/test_infrastructure.py
- [[Migrations applied incrementally when user_version starts at 0.]] - rationale - tests/test_infrastructure.py
- [[P1-6 primary path failure raises AtomicWriteError (emergency copy written to…]] - rationale - tests/test_infrastructure.py
- [[P3-5 Read failures must not block write operations.]] - rationale - tests/test_phase3_batch_b.py
- [[POST requests go through the write circuit breaker.]] - rationale - tests/test_phase3_batch_b.py
- [[Path_26]] - code
- [[Prevent automatic probing for the rest of this process lifetime. Call this…]] - rationale - circuit_breaker.py
- [[Raised when a circuit breaker is open (source is down).]] - rationale - circuit_breaker.py
- [[Regression if NWS ever returns a nullempty stationIdentifier, it must not be…]] - rationale - tests/test_infrastructure.py
- [[Regression the real data.nws_station_cache.json file on disk was written by…]] - rationale - tests/test_infrastructure.py
- [[Saved paper trades JSON contains a '_checksum' key with full 64-char hex…]] - rationale - tests/test_infrastructure.py
- [[Seconds remaining before the circuit allows a probe; 0.0 if closed or half-open.]] - rationale - circuit_breaker.py
- [[TestCircuitBreakerBackoff]] - code - tests/test_circuit_breaker.py
- [[TestCircuitBreakerBasic]] - code - tests/test_circuit_breaker.py
- [[TestCircuitBreakerBurstWindow]] - code - tests/test_circuit_breaker.py
- [[TestKalshiCircuitBreakerSplit]] - code - tests/test_phase3_batch_b.py
- [[Tripping the read CB must leave the write CB closed.]] - rationale - tests/test_phase3_batch_b.py
- [[Verify get_weather_markets doesn't crash and runs in reasonable time.]] - rationale - tests/test_infrastructure.py
- [[Wall-clock seconds since the circuit opened; 0.0 if currently closed.]] - rationale - circuit_breaker.py
- [[_save()_load() SHA-256 checksum]] - code - paper.py
- [[alerts.py write function raises RuntimeError if disk write fails twice.]] - rationale - tests/test_infrastructure.py
- [[backoff_multiplier=1.0 (default) never changes recovery_timeout.]] - rationale - tests/test_circuit_breaker.py
- [[climatological_prob returns None immediately when its CB is open.]] - rationale - tests/test_infrastructure.py
- [[climatology.py_1]] - code - climatology.py
- [[execution_log.py append_entry propagates OSError when the file cannot be…]] - rationale - tests/test_infrastructure.py
- [[get_live_observation returns None immediately when its CB is open.]] - rationale - tests/test_infrastructure.py
- [[kalshi_client._kalshi_cb_read  _kalshi_cb_write  _request_with_retry]] - code - kalshi_client.py
- [[log_api_request stores a non-None error string when provided.]] - rationale - tests/test_infrastructure.py
- [[log_api_request works without error arg (backward-compatible).]] - rationale - tests/test_infrastructure.py
- [[test_alerts_write_raises_on_failure()]] - code - tests/test_infrastructure.py
- [[test_atomic_write_creates_file()]] - code - tests/test_infrastructure.py
- [[test_atomic_write_falls_back_to_tmp_on_oserror()]] - code - tests/test_infrastructure.py
- [[test_atomic_write_is_atomic()]] - code - tests/test_infrastructure.py
- [[test_atomic_write_raises_on_double_failure()]] - code - tests/test_infrastructure.py
- [[test_auto_backup_logs_verification()]] - code - tests/test_infrastructure.py
- [[test_circuit_allows_call_when_closed()]] - code - tests/test_infrastructure.py
- [[test_circuit_opens_after_threshold()]] - code - tests/test_infrastructure.py
- [[test_circuit_recovers_after_timeout()]] - code - tests/test_infrastructure.py
- [[test_circuit_resets_on_success()]] - code - tests/test_infrastructure.py
- [[test_climatology_cb_skips_when_open()]] - code - tests/test_infrastructure.py
- [[test_execution_log_write_raises_on_failure()]] - code - tests/test_infrastructure.py
- [[test_get_obs_station_cache_hit_skips_network_call()]] - code - tests/test_infrastructure.py
- [[test_get_obs_station_cache_miss_fetches_and_persists()]] - code - tests/test_infrastructure.py
- [[test_get_obs_station_does_not_cache_a_falsy_station_id()]] - code - tests/test_infrastructure.py
- [[test_infrastructure.py]] - code - tests/test_infrastructure.py
- [[test_log_api_request_accepts_no_error()]] - code - tests/test_infrastructure.py
- [[test_log_api_request_stores_error()]] - code - tests/test_infrastructure.py
- [[test_log_api_request_writes_to_db()]] - code - tests/test_infrastructure.py
- [[test_market_fetch_partial_results_on_timeout()]] - code - tests/test_infrastructure.py
- [[test_market_fetch_uses_threadpool()]] - code - tests/test_infrastructure.py
- [[test_migrations_are_idempotent()]] - code - tests/test_infrastructure.py
- [[test_nws_cb_records_failure_on_exception()]] - code - tests/test_infrastructure.py
- [[test_nws_cb_skips_when_open()]] - code - tests/test_infrastructure.py
- [[test_paper_load_passes_valid_checksum()]] - code - tests/test_infrastructure.py
- [[test_paper_load_raises_on_checksum_mismatch()]] - code - tests/test_infrastructure.py
- [[test_paper_save_embeds_sha256_checksum()]] - code - tests/test_infrastructure.py
- [[test_pragma_migrations_incremental()]] - code - tests/test_infrastructure.py
- [[test_pragma_user_version_set_after_init()]] - code - tests/test_infrastructure.py
- [[test_station_cache_loads_pre_migration_flat_format()]] - code - tests/test_infrastructure.py
- [[test_verify_db_backup_counts_rows()]] - code - tests/test_infrastructure.py
- [[test_verify_db_backup_raises_on_empty()]] - code - tests/test_infrastructure.py
- [[verify_db_backup logs 'backup verified' with path and row count.]] - rationale - tests/test_infrastructure.py
- [[verify_db_backup returns 0 when predictions table is empty.]] - rationale - tests/test_infrastructure.py
- [[verify_db_backup returns row count  0 for a valid predictions.db copy.]] - rationale - tests/test_infrastructure.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_7
SORT file.name ASC
```

## Connections to other communities
- 18 edges to [[_COMMUNITY_Community 4]]
- 7 edges to [[_COMMUNITY_Community 8]]
- 6 edges to [[_COMMUNITY_Community 13]]
- 5 edges to [[_COMMUNITY_Community 139]]
- 4 edges to [[_COMMUNITY_Community 41]]
- 3 edges to [[_COMMUNITY_Community 5]]
- 3 edges to [[_COMMUNITY_Community 6]]
- 3 edges to [[_COMMUNITY_Community 248]]
- 2 edges to [[_COMMUNITY_Community 23]]
- 2 edges to [[_COMMUNITY_Community 102]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 9]]
- 1 edge to [[_COMMUNITY_Community 170]]
- 1 edge to [[_COMMUNITY_Community 64]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 404]]
- 1 edge to [[_COMMUNITY_Community 71]]
- 1 edge to [[_COMMUNITY_Community 30]]

## Top bridge nodes
- [[CircuitBreaker]] - degree 59, connects to 10 communities
- [[test_infrastructure.py]] - degree 55, connects to 9 communities
- [[CircuitOpenError]] - degree 12, connects to 5 communities
- [[CircuitBreaker class_1]] - degree 5, connects to 3 communities
- [[_save()_load() SHA-256 checksum]] - degree 3, connects to 2 communities