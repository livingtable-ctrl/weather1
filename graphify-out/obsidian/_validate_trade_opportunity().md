---
source_file: "order_executor.py"
type: "code"
community: "Module: tests"
location: "L514"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# _validate_trade_opportunity()

## Connections
- [[Pre-execution validation gate for auto-placed trades (P1.1+P1.2).     Returns (]] - `rationale_for` [EXTRACTED]
- [[_auto_place_trades()]] - `calls` [EXTRACTED]
- [[bool_18]] - `references` [EXTRACTED]
- [[check_system_health()]] - `calls` [EXTRACTED]
- [[get_cached_mid_price()]] - `calls` [EXTRACTED]
- [[get_min_edge_for_confidence()]] - `calls` [EXTRACTED]
- [[main.py]] - `imports` [EXTRACTED]
- [[order_executor.py]] - `contains` [EXTRACTED]
- [[str_22]] - `references` [EXTRACTED]
- [[test_validate_accepts_good_opportunity()]] - `calls` [INFERRED]
- [[test_validate_low_spread_tier_rejects_edge_below_threshold()]] - `calls` [INFERRED]
- [[test_validate_missing_ensemble_spread_uses_flat_threshold()]] - `calls` [INFERRED]
- [[test_validate_no_fetched_at_accepted()]] - `calls` [INFERRED]
- [[test_validate_rejects_missing_ticker()]] - `calls` [INFERRED]
- [[test_validate_rejects_negative_edge()]] - `calls` [INFERRED]
- [[test_validate_rejects_stale_data()]] - `calls` [INFERRED]
- [[test_validate_rejects_zero_edge()]] - `calls` [INFERRED]
- [[test_validate_rejects_zero_kelly()]] - `calls` [INFERRED]

#graphify/code #graphify/EXTRACTED #community/Module_tests