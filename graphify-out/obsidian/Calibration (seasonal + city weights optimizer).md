---
source_file: "calibration.py"
type: "code"
community: "Module: sem"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_sem
---

# Calibration (seasonal + city weights optimizer)

## Connections
- [[Cron Scheduler (main loop orchestrator)]] - `calls` [EXTRACTED]
- [[Main CLI (entry point, commands, cron trigger)]] - `calls` [EXTRACTED]
- [[Prediction Tracker (Brier, bias, calibration)]] - `calls` [EXTRACTED]
- [[city_weights.json (per-city calibration)]] - `shares_data_with` [EXTRACTED]
- [[seasonal_weights.json (calibration output)]] - `shares_data_with` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_sem