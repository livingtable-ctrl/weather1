---
type: community
cohesion: 0.07
members: 41
---

# Community 49

**Cohesion:** 0.07 - loosely connected
**Members:** 41 nodes

## Members
- [[dot-_gate()]] - code - tests/test_trading_gates.py
- [[dot-test_allows_when_all_gates_pass()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_accuracy_halted()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_daily_loss_halted()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_drawdown_halt()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_graduation_not_met()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_kill_switch_active()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_live_trading_env_absent()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_live_trading_not_enabled()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_not_prod()]] - code - tests/test_trading_gates.py
- [[dot-test_blocks_when_streak_paused()]] - code - tests/test_trading_gates.py
- [[dot-test_check_or_raise_raises_when_blocked()]] - code - tests/test_trading_gates.py
- [[dot-test_client_base_url_wins_over_stale_kalshi_env_demo_direction()]] - code - tests/test_trading_gates.py
- [[dot-test_client_base_url_wins_over_stale_kalshi_env_prod_direction()]] - code - tests/test_trading_gates.py
- [[dot-test_client_prod_base_url_reaches_full_gate()]] - code - tests/test_trading_gates.py
- [[dot-test_cmd_order_blocked_by_gate()]] - code - tests/test_trading_gates.py
- [[dot-test_cmd_order_gates_client_missing_base_url()]] - code - tests/test_trading_gates.py
- [[dot-test_daily_loss_check_receives_the_client()]] - code - tests/test_trading_gates.py
- [[dot-test_micro_live_blocked_by_gate()]] - code - tests/test_trading_gates.py
- [[dot-test_micro_live_gate_ok_uses_the_client_it_is_passed()]] - code - tests/test_trading_gates.py
- [[dot-test_place_live_order_blocked_by_gate()]] - code - tests/test_trading_gates.py
- [[dot-test_quick_paper_buy_gates_client_missing_base_url()]] - code - tests/test_trading_gates.py
- [[dot-test_quick_paper_buy_maker_order_blocked_by_gate()]] - code - tests/test_trading_gates.py
- [[2026-07-09 follow-up the outer guard must REQUIRE the gate for a client it…]] - rationale - tests/test_trading_gates.py
- [[2026-07-09 `import main` inside check() re-executes main.py as a second module…]] - rationale - tests/test_trading_gates.py
- [[2026-07-09 check() previously called is_daily_loss_halted() with no args, so…]] - rationale - tests/test_trading_gates.py
- [[A genuine prod client with everything else passing is allowed — confirms the…]] - rationale - tests/test_trading_gates.py
- [[Gate must block when LIVE_TRADING_ENABLED is not set at all. See…]] - rationale - tests/test_trading_gates.py
- [[LIVE_TRADING_ENABLED must be explicitly 'true' — KALSHI_ENV=prod alone is not…]] - rationale - tests/test_trading_gates.py
- [[Mirror of test_cmd_order_gates_client_missing_base_url for the maker-order…]] - rationale - tests/test_trading_gates.py
- [[Mirror of the above in the safety-critical direction a prod client must still…]] - rationale - tests/test_trading_gates.py
- [[No-client fallback now reads os.getenv(KALSHI_ENV) directly (not `import…]] - rationale - tests/test_trading_gates.py
- [[P0-2 LiveTradingGate must block live orders when graduationsafety gates fail.]] - rationale - tests/test_trading_gates.py
- [[TestLiveTradingGate]] - code - tests/test_trading_gates.py
- [[The kill switch must block every live-order path through this shared gate, not…]] - rationale - tests/test_trading_gates.py
- [[The real call site (order_executor.py1741) passes its own client through —…]] - rationale - tests/test_trading_gates.py
- [[_micro_live_gate_ok() must return False when the live trading gate blocks.]] - rationale - tests/test_trading_gates.py
- [[_place_live_order must return (False, 0.0) when gate blocks.]] - rationale - tests/test_trading_gates.py
- [[_quick_paper_buy's maker-order branch places a REAL order — despite the…]] - rationale - tests/test_trading_gates.py
- [[cmd_order (manual CLI order) must not bypass the live trading gate.]] - rationale - tests/test_trading_gates.py
- [[test_trading_gates.py]] - code - tests/test_trading_gates.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_49
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 17]]
- 3 edges to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 6]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[test_trading_gates.py]] - degree 6, connects to 4 communities
- [[TestLiveTradingGate]] - degree 25, connects to 1 community
- [[dot-_gate()]] - degree 17, connects to 1 community
- [[dot-test_micro_live_blocked_by_gate()]] - degree 3, connects to 1 community
- [[dot-test_micro_live_gate_ok_uses_the_client_it_is_passed()]] - degree 3, connects to 1 community