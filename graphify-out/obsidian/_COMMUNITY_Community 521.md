---
type: community
cohesion: 0.29
members: 7
---

# Community 521

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_fetch_archive_temps_source_uses_md5()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_md5_seed_is_deterministic()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_two_runs_same_result()]] - code - tests/test_phase3_batch_a.py
- [[P3-19 RNG seed must use hashlib.md5, not hash() (which is PYTHONHASHSEED-…]] - rationale - tests/test_phase3_batch_a.py
- [[TestFetchArchiveTempsDeterministicSeed]] - code - tests/test_phase3_batch_a.py
- [[Two calls with same target_date must produce identical ensemble.]] - rationale - tests/test_phase3_batch_a.py
- [[Two invocations of fetch_archive_temps with same args produce same list.]] - rationale - tests/test_phase3_batch_a.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_521
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[TestFetchArchiveTempsDeterministicSeed]] - degree 6, connects to 2 communities