---
type: community
cohesion: 0.17
members: 12
---

# Community 301

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[P1-5 1-char checksum must raise CorruptionError (was passing 116 of…]] - rationale - tests/test_safe_io.py
- [[P1-5 16-char checksums (prior format) must still pass validation.]] - rationale - tests/test_safe_io.py
- [[P1-5 empty checksum string must raise CorruptionError (was silently passing).]] - rationale - tests/test_safe_io.py
- [[P1-5 no _checksum field means no validation (legacy files without checksum).]] - rationale - tests/test_safe_io.py
- [[P1-5 tampered data must raise CorruptionError.]] - rationale - tests/test_safe_io.py
- [[Validate SHA-256 checksum in data dict. Raises CorruptionError on mismatch.…]] - rationale - paper.py
- [[_validate_checksum()]] - code - paper.py
- [[test_validate_checksum_accepts_legacy_16char()]] - code - tests/test_safe_io.py
- [[test_validate_checksum_rejects_empty_string()]] - code - tests/test_safe_io.py
- [[test_validate_checksum_rejects_mismatch()]] - code - tests/test_safe_io.py
- [[test_validate_checksum_rejects_one_char()]] - code - tests/test_safe_io.py
- [[test_validate_checksum_skips_when_absent()]] - code - tests/test_safe_io.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_301
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Safe IO CRC Validation Tests]]
- 4 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 460]]

## Top bridge nodes
- [[_validate_checksum()]] - degree 12, connects to 3 communities
- [[test_validate_checksum_accepts_legacy_16char()]] - degree 3, connects to 1 community
- [[test_validate_checksum_rejects_empty_string()]] - degree 3, connects to 1 community
- [[test_validate_checksum_rejects_mismatch()]] - degree 3, connects to 1 community
- [[test_validate_checksum_rejects_one_char()]] - degree 3, connects to 1 community