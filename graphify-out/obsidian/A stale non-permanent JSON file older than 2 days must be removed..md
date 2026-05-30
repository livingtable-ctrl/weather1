---
source_file: "tests/test_cleanup_data_dir.py"
type: "rationale"
community: "Module: tests"
location: "L55"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# A stale non-permanent JSON file older than 2 days must be removed.

## Connections
- [[.test_stale_ephemeral_file_is_deleted()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests