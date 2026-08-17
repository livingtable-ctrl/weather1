---
type: community
cohesion: 0.22
members: 9
---

# Community 429

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_checksum_changes_when_data_changes()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_save_checksum_is_verifiable()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_save_strips_old_crc32_field()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_save_writes_checksum_field()]] - code - tests/test_phase2_batch_b.py
- [[Different data must produce a different checksum.]] - rationale - tests/test_phase2_batch_b.py
- [[P2-14 _save must embed a 64-char SHA-256 _checksum field in every write.]] - rationale - tests/test_phase2_batch_b.py
- [[Round-trip _load after _save must succeed without CorruptionError.]] - rationale - tests/test_phase2_batch_b.py
- [[TestSaveEmbedsSHA256]] - code - tests/test_phase2_batch_b.py
- [[_save must not carry forward the legacy _crc32 field.]] - rationale - tests/test_phase2_batch_b.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_429
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestSaveEmbedsSHA256]] - degree 6, connects to 1 community