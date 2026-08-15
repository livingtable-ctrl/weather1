---
type: community
cohesion: 0.05
members: 63
---

# Trade Cycle Engine & Arbitrage Gates

**Cohesion:** 0.05 - loosely connected
**Members:** 63 nodes

## Members
- [[dot-_healthy_system()]] - code - tests/test_trade_cycle_engine.py
- [[dot-_scan_result_with_violation()]] - code - tests/test_p1_remaining.py
- [[dot-check_or_raise()]] - code - trading_gates.py
- [[dot-test_all_placed_omits_counts()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_arb_trades_blocked_when_accuracy_halted()]] - code - tests/test_p1_remaining.py
- [[dot-test_arb_trades_blocked_when_drawdown_halted()]] - code - tests/test_p1_remaining.py
- [[dot-test_auto_watch_calls_run_trade_cycle_with_liquidity_required()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_banner_suppressed_when_manual_override_halts_cycle()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_candidate_failing_prob_edge_gate_is_not_traded()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_graduation_gate_failure_blocks_watch_shaped_placement()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_market_fetch_exception_still_allows_settlement_to_run()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_med_candidate_placed_with_flat_20_cap()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_mid_scan_kill_switch_stops_analysis()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_none_found_degenerate_case()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_partial_placement_names_both_counts()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_plain_watch_never_calls_run_trade_cycle()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_pre_placement_kill_switch_hard_aborts()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_prints_error_and_reraises_on_failure()]] - code - tests/test_p1_remaining.py
- [[dot-test_prints_failed_count_when_nonzero()]] - code - tests/test_p1_remaining.py
- [[dot-test_prints_filled_count()]] - code - tests/test_p1_remaining.py
- [[dot-test_require_liquid_for_placement_excludes_illiquid_from_tiers()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_strong_candidate_uses_dynamic_kelly_cap()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_transient_kill_switch_does_not_block_later_placement()]] - code - tests/test_trade_cycle_engine.py
- [[dot-test_zero_placed_names_found_count()]] - code - tests/test_trade_cycle_engine.py
- [[A candidate with a large net_edge (would pass a naive MIN_EDGE- style check)…]] - rationale - tests/test_trade_cycle_engine.py
- [[A transient failure in the fetchconsistency-checkprewarmdedup section must…]] - rationale - tests/test_trade_cycle_engine.py
- [[A transient kill-switch activation (touched then cleared before this cycle…]] - rationale - tests/test_trade_cycle_engine.py
- [[Aggregates all pre-trade checks. Call check() before every live order.]] - rationale - trading_gates.py
- [[Build minimal scan state that would trigger arb placement.]] - rationale - tests/test_p1_remaining.py
- [[Direct unit tests of cron._placement_outcome_phrase() -- a pure function, so…]] - rationale - tests/test_trade_cycle_engine.py
- [[Isolate run_trade_cycle() from real data, networks, and alerts -- same…]] - rationale - tests/test_trade_cycle_engine.py
- [[LiveTradingGate]] - code - trading_gates.py
- [[No arb paper orders placed when accuracy halt is active.]] - rationale - tests/test_p1_remaining.py
- [[No arb paper orders placed when drawdown halt is active.]] - rationale - tests/test_p1_remaining.py
- [[Opus review (2026-08-07) four one-directional assertions on trade_cycle's own…]] - rationale - tests/test_trade_cycle_engine.py
- [[TestCmdBackfillPriceHistory]] - code - tests/test_p1_remaining.py
- [[TestCmdWatchIntegration]] - code - tests/test_trade_cycle_engine.py
- [[TestConsistencyArbHaltGuards]] - code - tests/test_p1_remaining.py
- [[TestCronBannerNotMisleadingWhenHalted]] - code - tests/test_trade_cycle_engine.py
- [[TestGraduationGateEndToEnd]] - code - tests/test_trade_cycle_engine.py
- [[TestKillSwitchClearedBetweenMidScanAndPlacement]] - code - tests/test_trade_cycle_engine.py
- [[TestMedTierCapUnification]] - code - tests/test_trade_cycle_engine.py
- [[TestMidScanAndPrePlacementKillSwitch]] - code - tests/test_trade_cycle_engine.py
- [[TestPlacementGateMirrorsValidateOpportunity]] - code - tests/test_trade_cycle_engine.py
- [[TestPlacementOutcomePhrase]] - code - tests/test_trade_cycle_engine.py
- [[TestRealThresholdDrivesTrading]] - code - tests/test_trade_cycle_engine.py
- [[TestScanSetupResilience]] - code - tests/test_trade_cycle_engine.py
- [[TestTierAndCapUnification]] - code - tests/test_trade_cycle_engine.py
- [[Tests for trade_cycle.run_trade_cycle() -- the shared headless engine extracted…]] - rationale - tests/test_trade_cycle_engine.py
- [[The med-tier $20 flat cap -- the other half of 'strongmed tier + dynamic-…]] - rationale - tests/test_trade_cycle_engine.py
- [[The strongmed tier split with dynamic-Kelly-cap vs. $20-flat-cap sizing must…]] - rationale - tests/test_trade_cycle_engine.py
- [[Violation]] - code - consistency.py
- [[_illiquid_strong_market_analysis()]] - code - tests/test_trade_cycle_engine.py
- [[cmd_watch must only invoke run_trade_cycle() when auto_trade=True -- plain…]] - rationale - tests/test_trade_cycle_engine.py
- [[consistency.py (arbitrageconsistency checks)]] - code - consistency.py
- [[cron.py's '!! N STRONG SIGNAL(S) -- placing paper trades !!' console banner…]] - rationale - tests/test_trade_cycle_engine.py
- [[ctx.check_graduation_gate() is new to watch's path -- it never existed pre-…]] - rationale - tests/test_trade_cycle_engine.py
- [[engine_env()]] - code - tests/test_trade_cycle_engine.py
- [[fixture_1]] - code
- [[main.cmd_backfill_price_history -- the `backfill-price-history` CLI command,…]] - rationale - tests/test_p1_remaining.py
- [[test_trade_cycle_engine.py]] - code - tests/test_trade_cycle_engine.py
- [[watch's live-capable path must not attempt to place an illiquid candidate, even…]] - rationale - tests/test_trade_cycle_engine.py
- [[watch's old display-only MIN_EDGE tag must no longer drive trading decisions --…]] - rationale - tests/test_trade_cycle_engine.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Trade_Cycle_Engine__Arbitrage_Gates
SORT file.name ASC
```

## Connections to other communities
- 23 edges to [[_COMMUNITY_Community 42]]
- 9 edges to [[_COMMUNITY_Community 266]]
- 6 edges to [[_COMMUNITY_Community 38]]
- 5 edges to [[_COMMUNITY_Community 136]]
- 4 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 4 edges to [[_COMMUNITY_Community 96]]
- 4 edges to [[_COMMUNITY_Community 368]]
- 3 edges to [[_COMMUNITY_Community 382]]
- 3 edges to [[_COMMUNITY_Community 290]]
- 3 edges to [[_COMMUNITY_Community 443]]
- 3 edges to [[_COMMUNITY_Community 556]]
- 3 edges to [[_COMMUNITY_Community 40]]
- 3 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 32]]
- 2 edges to [[_COMMUNITY_Community 553]]
- 2 edges to [[_COMMUNITY_Community 204]]
- 2 edges to [[_COMMUNITY_Community 472]]
- 2 edges to [[_COMMUNITY_Community 400]]
- 2 edges to [[_COMMUNITY_Community 474]]
- 2 edges to [[_COMMUNITY_Community 473]]
- 2 edges to [[_COMMUNITY_Community 37]]
- 2 edges to [[_COMMUNITY_Black Swan Halt State]]
- 2 edges to [[_COMMUNITY_Community 54]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]

## Top bridge nodes
- [[LiveTradingGate]] - degree 49, connects to 21 communities
- [[Violation]] - degree 45, connects to 19 communities
- [[test_trade_cycle_engine.py]] - degree 36, connects to 10 communities
- [[TestCmdBackfillPriceHistory]] - degree 7, connects to 1 community
- [[TestConsistencyArbHaltGuards]] - degree 6, connects to 1 community