---
source_file: "paper.py"
type: "code"
community: "Community 132"
location: "L469"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_132
---

# cloud_backup()

## Connections
- [[105 Upload backup to S3 if KALSHI_S3_BUCKET is set. Returns None if skipped.]] - `rationale_for` [EXTRACTED]
- [[dot-test_backup_creates_date_subdir()]] - `indirect_call` [INFERRED]
- [[dot-test_backup_prunes_old_dirs()]] - `indirect_call` [INFERRED]
- [[dot-test_restore_snapshots_existing_data()]] - `indirect_call` [INFERRED]
- [[dot-test_restore_with_confirm_proceeds()]] - `indirect_call` [INFERRED]
- [[Path_12]] - `calls` [EXTRACTED]
- [[auto_backup()]] - `calls` [EXTRACTED]
- [[main.py]] - `imports` [EXTRACTED]
- [[paper.py]] - `contains` [EXTRACTED]
- [[test_backup_to_s3_calls_upload()]] - `indirect_call` [INFERRED]
- [[test_backup_to_s3_skips_when_boto3_missing()]] - `indirect_call` [INFERRED]
- [[test_backup_to_s3_skips_without_env()]] - `indirect_call` [INFERRED]
- [[test_cloud_backup.py]] - `imports` [EXTRACTED]
- [[test_cloud_backup_fails_gracefully_on_s3_error()]] - `calls` [EXTRACTED]
- [[test_cloud_backup_skipped_without_env()]] - `calls` [EXTRACTED]
- [[test_cloud_backup_uploads_to_s3()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_132