---
type: community
cohesion: 0.13
members: 21
---

# Community 150

**Cohesion:** 0.13 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-test_climate_files_are_never_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_dot_files_are_never_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_fresh_ephemeral_file_is_kept()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_permanent_file_set_covers_expected_names()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_permanent_files_are_never_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[dot-test_stale_ephemeral_file_is_deleted()]] - code - tests/test_cleanup_data_dir.py
- [[A stale non-permanent JSON file older than 2 days must be removed.]] - rationale - tests/test_cleanup_data_dir.py
- [[An ephemeral file modified within 2 days must not be deleted.]] - rationale - tests/test_cleanup_data_dir.py
- [[Every file in _PERMANENT_DATA_FILES must survive cleanup even if stale.]] - rationale - tests/test_cleanup_data_dir.py
- [[Files starting with '.' must survive cleanup.]] - rationale - tests/test_cleanup_data_dir.py
- [[Files starting with climate_ must survive cleanup.]] - rationale - tests/test_cleanup_data_dir.py
- [[Path_5]] - code
- [[Redirect main.DATA_DIR (via __file__ resolution) to a temp directory.]] - rationale - tests/test_cleanup_data_dir.py
- [[Same logic as main.cleanup_data_dir but using the supplied data_dir.]] - rationale - tests/test_cleanup_data_dir.py
- [[TestCleanupDataDir]] - code - tests/test_cleanup_data_dir.py
- [[Write a JSON file and backdate its mtime by 3 days.]] - rationale - tests/test_cleanup_data_dir.py
- [[_PERMANENT_DATA_FILES must include the key calibration files.]] - rationale - tests/test_cleanup_data_dir.py
- [[_patched_cleanup()]] - code - tests/test_cleanup_data_dir.py
- [[_write_stale()]] - code - tests/test_cleanup_data_dir.py
- [[data_dir()]] - code - tests/test_cleanup_data_dir.py
- [[fixture_3]] - code

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_150
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[_patched_cleanup()]] - degree 9, connects to 1 community
- [[TestCleanupDataDir]] - degree 7, connects to 1 community
- [[_write_stale()]] - degree 7, connects to 1 community
- [[data_dir()]] - degree 4, connects to 1 community