---
source_file: "order_executor.py"
type: "code"
community: "Community 67"
location: "L891"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_67
---

# _reprice_or_cancel_pending_orders()

## Connections
- [[dot-test_amend_failure_leaves_old_row_pending_not_amended()]] - `calls` [EXTRACTED]
- [[dot-test_amend_success_logs_new_row_and_marks_old_row_amended()]] - `calls` [EXTRACTED]
- [[dot-test_amend_that_crosses_the_book_is_logged_as_filled()]] - `calls` [EXTRACTED]
- [[dot-test_empty_liquid_opps_is_a_noop()]] - `calls` [EXTRACTED]
- [[dot-test_order_younger_than_blanket_gate_is_untouched()]] - `calls` [EXTRACTED]
- [[dot-test_price_moved_reprices_as_new_maker_order()]] - `calls` [EXTRACTED]
- [[dot-test_price_unchanged_leaves_order_resting()]] - `calls` [EXTRACTED]
- [[dot-test_rested_past_blanket_gate_but_not_taker_gate_reprices_not_crosses()]] - `calls` [EXTRACTED]
- [[dot-test_strong_edge_and_rested_crosses_as_taker()]] - `calls` [EXTRACTED]
- [[dot-test_ticker_not_in_scan_leaves_order_untouched()]] - `calls` [EXTRACTED]
- [[dot-test_validation_failure_cancels_without_replacing()]] - `calls` [EXTRACTED]
- [[Reprice-or-cancel resting live orders based on this cycle's fresh market…]] - `rationale_for` [EXTRACTED]
- [[_amend_live_order()]] - `calls` [EXTRACTED]
- [[_cancel_and_verify_safe_to_replace()]] - `calls` [EXTRACTED]
- [[_clears_taker_fee()]] - `calls` [EXTRACTED]
- [[_current_forecast_cycle()]] - `calls` [EXTRACTED]
- [[_finalize_cancel()]] - `calls` [EXTRACTED]
- [[_get_current_book()]] - `calls` [EXTRACTED]
- [[_midpoint_price()]] - `calls` [EXTRACTED]
- [[_replace_live_order()]] - `calls` [EXTRACTED]
- [[_validate_trade_opportunity()]] - `calls` [EXTRACTED]
- [[cmd_watch()]] - `calls` [EXTRACTED]
- [[coalesce_market_price()]] - `calls` [EXTRACTED]
- [[get_recent_orders()]] - `calls` [EXTRACTED]
- [[main.py]] - `imports` [EXTRACTED]
- [[order_executor.py]] - `contains` [EXTRACTED]
- [[test_live_execution.py]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_67