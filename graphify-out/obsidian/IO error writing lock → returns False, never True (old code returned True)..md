---
source_file: "tests/test_cron_lock.py"
type: "rationale"
community: "Community 121"
location: "L158"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Community_121
---

# I/O error writing lock → returns False, never True (old code returned True).

## Connections
- [[dot-test_fails_closed_on_io_error()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Community_121