---
source_file: "tests/test_cleanup_data_dir.py"
type: "code"
community: "Community 4"
location: "L1"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_4
---

# test_cleanup_data_dir.py

## Connections
- [[P0-15 cleanup_data_dir must not delete permanent calibration files.]] - `rationale_for` [EXTRACTED]
- [[TestCleanupDataDir]] - `contains` [EXTRACTED]
- [[_patched_cleanup()]] - `contains` [EXTRACTED]
- [[_write_stale()]] - `contains` [EXTRACTED]
- [[atomic_write_json_with_history()]] - `imports` [EXTRACTED]
- [[data_dir()]] - `contains` [EXTRACTED]
- [[pathlib]] - `imports_from` [EXTRACTED]
- [[pytest_1]] - `imports` [EXTRACTED]
- [[safe_io.py]] - `calls` [EXTRACTED]
- [[test_atomic_write_json_with_history_keeps_previous_versions()]] - `contains` [EXTRACTED]
- [[test_prune_old_analysis_attempts_removes_stale_rows()]] - `contains` [EXTRACTED]
- [[test_vacuum_database_runs_without_error()]] - `contains` [EXTRACTED]
- [[time]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_4