---
source_file: "tests/test_safe_io.py"
type: "code"
community: "Module: tests"
location: "L1"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# test_safe_io.py

## Connections
- [[AtomicWriteError]] - `imports` [EXTRACTED]
- [[CorruptionError]] - `imports` [EXTRACTED]
- [[_validate_checksum()]] - `imports` [EXTRACTED]
- [[_validate_crc()]] - `imports` [EXTRACTED]
- [[_write_with_crc()]] - `contains` [EXTRACTED]
- [[test_atomic_write_emergency_copy_written_on_failure()]] - `contains` [EXTRACTED]
- [[test_atomic_write_raises_when_all_retries_fail()]] - `contains` [EXTRACTED]
- [[test_load_raises_on_tampered_file()]] - `contains` [EXTRACTED]
- [[test_load_skips_crc_check_when_field_absent()]] - `contains` [EXTRACTED]
- [[test_load_validates_crc_on_good_file()]] - `contains` [EXTRACTED]
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

#graphify/code #graphify/EXTRACTED #community/Module_tests