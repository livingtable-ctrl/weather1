---
source_file: "tests/test_cron_trade_updates.py"
type: "rationale"
community: "Module: tests"
location: "L28"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# cmd_cron must call auto_settle_paper_trades so paper trades get marked won/lost.

## Connections
- [[.test_cmd_cron_calls_auto_settle_paper_trades()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests