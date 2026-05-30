---
source_file: "paper.py"
type: "code"
community: "Module: tests"
location: "L280"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# cloud_backup()

## Connections
- [[105 Upload backup to S3 if KALSHI_S3_BUCKET is set. Returns None if skipped.]] - `rationale_for` [EXTRACTED]
- [[auto_backup()]] - `calls` [EXTRACTED]
- [[bool_19]] - `references` [EXTRACTED]
- [[main.py]] - `imports` [EXTRACTED]
- [[paper.py]] - `contains` [EXTRACTED]
- [[test_cloud_backup.py]] - `imports` [EXTRACTED]
- [[test_cloud_backup_fails_gracefully_on_s3_error()]] - `calls` [EXTRACTED]
- [[test_cloud_backup_skipped_without_env()]] - `calls` [EXTRACTED]
- [[test_cloud_backup_uploads_to_s3()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests