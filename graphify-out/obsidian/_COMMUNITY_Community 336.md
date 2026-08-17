---
type: community
cohesion: 0.18
members: 11
---

# Community 336

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[CorruptionError]] - code - paper.py
- [[Path_15]] - code
- [[Raised when a file's CRC32 checksum does not match its content.]] - rationale - paper.py
- [[Validate CRC32 checksum embedded in data dict. No-op if field absent.]] - rationale - paper.py
- [[When every candidate (primary write AND every emergency candidate) fails, the…]] - rationale - tests/test_safe_io.py
- [[_validate_crc()]] - code - paper.py
- [[_write_with_crc()]] - code - tests/test_safe_io.py
- [[test_atomic_write_error_message_accurate_when_no_emergency_copy_possible()]] - code - tests/test_safe_io.py
- [[test_load_raises_on_tampered_file()]] - code - tests/test_safe_io.py
- [[test_load_skips_crc_check_when_field_absent()]] - code - tests/test_safe_io.py
- [[test_load_validates_crc_on_good_file()]] - code - tests/test_safe_io.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_336
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 85]]
- 4 edges to [[_COMMUNITY_Community 1]]
- 2 edges to [[_COMMUNITY_Community 12]]
- 1 edge to [[_COMMUNITY_Community 116]]
- 1 edge to [[_COMMUNITY_Community 304]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 498]]

## Top bridge nodes
- [[CorruptionError]] - degree 11, connects to 7 communities
- [[_validate_crc()]] - degree 9, connects to 3 communities
- [[test_atomic_write_error_message_accurate_when_no_emergency_copy_possible()]] - degree 3, connects to 1 community
- [[test_load_validates_crc_on_good_file()]] - degree 3, connects to 1 community
- [[_write_with_crc()]] - degree 3, connects to 1 community