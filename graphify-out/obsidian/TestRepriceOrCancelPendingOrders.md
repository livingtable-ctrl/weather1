---
source_file: "tests/test_live_execution.py"
type: "code"
community: "Community 67"
location: "L2141"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_67
---

# TestRepriceOrCancelPendingOrders

## Connections
- [[dot-_seed_pending()]] - `method` [EXTRACTED]
- [[dot-setup_method()_37]] - `method` [EXTRACTED]
- [[dot-teardown_method()_29]] - `method` [EXTRACTED]
- [[dot-test_amend_exchange_success_survives_bookkeeping_failure()]] - `method` [EXTRACTED]
- [[dot-test_amend_failure_leaves_old_row_pending_not_amended()]] - `method` [EXTRACTED]
- [[dot-test_amend_success_logs_new_row_and_marks_old_row_amended()]] - `method` [EXTRACTED]
- [[dot-test_amend_that_crosses_the_book_is_logged_as_filled()]] - `method` [EXTRACTED]
- [[dot-test_empty_liquid_opps_is_a_noop()]] - `method` [EXTRACTED]
- [[dot-test_order_younger_than_blanket_gate_is_untouched()]] - `method` [EXTRACTED]
- [[dot-test_price_moved_reprices_as_new_maker_order()]] - `method` [EXTRACTED]
- [[dot-test_price_unchanged_leaves_order_resting()]] - `method` [EXTRACTED]
- [[dot-test_rested_past_blanket_gate_but_not_taker_gate_reprices_not_crosses()]] - `method` [EXTRACTED]
- [[dot-test_strong_edge_and_rested_crosses_as_taker()]] - `method` [EXTRACTED]
- [[dot-test_ticker_not_in_scan_leaves_order_untouched()]] - `method` [EXTRACTED]
- [[dot-test_validation_failure_cancels_without_replacing()]] - `method` [EXTRACTED]
- [[LivePositionStore]] - `uses` [INFERRED]
- [[Position]] - `uses` [INFERRED]
- [[The core reprice-or-cancel policy cancel on edge decay, cancel+ replace as…]] - `rationale_for` [EXTRACTED]
- [[test_live_execution.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_67