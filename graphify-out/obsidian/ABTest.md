---
source_file: "ab_test.py"
type: "code"
community: "A/B Testing System"
location: "L56"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/A/B_Testing_System
---

# ABTest

## Connections
- [[.__init__()]] - `method` [EXTRACTED]
- [[.pick_variant()]] - `method` [EXTRACTED]
- [[.record_outcome()]] - `method` [EXTRACTED]
- [[.summary()]] - `method` [EXTRACTED]
- [[.test_auto_disable_low_performer()]] - `calls` [EXTRACTED]
- [[.test_get_active_variant_returns_least_traded()]] - `calls` [EXTRACTED]
- [[.test_list_all_summaries_includes_saved_test()]] - `calls` [EXTRACTED]
- [[.test_pick_variant_all_exhausted_falls_back_to_control()]] - `calls` [EXTRACTED]
- [[.test_pick_variant_returns_valid_variant()]] - `calls` [EXTRACTED]
- [[.test_pick_variant_round_robins_to_least_traded()]] - `calls` [EXTRACTED]
- [[.test_record_outcome_increments_trades_and_wins()]] - `calls` [EXTRACTED]
- [[.test_record_outcome_unknown_variant_is_noop()]] - `calls` [EXTRACTED]
- [[.test_summary_has_required_keys()]] - `calls` [EXTRACTED]
- [[CorruptionError]] - `uses` [INFERRED]
- [[Simple bandit-style AB test across strategy parameter variants.     Tracks win]] - `rationale_for` [EXTRACTED]
- [[TestABTest]] - `uses` [INFERRED]
- [[ab_test.py]] - `contains` [EXTRACTED]
- [[auto_settle_paper_trades()]] - `calls` [EXTRACTED]
- [[bool_18]] - `uses` [INFERRED]
- [[bool_19]] - `uses` [INFERRED]
- [[float_23]] - `uses` [INFERRED]
- [[float_24]] - `uses` [INFERRED]
- [[int_18]] - `uses` [INFERRED]
- [[int_19]] - `uses` [INFERRED]
- [[order_executor.py]] - `imports` [EXTRACTED]
- [[paper.py]] - `imports` [EXTRACTED]
- [[settle_paper_trade()]] - `calls` [EXTRACTED]
- [[str_22]] - `uses` [INFERRED]
- [[str_23]] - `uses` [INFERRED]
- [[test_ab_test.py]] - `imports` [EXTRACTED]
- [[test_l4a_get_active_variant_returns_value()]] - `calls` [EXTRACTED]
- [[test_l4a_get_active_variant_value_survives_reload()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/A/B_Testing_System