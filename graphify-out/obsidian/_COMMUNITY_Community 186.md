---
type: community
cohesion: 0.16
members: 18
---

# Community 186

**Cohesion:** 0.16 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-test_concurrent_position_cap_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_daily_loss_halted_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_daily_spend_cap_reached_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_paused_drawdown_returns_zero()]] - code - tests/test_risk_control.py
- [[dot-test_per_trade_overage_skips_trade()]] - code - tests/test_risk_control.py
- [[A single trade whose cost would breach MAX_DAILY_SPEND must be skipped.]] - rationale - tests/test_risk_control.py
- [[Guards in _auto_place_trades must block execution and return 0.]] - rationale - tests/test_risk_control.py
- [[P2-B is_paused_drawdown=True must block all auto-trades and return 0.]] - rationale - tests/test_risk_control.py
- [[P2-B when open trade count = MAX_CONCURRENT_POSITIONS, no new trades.]] - rationale - tests/test_risk_control.py
- [[Patch all paper guard functions imported inside _auto_place_trades.]] - rationale - tests/test_risk_control.py
- [[Redirect execution_log.DB_PATH to a per-test temp file. execution_log.db is a…]] - rationale - tests/conftest.py
- [[Return a minimal valid opportunity dict accepted by _auto_place_trades.]] - rationale - tests/test_risk_control.py
- [[TestAutoPlaceTradeGuards]] - code - tests/test_risk_control.py
- [[_make_opp()_1]] - code - tests/test_risk_control.py
- [[_patch_paper_guards()]] - code - tests/test_risk_control.py
- [[analyze command]] - document - COMMANDS.md
- [[isolate_execution_log()]] - code - tests/conftest.py
- [[watch command]] - document - COMMANDS.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_186
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 18]]
- 2 edges to [[_COMMUNITY_Community 526]]

## Top bridge nodes
- [[_make_opp()_1]] - degree 8, connects to 2 communities
- [[_patch_paper_guards()]] - degree 8, connects to 2 communities
- [[TestAutoPlaceTradeGuards]] - degree 10, connects to 1 community
- [[isolate_execution_log()]] - degree 4, connects to 1 community