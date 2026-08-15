---
source_file: "tests/test_safe_io.py"
type: "code"
community: "Safe I/O CRC Validation Tests"
location: "L1"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Safe_I/O_CRC_Validation_Tests
---

# test_safe_io.py

## Connections
- [[AtomicWriteError]] - `imports` [EXTRACTED]
- [[CorruptionError]] - `imports` [EXTRACTED]
- [[Paper Trading Ledger Module]] - `calls` [EXTRACTED]
- [[_replace_with_retry()]] - `calls` [EXTRACTED]
- [[_validate_checksum()]] - `imports` [EXTRACTED]
- [[_validate_crc()]] - `imports` [EXTRACTED]
- [[_write_with_crc()]] - `contains` [EXTRACTED]
- [[atomic_write_json()]] - `calls` [EXTRACTED]
- [[test_atomic_write_concurrent_threads_same_target_no_collision()]] - `contains` [EXTRACTED]
- [[test_atomic_write_default_fallback_does_not_clobber_original()]] - `contains` [EXTRACTED]
- [[test_atomic_write_emergency_copy_written_on_failure()]] - `contains` [EXTRACTED]
- [[test_atomic_write_error_message_accurate_when_no_emergency_copy_possible()]] - `contains` [EXTRACTED]
- [[test_atomic_write_json_emergency_copy_opt_out_skips_recovery_copy()]] - `contains` [EXTRACTED]
- [[test_atomic_write_raises_when_all_retries_fail()]] - `contains` [EXTRACTED]
- [[test_atomic_write_skips_fallback_dir_that_collides_with_original()]] - `contains` [EXTRACTED]
- [[test_atomic_write_text_concurrent_writers_never_expose_torn_file()]] - `contains` [EXTRACTED]
- [[test_atomic_write_text_creates_parent_dirs()]] - `contains` [EXTRACTED]
- [[test_atomic_write_text_emergency_copy_opt_out_skips_recovery_copy()]] - `contains` [EXTRACTED]
- [[test_atomic_write_text_emergency_copy_written_on_failure()]] - `contains` [EXTRACTED]
- [[test_atomic_write_text_round_trip()]] - `contains` [EXTRACTED]
- [[test_atomic_write_text_shares_retry_and_raise_behavior_with_json()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_also_checks_system_temp_fallback()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_default_base_dir_uses_project_root()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_empty_when_dir_empty()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_empty_when_dir_missing()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_explicit_base_dir_skips_temp_scan()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_ignores_subdirectories()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_multiple_files_sorted_oldest_first()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_reports_real_files()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_skips_file_with_unparseable_mtime()]] - `contains` [EXTRACTED]
- [[test_check_emergency_copies_temp_scan_ignores_unrelated_files()]] - `contains` [EXTRACTED]
- [[test_load_raises_on_tampered_file()]] - `contains` [EXTRACTED]
- [[test_load_skips_crc_check_when_field_absent()]] - `contains` [EXTRACTED]
- [[test_load_validates_crc_on_good_file()]] - `contains` [EXTRACTED]
- [[test_replace_with_retry_does_not_retry_other_exceptions()]] - `contains` [EXTRACTED]
- [[test_replace_with_retry_reraises_after_deadline()]] - `contains` [EXTRACTED]
- [[test_replace_with_retry_succeeds_after_transient_permission_errors()]] - `contains` [EXTRACTED]
- [[test_save_then_load_roundtrip()]] - `contains` [EXTRACTED]
- [[test_save_writes_checksum_field()]] - `contains` [EXTRACTED]
- [[test_validate_checksum_accepts_legacy_16char()]] - `contains` [EXTRACTED]
- [[test_validate_checksum_passes_on_valid_64char()]] - `contains` [EXTRACTED]
- [[test_validate_checksum_rejects_empty_string()]] - `contains` [EXTRACTED]
- [[test_validate_checksum_rejects_mismatch()]] - `contains` [EXTRACTED]
- [[test_validate_checksum_rejects_one_char()]] - `contains` [EXTRACTED]
- [[test_validate_checksum_skips_when_absent()]] - `contains` [EXTRACTED]
- [[test_verify_backup_fails_on_corrupt_file()]] - `contains` [EXTRACTED]
- [[test_verify_backup_fails_on_invalid_json()]] - `contains` [EXTRACTED]
- [[test_verify_backup_logs_checksum_on_success()]] - `contains` [EXTRACTED]
- [[test_verify_backup_passes_on_good_file()]] - `contains` [EXTRACTED]
- [[verify_backup()]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Safe_I/O_CRC_Validation_Tests