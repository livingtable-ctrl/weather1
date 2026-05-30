---
source_file: "order_executor.py"
type: "code"
community: "A/B Testing System"
location: "L653"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/A/B_Testing_System
---

# _auto_place_trades()

## Connections
- [[Auto-place paper or live trades for signals not already held.     Called from c]] - `rationale_for` [EXTRACTED]
- [[_current_forecast_cycle()]] - `calls` [EXTRACTED]
- [[_daily_paper_spend()]] - `calls` [EXTRACTED]
- [[_place_live_order()]] - `calls` [EXTRACTED]
- [[_validate_trade_opportunity()]] - `calls` [EXTRACTED]
- [[bool_18]] - `references` [EXTRACTED]
- [[cmd_watch()]] - `calls` [EXTRACTED]
- [[corr_kelly_scale()]] - `calls` [EXTRACTED]
- [[dim()]] - `calls` [EXTRACTED]
- [[drawdown_scaling_factor()]] - `calls` [EXTRACTED]
- [[float_23]] - `references` [EXTRACTED]
- [[get_daily_pnl()]] - `calls` [EXTRACTED]
- [[get_open_trades()]] - `calls` [EXTRACTED]
- [[green()]] - `calls` [EXTRACTED]
- [[int_18]] - `references` [EXTRACTED]
- [[is_daily_loss_halted()]] - `calls` [EXTRACTED]
- [[is_paused_drawdown()]] - `calls` [EXTRACTED]
- [[is_streak_paused()]] - `calls` [EXTRACTED]
- [[kelly_quantity()]] - `calls` [EXTRACTED]
- [[log_analysis_attempt()]] - `calls` [EXTRACTED]
- [[log_live_fill()]] - `calls` [EXTRACTED]
- [[log_prediction()]] - `calls` [EXTRACTED]
- [[main.py]] - `imports` [EXTRACTED]
- [[order_executor.py]] - `contains` [EXTRACTED]
- [[parse_market_price()]] - `calls` [EXTRACTED]
- [[place_paper_order()]] - `calls` [EXTRACTED]
- [[portfolio_kelly_fraction()]] - `calls` [EXTRACTED]
- [[portfolio_var()]] - `calls` [EXTRACTED]
- [[red()]] - `calls` [EXTRACTED]
- [[spread_kelly_multiplier()]] - `calls` [EXTRACTED]
- [[test_auto_place_trades_stops_at_daily_spend_cap()]] - `calls` [INFERRED]
- [[yellow()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/A/B_Testing_System