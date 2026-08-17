---
source_file: "order_executor.py"
type: "code"
community: "Community 3"
location: "L1331"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_3
---

# _check_live_position_exits()

## Connections
- [[dot-test_healthy_position_is_left_alone()]] - `calls` [EXTRACTED]
- [[dot-test_no_open_positions_is_a_no_op()]] - `calls` [EXTRACTED]
- [[dot-test_stop_loss_and_breakeven_are_mutually_exclusive_same_cycle()]] - `calls` [EXTRACTED]
- [[dot-test_stop_loss_breach_triggers_immediate_exit()]] - `calls` [EXTRACTED]
- [[dot-test_stop_loss_fires_on_rest_fallback_integer_cents_book()]] - `calls` [EXTRACTED]
- [[dot-test_two_positions_on_same_ticker_both_get_exited()]] - `calls` [EXTRACTED]
- [[dot-test_two_positions_same_ticker_only_one_individually_breaches_both_exit()]] - `calls` [EXTRACTED]
- [[LivePositionStore]] - `calls` [EXTRACTED]
- [[Protect open live positions with stop-loss and breakeven-stop checks, reusing…]] - `rationale_for` [EXTRACTED]
- [[_cmd_cron_body()]] - `calls` [EXTRACTED]
- [[_current_forecast_cycle()]] - `calls` [EXTRACTED]
- [[_get_current_book()]] - `calls` [EXTRACTED]
- [[check_breakeven_stops()]] - `calls` [EXTRACTED]
- [[check_stop_losses()]] - `calls` [EXTRACTED]
- [[cmd_watch()]] - `calls` [EXTRACTED]
- [[coalesce_market_price()]] - `calls` [EXTRACTED]
- [[cron.py]] - `imports` [EXTRACTED]
- [[liquidation_price()]] - `calls` [EXTRACTED]
- [[main.py]] - `imports` [EXTRACTED]
- [[order_executor.py]] - `contains` [EXTRACTED]
- [[test_live_execution.py]] - `imports` [EXTRACTED]
- [[update_peak_profits()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_3