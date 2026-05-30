---
type: community
cohesion: 0.04
members: 66
---

# Circuit Breaker Fault Tolerance

**Cohesion:** 0.04 - loosely connected
**Members:** 66 nodes

## Members
- [[._save_state()]] - code - circuit_breaker.py
- [[.execute()]] - code - circuit_breaker.py
- [[.record_failure()]] - code - circuit_breaker.py
- [[.record_success()]] - code - circuit_breaker.py
- [[.suppress_probe()]] - code - circuit_breaker.py
- [[A network error inside get_live_observation increments the CB failure count.]] - rationale - tests/test_infrastructure.py
- [[After init_db(), PRAGMA user_version equals _SCHEMA_VERSION.]] - rationale - tests/test_infrastructure.py
- [[Any_1]] - code - circuit_breaker.py
- [[Build a dedicated session for Open-Meteo that does NOT auto-retry on 429.]] - rationale - weather_markets.py
- [[Call fn(args, kwargs) with automatic circuit protection.          Raises Ci]] - rationale - circuit_breaker.py
- [[CircuitBreaker]] - code - circuit_breaker.py
- [[If both primary and tmp writes fail, AtomicWriteError is raised.]] - rationale - tests/test_infrastructure.py
- [[KalshiClient_4]] - code - weather_markets.py
- [[Loading paper trades with a correct checksum does not raise.]] - rationale - tests/test_infrastructure.py
- [[Loading paper trades with a corrupted checksum raises ValueError.]] - rationale - tests/test_infrastructure.py
- [[Migrations applied incrementally when user_version starts at 0.]] - rationale - tests/test_infrastructure.py
- [[P1-6 primary path failure raises AtomicWriteError (emergency copy written to tm]] - rationale - tests/test_infrastructure.py
- [[Path_11]] - code - tests/test_infrastructure.py
- [[Prevent automatic probing for the rest of this process lifetime.          Call]] - rationale - circuit_breaker.py
- [[Response_1]] - code - weather_markets.py
- [[Saved paper trades JSON contains a '_checksum' key with full 64-char hex SHA-256]] - rationale - tests/test_infrastructure.py
- [[Session_1]] - code - weather_markets.py
- [[ThreadPool reduces wall-clock time when each analysis has IO latency.]] - rationale - tests/test_infrastructure.py
- [[Verify get_weather_markets doesn't crash and runs in reasonable time.]] - rationale - tests/test_infrastructure.py
- [[_build_om_session()]] - code - weather_markets.py
- [[alerts.py write function raises RuntimeError if disk write fails twice.]] - rationale - tests/test_infrastructure.py
- [[analyze_markets_parallel continues if one market raises an exception.]] - rationale - tests/test_infrastructure.py
- [[analyze_markets_parallel returns one result dict per market.]] - rationale - tests/test_infrastructure.py
- [[climatological_prob returns None immediately when its CB is open.]] - rationale - tests/test_infrastructure.py
- [[execution_log.py append_entry propagates OSError when the file cannot be written]] - rationale - tests/test_infrastructure.py
- [[get_live_observation returns None immediately when its CB is open.]] - rationale - tests/test_infrastructure.py
- [[log_api_request stores a non-None error string when provided.]] - rationale - tests/test_infrastructure.py
- [[log_api_request works without error arg (backward-compatible).]] - rationale - tests/test_infrastructure.py
- [[test_alerts_write_raises_on_failure()]] - code - tests/test_infrastructure.py
- [[test_analyze_markets_parallel_handles_per_market_exception()]] - code - tests/test_infrastructure.py
- [[test_analyze_markets_parallel_is_faster_than_sequential()]] - code - tests/test_infrastructure.py
- [[test_analyze_markets_parallel_returns_results()]] - code - tests/test_infrastructure.py
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
- [[test_infrastructure.py]] - code - tests/test_infrastructure.py
- [[test_log_api_request_accepts_no_error()]] - code - tests/test_infrastructure.py
- [[test_log_api_request_stores_error()]] - code - tests/test_infrastructure.py
- [[test_log_api_request_writes_to_db()]] - code - tests/test_infrastructure.py
- [[test_market_fetch_uses_threadpool()]] - code - tests/test_infrastructure.py
- [[test_migrations_are_idempotent()]] - code - tests/test_infrastructure.py
- [[test_nws_cb_records_failure_on_exception()]] - code - tests/test_infrastructure.py
- [[test_nws_cb_skips_when_open()]] - code - tests/test_infrastructure.py
- [[test_paper_load_passes_valid_checksum()]] - code - tests/test_infrastructure.py
- [[test_paper_load_raises_on_checksum_mismatch()]] - code - tests/test_infrastructure.py
- [[test_paper_save_embeds_sha256_checksum()]] - code - tests/test_infrastructure.py
- [[test_pragma_migrations_incremental()]] - code - tests/test_infrastructure.py
- [[test_pragma_user_version_set_after_init()]] - code - tests/test_infrastructure.py
- [[test_verify_db_backup_counts_rows()]] - code - tests/test_infrastructure.py
- [[test_verify_db_backup_raises_on_empty()]] - code - tests/test_infrastructure.py
- [[verify_db_backup logs 'backup verified' with path and row count.]] - rationale - tests/test_infrastructure.py
- [[verify_db_backup returns 0 when predictions table is empty.]] - rationale - tests/test_infrastructure.py
- [[verify_db_backup returns row count  0 for a valid predictions.db copy.]] - rationale - tests/test_infrastructure.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Circuit_Breaker_Fault_Tolerance
SORT file.name ASC
```

## Connections to other communities
- 11 edges to [[_COMMUNITY_Module frosty]]
- 9 edges to [[_COMMUNITY_Module frosty]]
- 9 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 6 edges to [[_COMMUNITY_Module tests]]
- 6 edges to [[_COMMUNITY_Module frosty]]
- 5 edges to [[_COMMUNITY_Paper Trading & Exits]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 3 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Python Types & Utilities]]
- 1 edge to [[_COMMUNITY_Module tests]]

## Top bridge nodes
- [[CircuitBreaker]] - degree 61, connects to 9 communities
- [[KalshiClient_4]] - degree 4, connects to 3 communities
- [[Response_1]] - degree 4, connects to 3 communities
- [[test_infrastructure.py]] - degree 35, connects to 2 communities
- [[.execute()]] - degree 7, connects to 2 communities