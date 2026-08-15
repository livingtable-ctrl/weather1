---
type: community
cohesion: 0.06
members: 44
---

# Community 42

**Cohesion:** 0.06 - loosely connected
**Members:** 44 nodes

## Members
- [[dot-test_accuracy_halt_blocks_placement()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_both_kelly_keys_missing_defaults_to_zero_and_untiers()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_consistency_skip_blocks_placement_with_no_shadow_log()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_cron_batch_log_receives_rejected_tickers()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_default_threshold_classifies_as_strong()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_divergence_rejected_market_still_reaches_all_results()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_external_halted_reason_blocks_placement()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_kelly_at_floor_boundary_still_clears_gate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_kill_switch_hard_aborts_before_any_scan()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_low_kelly_untiers_an_otherwise_strong_candidate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_manual_override_skips_placement_not_scan()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_missing_ci_kelly_falls_back_to_fee_adjusted_kelly()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_missing_raw_edge_key_defaults_to_clearing_gate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_mkt_prob_rejected_market_still_reaches_all_results()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_negative_net_edge_untiers_a_wide_spread_candidate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_none_adjusted_edge_value_does_not_crash_the_scan()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_none_net_edge_value_does_not_crash_the_scan()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_raw_edge_at_min_edge_boundary_still_clears_gate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_raw_edge_below_min_edge_untiers_an_otherwise_strong_candidate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_raw_edge_wrong_sign_untiers_an_otherwise_strong_candidate()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_reproduces_live_kxhightsea_incident_no_side_magnitude_failure()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_tiered_candidate_clears_validates_own_edge_gates()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_tightened_threshold_demotes_to_med()]] - code - tests/test_trade_cycle_engine.py
- [[Consistency-skip is a stricter halt than the others no shadow logging either…]] - rationale - tests/test_trade_cycle_engine.py
- [[End-to-end cron.py's rebuilt _analysis_batch must include a market the…]] - rationale - tests/test_trade_cycle_engine.py
- [[Every market that reaches a real analysis -- including ones later rejected by…]] - rationale - tests/test_trade_cycle_engine.py
- [[Matches validate()'s own `if edge in opp` guard -- a caller that never…]] - rationale - tests/test_trade_cycle_engine.py
- [[Opus review (2026-08-07) HIGH finding the first version of this fix mirrored…]] - rationale - tests/test_trade_cycle_engine.py
- [[TestAnalysisAttemptDataLoss]] - code - tests/test_trade_cycle_engine.py
- [[TestEffectiveStrongEdgeThreading]] - code - tests/test_trade_cycle_engine.py
- [[TestGateUnification]] - code - tests/test_trade_cycle_engine.py
- [[TestPlacementEdgeGateTierClassification]] - code - tests/test_trade_cycle_engine.py
- [[TestPlacementKellyFloorGateTierClassification]] - code - tests/test_trade_cycle_engine.py
- [[The actual backlog.txt reproduction case recommended_side=no,…]] - rationale - tests/test_trade_cycle_engine.py
- [[The unified gate set must block placement identically for both…]] - rationale - tests/test_trade_cycle_engine.py
- [[_strong_market_analysis()]] - code - tests/test_trade_cycle_engine.py
- [[backlog.txt 'STRONGMED TIER CLASSIFICATION AND FINAL PLACEMENT VALIDATION USE…]] - rationale - tests/test_trade_cycle_engine.py
- [[backlog.txt 'STRONGMED TIER REMAINING VALIDATE() GATES NOT MIRRORED (KELLY…]] - rationale - tests/test_trade_cycle_engine.py
- [[cron.py's Brier-drift-tightened threshold must actually change tier…]] - rationale - tests/test_trade_cycle_engine.py
- [[cron.py's anomaly-detection  black-swan-check-error halt reason, computed…]] - rationale - tests/test_trade_cycle_engine.py
- [[oppadjusted_edge present but None must not raise TypeError from…]] - rationale - tests/test_trade_cycle_engine.py
- [[oppnet_edge present but None (as opposed to simply absent) must not raise…]] - rationale - tests/test_trade_cycle_engine.py
- [[parametrize_2]] - code
- [[validate() rejects strictly-below 0.002, so exactly 0.002 clears.]] - rationale - tests/test_trade_cycle_engine.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_42
SORT file.name ASC
```

## Connections to other communities
- 23 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 7 edges to [[_COMMUNITY_Community 136]]
- 6 edges to [[_COMMUNITY_Community 290]]
- 5 edges to [[_COMMUNITY_Community 266]]
- 4 edges to [[_COMMUNITY_Community 382]]
- 3 edges to [[_COMMUNITY_Community 443]]
- 2 edges to [[_COMMUNITY_Community 556]]
- 1 edge to [[_COMMUNITY_Community 85]]

## Top bridge nodes
- [[_strong_market_analysis()]] - degree 56, connects to 7 communities
- [[dot-test_tiered_candidate_clears_validates_own_edge_gates()]] - degree 4, connects to 2 communities
- [[TestPlacementEdgeGateTierClassification]] - degree 12, connects to 1 community
- [[TestGateUnification]] - degree 9, connects to 1 community
- [[TestPlacementKellyFloorGateTierClassification]] - degree 8, connects to 1 community