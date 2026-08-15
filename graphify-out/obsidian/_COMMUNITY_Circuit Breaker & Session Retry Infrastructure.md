---
type: community
cohesion: 0.04
members: 59
---

# Circuit Breaker & Session Retry Infrastructure

**Cohesion:** 0.04 - loosely connected
**Members:** 59 nodes

## Members
- [[A cache miss fetches from the network, stores the result in _station_cache, and…]] - rationale - tests/test_infrastructure.py
- [[A cached (lat, lon) - station_id lookup must not hit the network.]] - rationale - tests/test_infrastructure.py
- [[A timeout mid-fetch must return whatever partial results were already collected…]] - rationale - tests/test_infrastructure.py
- [[After init_db(), PRAGMA user_version equals _SCHEMA_VERSION.]] - rationale - tests/test_infrastructure.py
- [[Build a requests Session with automatic retry on transient errors.]] - rationale - kalshi_client.py
- [[CircuitBreaker class_1]] - code - circuit_breaker.py
- [[If both primary and tmp writes fail, AtomicWriteError is raised.]] - rationale - tests/test_infrastructure.py
- [[Loading paper trades with a correct checksum does not raise.]] - rationale - tests/test_infrastructure.py
- [[Loading paper trades with a corrupted checksum raises ValueError.]] - rationale - tests/test_infrastructure.py
- [[Migrations applied incrementally when user_version starts at 0.]] - rationale - tests/test_infrastructure.py
- [[P1-6 primary path failure raises AtomicWriteError (emergency copy written to…]] - rationale - tests/test_infrastructure.py
- [[Path_22]] - code
- [[Regression if NWS ever returns a nullempty stationIdentifier, it must not be…]] - rationale - tests/test_infrastructure.py
- [[Regression the real data.nws_station_cache.json file on disk was written by…]] - rationale - tests/test_infrastructure.py
- [[Saved paper trades JSON contains a '_checksum' key with full 64-char hex…]] - rationale - tests/test_infrastructure.py
- [[Session]] - code
- [[Verify HTTPAdapter Retry has exactly total=3, backoff_factor=1, correct…]] - rationale - tests/test_infrastructure.py
- [[Verify get_weather_markets doesn't crash and runs in reasonable time.]] - rationale - tests/test_infrastructure.py
- [[_build_session()]] - code - kalshi_client.py
- [[alerts.py write function raises RuntimeError if disk write fails twice.]] - rationale - tests/test_infrastructure.py
- [[climatology.py_2]] - code - climatology.py
- [[execution_log.py append_entry propagates OSError when the file cannot be…]] - rationale - tests/test_infrastructure.py
- [[flash_crash_cb (FlashCrashCB instance)]] - code - circuit_breaker.py
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
- [[test_paper_load_passes_valid_checksum()]] - code - tests/test_infrastructure.py
- [[test_paper_load_raises_on_checksum_mismatch()]] - code - tests/test_infrastructure.py
- [[test_paper_save_embeds_sha256_checksum()]] - code - tests/test_infrastructure.py
- [[test_pragma_migrations_incremental()]] - code - tests/test_infrastructure.py
- [[test_pragma_user_version_set_after_init()]] - code - tests/test_infrastructure.py
- [[test_session_has_retry_adapter()]] - code - tests/test_infrastructure.py
- [[test_session_retry_parameters()]] - code - tests/test_infrastructure.py
- [[test_station_cache_loads_pre_migration_flat_format()]] - code - tests/test_infrastructure.py
- [[test_verify_db_backup_counts_rows()]] - code - tests/test_infrastructure.py
- [[test_verify_db_backup_raises_on_empty()]] - code - tests/test_infrastructure.py
- [[verify_db_backup logs 'backup verified' with path and row count.]] - rationale - tests/test_infrastructure.py
- [[verify_db_backup returns 0 when predictions table is empty.]] - rationale - tests/test_infrastructure.py
- [[verify_db_backup returns row count  0 for a valid predictions.db copy.]] - rationale - tests/test_infrastructure.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Circuit_Breaker__Session_Retry_Infrastructure
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Community 44]]
- 5 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 4 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 2 edges to [[_COMMUNITY_Community 351]]
- 2 edges to [[_COMMUNITY_Community 548]]
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 1 edge to [[_COMMUNITY_Community 143]]
- 1 edge to [[_COMMUNITY_Community 227]]
- 1 edge to [[_COMMUNITY_Community 501]]
- 1 edge to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 1 edge to [[_COMMUNITY_Community 145]]
- 1 edge to [[_COMMUNITY_Community 180]]
- 1 edge to [[_COMMUNITY_Community 244]]
- 1 edge to [[_COMMUNITY_Community 248]]
- 1 edge to [[_COMMUNITY_Community 36]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 130]]
- 1 edge to [[_COMMUNITY_Community 96]]

## Top bridge nodes
- [[test_infrastructure.py]] - degree 51, connects to 13 communities
- [[_build_session()]] - degree 9, connects to 3 communities
- [[CircuitBreaker class_1]] - degree 5, connects to 2 communities
- [[flash_crash_cb (FlashCrashCB instance)]] - degree 3, connects to 2 communities
- [[test_atomic_write_creates_file()]] - degree 3, connects to 1 community