---
type: community
cohesion: 0.11
members: 10
---

# Community 301

**Cohesion:** 0.11 - loosely connected
**Members:** 10 nodes

## Members
- [[P1-5 1-char checksum must raise CorruptionError (was passing 116 of…]] - rationale - tests/test_safe_io.py
- [[P1-5 16-char checksums (prior format) must still pass validation.]] - rationale - tests/test_safe_io.py
- [[P1-5 empty checksum string must raise CorruptionError (was silently passing).]] - rationale - tests/test_safe_io.py
- [[P1-5 no _checksum field means no validation (legacy files without checksum).]] - rationale - tests/test_safe_io.py
- [[P1-5 tampered data must raise CorruptionError.]] - rationale - tests/test_safe_io.py
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
- 5 edges to [[_COMMUNITY_Safe IO CRC Validation Tests]]

## Top bridge nodes
- [[test_validate_checksum_accepts_legacy_16char()]] - degree 2, connects to 1 community
- [[test_validate_checksum_rejects_empty_string()]] - degree 2, connects to 1 community
- [[test_validate_checksum_rejects_mismatch()]] - degree 2, connects to 1 community
- [[test_validate_checksum_rejects_one_char()]] - degree 2, connects to 1 community
- [[test_validate_checksum_skips_when_absent()]] - degree 2, connects to 1 community