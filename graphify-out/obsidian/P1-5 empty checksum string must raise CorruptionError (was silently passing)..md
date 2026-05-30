---
source_file: "tests/test_safe_io.py"
type: "rationale"
community: "Module: tests"
location: "L123"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# P1-5: empty checksum string must raise CorruptionError (was silently passing).

## Connections
- [[test_validate_checksum_rejects_empty_string()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests