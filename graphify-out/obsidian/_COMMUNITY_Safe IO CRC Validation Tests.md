---
type: community
cohesion: 0.04
members: 52
---

# Safe I/O CRC Validation Tests

**Cohesion:** 0.04 - loosely connected
**Members:** 52 nodes

## Members
- [[A PermissionError that never clears must eventually re-raise (not hang forever…]] - rationale - tests/test_safe_io.py
- [[A non-PermissionError failure (e.g. a genuine disk-full OSError) must propagate…]] - rationale - tests/test_safe_io.py
- [[A real emergency copy must be reported with its filename, full path, and an…]] - rationale - tests/test_safe_io.py
- [[Basic correctness the exact text passed in is what's on disk after.]] - rationale - tests/test_safe_io.py
- [[Belt-and-suspenders guard even an explicit fallback_dir that happens to…]] - rationale - tests/test_safe_io.py
- [[Only files matter for operator recovery -- a stray subdirectory (e.g. from a…]] - rationale - tests/test_safe_io.py
- [[Opus-review-caught atomic_write_json()'s own candidate order falls through to…]] - rationale - tests/test_safe_io.py
- [[Opus-review-caught datetime.fromtimestamp() can raise on a corrupt or out-of-…]] - rationale - tests/test_safe_io.py
- [[P1-5 valid 64-char checksum must pass validation.]] - rationale - tests/test_safe_io.py
- [[P1-6 AtomicWriteError must be raised when the primary path is unwritable.]] - rationale - tests/test_safe_io.py
- [[P1-6 emergency copy is written to fallback_dir before raising.]] - rationale - tests/test_safe_io.py
- [[Passing an explicit base_dir (as most tests in this file do, for isolation)…]] - rationale - tests/test_safe_io.py
- [[Path_12]] - code
- [[Regression test for the 2026-07-27 live bug every real caller omits…]] - rationale - tests/test_safe_io.py
- [[Retries through N PermissionErrors, then returns normally once os.replace…]] - rationale - tests/test_safe_io.py
- [[The actual bug class backlog.txt hurricane_climatology. fetch_hurdat2_raw's…]] - rationale - tests/test_safe_io.py
- [[The temp scan is bounded to known data basenames specifically so it doesn't…]] - rationale - tests/test_safe_io.py
- [[When every candidate (primary write AND every emergency candidate) fails, the…]] - rationale - tests/test_safe_io.py
- [[_write_with_crc()]] - code - tests/test_safe_io.py
- [[backlog.txt FORECAST_SIGMA.JSON ATOMIC WRITE CONTENTION multiple threads…]] - rationale - tests/test_safe_io.py
- [[backlog.txt SAFE_IO -- NOTHING MONITORS data.emergency FOR REAL RECOVERY…]] - rationale - tests/test_safe_io.py
- [[backlog.txt climate_indices.py's PDOPNA CACHE AND backtest.py's OWN CACHE…_1]] - rationale - tests/test_safe_io.py
- [[backlog.txt climate_indices.py's PDOPNA CACHE AND backtest.py's OWN CACHE…_2]] - rationale - tests/test_safe_io.py
- [[test_atomic_write_concurrent_threads_same_target_no_collision()]] - code - tests/test_safe_io.py
- [[test_atomic_write_default_fallback_does_not_clobber_original()]] - code - tests/test_safe_io.py
- [[test_atomic_write_emergency_copy_written_on_failure()]] - code - tests/test_safe_io.py
- [[test_atomic_write_error_message_accurate_when_no_emergency_copy_possible()]] - code - tests/test_safe_io.py
- [[test_atomic_write_json_emergency_copy_opt_out_skips_recovery_copy()]] - code - tests/test_safe_io.py
- [[test_atomic_write_raises_when_all_retries_fail()]] - code - tests/test_safe_io.py
- [[test_atomic_write_skips_fallback_dir_that_collides_with_original()]] - code - tests/test_safe_io.py
- [[test_atomic_write_text_concurrent_writers_never_expose_torn_file()]] - code - tests/test_safe_io.py
- [[test_atomic_write_text_emergency_copy_opt_out_skips_recovery_copy()]] - code - tests/test_safe_io.py
- [[test_atomic_write_text_round_trip()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_also_checks_system_temp_fallback()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_empty_when_dir_empty()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_empty_when_dir_missing()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_explicit_base_dir_skips_temp_scan()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_ignores_subdirectories()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_multiple_files_sorted_oldest_first()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_reports_real_files()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_skips_file_with_unparseable_mtime()]] - code - tests/test_safe_io.py
- [[test_check_emergency_copies_temp_scan_ignores_unrelated_files()]] - code - tests/test_safe_io.py
- [[test_load_raises_on_tampered_file()]] - code - tests/test_safe_io.py
- [[test_load_skips_crc_check_when_field_absent()]] - code - tests/test_safe_io.py
- [[test_load_validates_crc_on_good_file()]] - code - tests/test_safe_io.py
- [[test_replace_with_retry_does_not_retry_other_exceptions()]] - code - tests/test_safe_io.py
- [[test_replace_with_retry_reraises_after_deadline()]] - code - tests/test_safe_io.py
- [[test_replace_with_retry_succeeds_after_transient_permission_errors()]] - code - tests/test_safe_io.py
- [[test_safe_io.py]] - code - tests/test_safe_io.py
- [[test_save_then_load_roundtrip()]] - code - tests/test_safe_io.py
- [[test_save_writes_checksum_field()]] - code - tests/test_safe_io.py
- [[test_validate_checksum_passes_on_valid_64char()]] - code - tests/test_safe_io.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Safe_I/O_CRC_Validation_Tests
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 301]]
- 4 edges to [[_COMMUNITY_Community 460]]
- 1 edge to [[_COMMUNITY_Community 145]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Community 610]]
- 1 edge to [[_COMMUNITY_Community 611]]
- 1 edge to [[_COMMUNITY_Community 612]]
- 1 edge to [[_COMMUNITY_Community 613]]
- 1 edge to [[_COMMUNITY_Community 40]]

## Top bridge nodes
- [[test_safe_io.py]] - degree 46, connects to 10 communities