---
source_file: "tests/test_phase3_batch_a.py"
type: "rationale"
community: "Module: tests"
location: "L163"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# P3-19: RNG seed must use hashlib.md5, not hash() (which is PYTHONHASHSEED-random

## Connections
- [[TestFetchArchiveTempsDeterministicSeed]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests