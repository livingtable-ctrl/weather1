---
source_file: "tests/test_cron_trade_updates.py"
type: "rationale"
community: "Module: tests"
location: "L52"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# auto_settle_paper_trades must be called in the same cron cycle as sync_outcomes.

## Connections
- [[.test_auto_settle_called_after_sync_outcomes()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests