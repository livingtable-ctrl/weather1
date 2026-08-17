---
type: community
cohesion: 0.18
members: 11
---

# Community 351

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_drawdown_halt_default_is_20pct()]] - code - tests/test_risk_control.py
- [[dot-test_threshold_at_starting_balance_unchanged()]] - code - tests/test_risk_control.py
- [[dot-test_threshold_grows_with_balance()]] - code - tests/test_risk_control.py
- [[dot-test_threshold_never_below_starting_balance()]] - code - tests/test_risk_control.py
- [[DRAWDOWN_HALT_PCT default must be 0.20, not 0.50.]] - rationale - tests/test_risk_control.py
- [[If balance somehow drops below STARTING_BALANCE, threshold uses…]] - rationale - tests/test_risk_control.py
- [[TestDailyLossThresholdScalesWithBalance]] - code - tests/test_risk_control.py
- [[TestDrawdownHaltDefault]] - code - tests/test_risk_control.py
- [[When balance equals STARTING_BALANCE, behavior matches the old threshold.]] - rationale - tests/test_risk_control.py
- [[When balance has grown 2x, the halt threshold doubles (3% of 2x = 6% of start).]] - rationale - tests/test_risk_control.py
- [[is_daily_loss_halted uses current balance, not STARTING_BALANCE.]] - rationale - tests/test_risk_control.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_351
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestDailyLossThresholdScalesWithBalance]] - degree 6, connects to 1 community
- [[TestDrawdownHaltDefault]] - degree 3, connects to 1 community