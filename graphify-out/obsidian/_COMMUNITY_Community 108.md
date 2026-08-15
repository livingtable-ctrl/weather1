---
type: community
cohesion: 0.11
members: 26
---

# Community 108

**Cohesion:** 0.11 - loosely connected
**Members:** 26 nodes

## Members
- [[dot-test_concurrent_position_cap_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_daily_loss_halted_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_daily_spend_cap_reached_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_demo_env_uses_demo_base_url()]] - code - tests/test_risk_control.py
- [[dot-test_drawdown_halt_default_is_20pct()]] - code - tests/test_risk_control.py
- [[dot-test_paper_mode_never_calls_place_live_order()]] - code - tests/test_risk_control.py
- [[dot-test_paused_drawdown_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_per_trade_overage_skips_trade()]] - code - tests/test_risk_control.py
- [[dot-test_prod_env_uses_prod_base_url()]] - code - tests/test_risk_control.py
- [[A single trade whose cost would breach MAX_DAILY_SPEND must be skipped.]] - rationale - tests/test_risk_control.py
- [[DRAWDOWN_HALT_PCT default must be 0.20, not 0.50.]] - rationale - tests/test_risk_control.py
- [[Guards in _auto_place_trades must block execution and return 0.]] - rationale - tests/test_risk_control.py
- [[P2 Risk Control verification tests. No production code is modified — all tests…]] - rationale - tests/test_risk_control.py
- [[P2-B is_paused_drawdown=True must block all auto-trades and return 0.]] - rationale - tests/test_risk_control.py
- [[P2-B when open trade count = MAX_CONCURRENT_POSITIONS, no new trades.]] - rationale - tests/test_risk_control.py
- [[Patch all paper guard functions imported inside _auto_place_trades.]] - rationale - tests/test_risk_control.py
- [[Return a minimal valid opportunity dict accepted by _auto_place_trades.]] - rationale - tests/test_risk_control.py
- [[Sanity check KALSHI_ENV=prod must give the production URL.]] - rationale - tests/test_risk_control.py
- [[TestAutoPlaceTradeGuards]] - code - tests/test_risk_control.py
- [[TestDrawdownHaltDefault]] - code - tests/test_risk_control.py
- [[TestPaperLiveSeparation]] - code - tests/test_risk_control.py
- [[When KALSHI_ENV=demo the MARKET_BASE_URL must point to demo.kalshi.co.]] - rationale - tests/test_risk_control.py
- [[_auto_place_trades(live=False) must never call _place_live_order.]] - rationale - tests/test_risk_control.py
- [[_make_opp()_2]] - code - tests/test_risk_control.py
- [[_patch_paper_guards()]] - code - tests/test_risk_control.py
- [[test_risk_control.py]] - code - tests/test_risk_control.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_108
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 40]]
- 2 edges to [[_COMMUNITY_Community 521]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 410]]
- 1 edge to [[_COMMUNITY_Community 435]]
- 1 edge to [[_COMMUNITY_Community 380]]
- 1 edge to [[_COMMUNITY_Community 228]]

## Top bridge nodes
- [[test_risk_control.py]] - degree 16, connects to 8 communities