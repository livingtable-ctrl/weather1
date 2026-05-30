---
source_file: "tests/test_cloud_backup.py"
type: "rationale"
community: "Module: tests"
location: "L84"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# backup_to_s3 logs a warning and does not raise when boto3 is not installed.

## Connections
- [[test_backup_to_s3_skips_when_boto3_missing()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests