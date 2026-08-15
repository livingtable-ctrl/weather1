---
type: community
cohesion: 0.09
members: 21
---

# Community 132

**Cohesion:** 0.09 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-test_backup_creates_date_subdir()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_backup_prunes_old_dirs()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_restore_default_raises()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_restore_snapshots_existing_data()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_restore_with_confirm_proceeds()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_restore_without_confirm_raises()]] - code - tests/test_phase2_batch_g.py
- [[P2-20 backup_data must write to YYYY-MM-DD subdirectory.]] - rationale - tests/test_phase2_batch_g.py
- [[P2-47 restore_data must require confirm=True to prevent silent overwrites.]] - rationale - tests/test_phase2_batch_g.py
- [[TestCloudBackupTimestamped]] - code - tests/test_phase2_batch_g.py
- [[TestRestoreDataConfirm]] - code - tests/test_phase2_batch_g.py
- [[backup_to_s3 calls boto3.client('s3').upload_file with correct args.]] - rationale - tests/test_cloud_backup.py
- [[backup_to_s3 logs a warning and does not raise when boto3 is not installed.]] - rationale - tests/test_cloud_backup.py
- [[backup_to_s3 with no bucket returns None.]] - rationale - tests/test_cloud_backup.py
- [[restore_data must snapshot current data before overwriting.]] - rationale - tests/test_phase2_batch_g.py
- [[test_backup_to_s3_calls_upload()]] - code - tests/test_cloud_backup.py
- [[test_backup_to_s3_skips_when_boto3_missing()]] - code - tests/test_cloud_backup.py
- [[test_backup_to_s3_skips_without_env()]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup.py]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup_fails_gracefully_on_s3_error()]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup_skipped_without_env()]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup_uploads_to_s3()]] - code - tests/test_cloud_backup.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_132
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 248]]
- 1 edge to [[_COMMUNITY_Community 109]]

## Top bridge nodes
- [[test_cloud_backup.py]] - degree 7, connects to 1 community
- [[TestRestoreDataConfirm]] - degree 6, connects to 1 community
- [[TestCloudBackupTimestamped]] - degree 4, connects to 1 community