---
type: community
cohesion: 0.25
members: 8
---

# Community 435

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_threshold_at_starting_balance_unchanged()]] - code - tests/test_risk_control.py
- [[dot-test_threshold_grows_with_balance()]] - code - tests/test_risk_control.py
- [[dot-test_threshold_never_below_starting_balance()]] - code - tests/test_risk_control.py
- [[If balance somehow drops below STARTING_BALANCE, threshold uses…]] - rationale - tests/test_risk_control.py
- [[TestDailyLossThresholdScalesWithBalance]] - code - tests/test_risk_control.py
- [[When balance equals STARTING_BALANCE, behavior matches the old threshold.]] - rationale - tests/test_risk_control.py
- [[When balance has grown 2x, the halt threshold doubles (3% of 2x = 6% of start).]] - rationale - tests/test_risk_control.py
- [[is_daily_loss_halted uses current balance, not STARTING_BALANCE.]] - rationale - tests/test_risk_control.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_435
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 108]]

## Top bridge nodes
- [[TestDailyLossThresholdScalesWithBalance]] - degree 5, connects to 1 community