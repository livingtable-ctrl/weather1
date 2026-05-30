---
source_file: "execution_log.py"
type: "code"
community: "Module: sem"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_sem
---

# Execution Log (dedup guard + live P&L)

## Connections
- [[Order Executor (signal - trade pipeline)]] - `calls` [EXTRACTED]
- [[Order Idempotency (client_order_id dedup)]] - `implements` [EXTRACTED]
- [[execution_log.db (dedup guard + P&L)]] - `shares_data_with` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_sem