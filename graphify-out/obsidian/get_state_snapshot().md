---
source_file: "paper.py"
type: "code"
community: "CLI & Preload Pipeline"
location: "L353"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/CLI__Preload_Pipeline
---

# get_state_snapshot()

## Connections
- [[Return a point-in-time snapshot of the paper trading state.     Used for consis]] - `rationale_for` [EXTRACTED]
- [[_cmd_cron_body()]] - `calls` [EXTRACTED]
- [[alerts.py]] - `imports` [EXTRACTED]
- [[cron.py]] - `imports` [EXTRACTED]
- [[get_balance()]] - `calls` [EXTRACTED]
- [[get_open_trades()]] - `calls` [EXTRACTED]
- [[get_peak_balance()]] - `calls` [EXTRACTED]
- [[paper.py]] - `contains` [EXTRACTED]
- [[run_black_swan_check()]] - `calls` [EXTRACTED]
- [[test_get_state_snapshot_returns_required_keys()]] - `calls` [EXTRACTED]
- [[test_state_consistency.py]] - `imports` [EXTRACTED]
- [[test_state_snapshot_balance_matches_get_balance()]] - `calls` [EXTRACTED]
- [[test_state_snapshot_peak_matches_get_peak_balance()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/CLI__Preload_Pipeline