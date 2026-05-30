---
source_file: "tests/test_cloud_backup.py"
type: "rationale"
community: "Module: tests"
location: "L60"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# backup_to_s3 calls boto3.client('s3').upload_file with correct args.

## Connections
- [[test_backup_to_s3_calls_upload()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests