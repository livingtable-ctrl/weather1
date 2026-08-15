---
source_file: "tests/test_shadow_predictions.py"
type: "code"
community: "Shadow Predictions Auto-Place Trades"
location: "L119"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Shadow_Predictions_Auto-Place_Trades
---

# test_trading_paused_skips_already_open_ticker()

## Connections
- [[A ticker with an existing open position must not get re-logged every cron cycle…]] - `rationale_for` [EXTRACTED]
- [[_auto_place_trades()]] - `calls` [EXTRACTED]
- [[_fetch()]] - `calls` [EXTRACTED]
- [[_make_flat_opp()]] - `calls` [EXTRACTED]
- [[test_shadow_predictions.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Shadow_Predictions_Auto-Place_Trades