---
source_file: "tests/test_cleanup_data_dir.py"
type: "rationale"
community: "Module: tests"
location: "L107"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# An ephemeral file modified within 2 days must not be deleted.

## Connections
- [[.test_fresh_ephemeral_file_is_kept()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests