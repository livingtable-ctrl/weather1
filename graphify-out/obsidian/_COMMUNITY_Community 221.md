---
type: community
cohesion: 0.18
members: 16
---

# Community 221

**Cohesion:** 0.18 - loosely connected
**Members:** 16 nodes

## Members
- [[105 Upload backup to S3 if KALSHI_S3_BUCKET is set. Returns None if skipped.]] - rationale - paper.py
- [[dot-test_backup_creates_date_subdir()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_backup_prunes_old_dirs()]] - code - tests/test_phase2_batch_g.py
- [[P2-20 backup_data must write to YYYY-MM-DD subdirectory.]] - rationale - tests/test_phase2_batch_g.py
- [[TestCloudBackupTimestamped]] - code - tests/test_phase2_batch_g.py
- [[backup_to_s3 calls boto3.client('s3').upload_file with correct args.]] - rationale - tests/test_cloud_backup.py
- [[backup_to_s3 logs a warning and does not raise when boto3 is not installed.]] - rationale - tests/test_cloud_backup.py
- [[backup_to_s3 with no bucket returns None.]] - rationale - tests/test_cloud_backup.py
- [[cloud_backup()]] - code - paper.py
- [[test_backup_to_s3_calls_upload()]] - code - tests/test_cloud_backup.py
- [[test_backup_to_s3_skips_when_boto3_missing()]] - code - tests/test_cloud_backup.py
- [[test_backup_to_s3_skips_without_env()]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup.py]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup_fails_gracefully_on_s3_error()]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup_skipped_without_env()]] - code - tests/test_cloud_backup.py
- [[test_cloud_backup_uploads_to_s3()]] - code - tests/test_cloud_backup.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_221
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 518]]
- 1 edge to [[_COMMUNITY_Community 453]]
- 1 edge to [[_COMMUNITY_Community 498]]
- 1 edge to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 6]]

## Top bridge nodes
- [[cloud_backup()]] - degree 16, connects to 5 communities
- [[test_cloud_backup.py]] - degree 11, connects to 2 communities
- [[TestCloudBackupTimestamped]] - degree 4, connects to 1 community