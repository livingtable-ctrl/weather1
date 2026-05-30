---
source_file: "cron.py"
type: "code"
community: "Module: sem"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_sem
---

# Cron Scheduler (main loop orchestrator)

## Connections
- [[.kill_switch flag file]] - `shares_data_with` [EXTRACTED]
- [[Alerts (anomaly + black swan detection)]] - `calls` [EXTRACTED]
- [[Calibration (seasonal + city weights optimizer)]] - `calls` [EXTRACTED]
- [[Cron Integration Test Suite]] - `references` [EXTRACTED]
- [[File-Based Cron Lock (prevents concurrent runs)]] - `implements` [EXTRACTED]
- [[Flask Web Dashboard (SSE + REST API)]] - `calls` [EXTRACTED]
- [[ML Bias Correction (Platt scaling + temperature)]] - `calls` [EXTRACTED]
- [[Main CLI (entry point, commands, cron trigger)]] - `calls` [EXTRACTED]
- [[Monte Carlo Portfolio Simulation]] - `calls` [EXTRACTED]
- [[Order Executor (signal - trade pipeline)]] - `calls` [EXTRACTED]
- [[Phase 3 Regression Test Batches (A-E)]] - `references` [EXTRACTED]
- [[Settlement Monitor (auto-settle via METARNWS)]] - `calls` [EXTRACTED]
- [[Weather Markets (forecast + probability engine)]] - `calls` [EXTRACTED]
- [[strategy_pins.json (ensemble pinning)]] - `shares_data_with` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_sem