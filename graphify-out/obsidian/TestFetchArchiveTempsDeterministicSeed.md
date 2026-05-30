---
source_file: "tests/test_phase3_batch_a.py"
type: "code"
community: "Module: tests"
location: "L162"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# TestFetchArchiveTempsDeterministicSeed

## Connections
- [[.test_fetch_archive_temps_source_uses_md5()]] - `method` [EXTRACTED]
- [[.test_md5_seed_is_deterministic()]] - `method` [EXTRACTED]
- [[.test_two_runs_same_result()]] - `method` [EXTRACTED]
- [[KalshiClient_1]] - `uses` [INFERRED]
- [[P3-19 RNG seed must use hashlib.md5, not hash() (which is PYTHONHASHSEED-random]] - `rationale_for` [EXTRACTED]
- [[test_phase3_batch_a.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests