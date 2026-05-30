---
source_file: "tests/test_risk_control.py"
type: "code"
community: "Module: tests"
location: "L46"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# _patch_paper_guards()

## Connections
- [[.test_concurrent_position_cap_returns_zero()]] - `calls` [EXTRACTED]
- [[.test_daily_loss_halted_returns_zero()]] - `calls` [EXTRACTED]
- [[.test_daily_spend_cap_reached_returns_zero()]] - `calls` [EXTRACTED]
- [[.test_paper_mode_never_calls_place_live_order()]] - `calls` [EXTRACTED]
- [[.test_paused_drawdown_returns_zero()]] - `calls` [EXTRACTED]
- [[.test_per_trade_overage_skips_trade()]] - `calls` [EXTRACTED]
- [[Patch all paper guard functions imported inside _auto_place_trades.]] - `rationale_for` [EXTRACTED]
- [[bool_30]] - `references` [EXTRACTED]
- [[test_risk_control.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests