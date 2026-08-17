---
type: community
cohesion: 0.20
members: 10
---

# Community 384

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_check_config_integrity_detects_change()]] - code - tests/test_p9_p10.py
- [[dot-test_check_config_integrity_first_run()]] - code - tests/test_p9_p10.py
- [[dot-test_check_config_integrity_no_change()]] - code - tests/test_p9_p10.py
- [[dot-test_config_hash_is_deterministic()]] - code - tests/test_p9_p10.py
- [[dot-test_get_config_fingerprint_returns_dict()]] - code - tests/test_p9_p10.py
- [[First run no previous hash → changed=False, writes hash file.]] - rationale - tests/test_p9_p10.py
- [[Running twice with same config → changed=False.]] - rationale - tests/test_p9_p10.py
- [[Same config should always produce the same hash.]] - rationale - tests/test_p9_p10.py
- [[TestConfigIntegrity]] - code - tests/test_p9_p10.py
- [[Writing a different hash file → changed=True.]] - rationale - tests/test_p9_p10.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_384
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 54]]
- 1 edge to [[_COMMUNITY_Community 426]]

## Top bridge nodes
- [[TestConfigIntegrity]] - degree 6, connects to 1 community
- [[dot-test_get_config_fingerprint_returns_dict()]] - degree 2, connects to 1 community