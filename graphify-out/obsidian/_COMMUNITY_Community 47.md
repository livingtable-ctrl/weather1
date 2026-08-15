---
type: community
cohesion: 0.07
members: 41
---

# Community 47

**Cohesion:** 0.07 - loosely connected
**Members:** 41 nodes

## Members
- [[dot-test_climate_files_are_never_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_dot_files_are_never_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_fresh_ephemeral_file_is_kept()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_permanent_file_set_covers_expected_names()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_permanent_files_are_never_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_stale_ephemeral_file_is_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[A stale non-permanent JSON file older than 2 days must be removed.]] - rationale - tests/test_cleanup_data_dir.py
- [[An ephemeral file modified within 2 days must not be deleted.]] - rationale - tests/test_cleanup_data_dir.py
- [[Does not expose emergency_copy -- this function exists specifically to preserve…]] - rationale - safe_io.py
- [[Every file in _PERMANENT_DATA_FILES must survive cleanup even if stale.]] - rationale - tests/test_cleanup_data_dir.py
- [[Files starting with '.' must survive cleanup.]] - rationale - tests/test_cleanup_data_dir.py
- [[Files starting with climate_ must survive cleanup.]] - rationale - tests/test_cleanup_data_dir.py
- [[P0-15 cleanup_data_dir must not delete permanent calibration files.]] - rationale - tests/test_cleanup_data_dir.py
- [[Path_21]] - code
- [[Path_22]] - code
- [[Redirect main.DATA_DIR (via __file__ resolution) to a temp directory.]] - rationale - tests/test_cleanup_data_dir.py
- [[Return info about any real recovery copies sitting in the emergency- copy…]] - rationale - safe_io.py
- [[Return the main project root directory, resolving git worktrees correctly. When…]] - rationale - safe_io.py
- [[Same logic as main.cleanup_data_dir but using the supplied data_dir.]] - rationale - tests/test_cleanup_data_dir.py
- [[Shared write-tempfsyncrenameretryemergency-copy core for atomic_write_json…]] - rationale - safe_io.py
- [[TestCleanupDataDir]] - code - tests/test_cleanup_data_dir.py
- [[Write a JSON file and backdate its mtime by 3 days.]] - rationale - tests/test_cleanup_data_dir.py
- [[Write raw text to path atomically -- same write-tempfsyncrename, retry, and…]] - rationale - safe_io.py
- [[_PERMANENT_DATA_FILES must include the key calibration files.]] - rationale - tests/test_cleanup_data_dir.py
- [[_atomic_write_payload()]] - code - safe_io.py
- [[_patched_cleanup()]] - code - tests/test_cleanup_data_dir.py
- [[_replace_with_retry()]] - code - safe_io.py
- [[_write_stale()]] - code - tests/test_cleanup_data_dir.py
- [[atomic_write_json_with_history()]] - code - safe_io.py
- [[atomic_write_text()]] - code - safe_io.py
- [[check_emergency_copies()]] - code - safe_io.py
- [[cron.py emergency-copy monitor call site]] - code - cron.py
- [[data_dir()]] - code - tests/test_cleanup_data_dir.py
- [[fixture_11]] - code
- [[os.replace(src, dst), retrying briefly on PermissionError. Self-caught…]] - rationale - safe_io.py
- [[paper._acquire_file_lock()  msvcrt retry loop]] - code - paper.py
- [[project_root()]] - code - safe_io.py
- [[test_atomic_write_json_with_history_keeps_previous_versions()]] - code - tests/test_cleanup_data_dir.py
- [[test_cleanup_data_dir.py]] - code - tests/test_cleanup_data_dir.py
- [[test_prune_old_analysis_attempts_removes_stale_rows()]] - code - tests/test_cleanup_data_dir.py
- [[test_vacuum_database_runs_without_error()]] - code - tests/test_cleanup_data_dir.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_47
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 5 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 4 edges to [[_COMMUNITY_Community 59]]
- 2 edges to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 2 edges to [[_COMMUNITY_Community 118]]
- 2 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 145]]
- 1 edge to [[_COMMUNITY_Community 385]]
- 1 edge to [[_COMMUNITY_Community 55]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Safe IO CRC Validation Tests]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]

## Top bridge nodes
- [[project_root()]] - degree 12, connects to 7 communities
- [[atomic_write_json_with_history()]] - degree 13, connects to 5 communities
- [[test_cleanup_data_dir.py]] - degree 12, connects to 3 communities
- [[_atomic_write_payload()]] - degree 8, connects to 3 communities
- [[_replace_with_retry()]] - degree 7, connects to 3 communities