---
source_file: "tests/test_cloud_backup.py"
type: "code"
community: "Module: tests"
location: "L59"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# test_backup_to_s3_calls_upload()

## Connections
- [[MagicMock]] - `calls` [INFERRED]
- [[backup_to_s3 calls boto3.client('s3').upload_file with correct args.]] - `rationale_for` [EXTRACTED]
- [[test_cloud_backup.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests