---
source_file: "order_executor.py"
type: "code"
community: "Community 85"
location: "L1895"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/Community_85
---

# _validate_trade_opportunity()

## Connections
- [[dot-test_market_dict_feeds_a_real_price_to_the_breaker()]] - `calls` [INFERRED]
- [[dot-test_no_market_dict_does_not_crash()]] - `calls` [INFERRED]
- [[dot-test_tiered_candidate_clears_validates_own_edge_gates()]] - `calls` [INFERRED]
- [[dot-test_ws_cached_price_is_preferred_over_market_dict()]] - `calls` [INFERRED]
- [[FlashCrashCB]] - `calls` [EXTRACTED]
- [[Pre-execution validation gate for auto-placed trades (P1.1+P1.2). Returns (ok,…]] - `rationale_for` [EXTRACTED]
- [[_auto_place_trades()]] - `calls` [EXTRACTED]
- [[_log_shadow_predictions()]] - `calls` [EXTRACTED]
- [[_reprice_or_cancel_pending_orders()]] - `calls` [EXTRACTED]
- [[_validate_trade_opportunity() (as imported from main)]] - `semantically_similar_to` [INFERRED]
- [[check_system_health()]] - `calls` [EXTRACTED]
- [[get_cached_mid_price()]] - `calls` [EXTRACTED]
- [[get_min_edge_for_confidence()]] - `calls` [EXTRACTED]
- [[get_paper_min_edge()]] - `calls` [EXTRACTED]
- [[order_executor.py]] - `contains` [EXTRACTED]
- [[parse_market_price()]] - `calls` [EXTRACTED]
- [[run_trade_cycle()]] - `conceptually_related_to` [EXTRACTED]
- [[test_drawdown_tiers.py_1]] - `references` [EXTRACTED]
- [[test_validate_accepts_good_opportunity()]] - `calls` [INFERRED]
- [[test_validate_low_spread_tier_rejects_edge_below_threshold()]] - `calls` [INFERRED]
- [[test_validate_missing_ensemble_spread_uses_flat_threshold()]] - `calls` [INFERRED]
- [[test_validate_no_fetched_at_accepted()]] - `calls` [INFERRED]
- [[test_validate_none_edge_value_does_not_crash()]] - `calls` [INFERRED]
- [[test_validate_none_kelly_values_both_missing_rejects_without_crash()]] - `calls` [INFERRED]
- [[test_validate_none_kelly_values_fall_back_then_do_not_crash()]] - `calls` [INFERRED]
- [[test_validate_none_net_edge_value_does_not_crash()]] - `calls` [INFERRED]
- [[test_validate_rejects_missing_ticker()]] - `calls` [INFERRED]
- [[test_validate_rejects_negative_edge()]] - `calls` [INFERRED]
- [[test_validate_rejects_stale_data()]] - `calls` [INFERRED]
- [[test_validate_rejects_zero_edge()]] - `calls` [INFERRED]
- [[test_validate_rejects_zero_kelly()]] - `calls` [INFERRED]

#graphify/code #graphify/INFERRED #community/Community_85