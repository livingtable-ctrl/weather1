---
source_file: "settlement_monitor.py"
type: "code"
community: "Module: sem"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_sem
---

# Settlement Monitor (auto-settle via METAR/NWS)

## Connections
- [[Cron Scheduler (main loop orchestrator)]] - `calls` [EXTRACTED]
- [[METAR (same-day observation lock-in)]] - `calls` [EXTRACTED]
- [[NWS (National Weather Service forecast API)]] - `calls` [EXTRACTED]
- [[Paper Trading Engine (Kelly + drawdown + stops)]] - `calls` [EXTRACTED]
- [[Safe IO (atomic writes + CRC integrity)]] - `calls` [EXTRACTED]
- [[Settlement Monitor Test Suite]] - `references` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_sem