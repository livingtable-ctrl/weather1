---
type: community
cohesion: 0.22
members: 9
---

# Community 400

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-setup_method()_31]] - code - tests/test_p1_remaining.py
- [[dot-teardown_method()_23]] - code - tests/test_p1_remaining.py
- [[dot-test_returns_empty_string_when_not_halted()]] - code - tests/test_p1_remaining.py
- [[dot-test_returns_sprt_reason_when_degraded()]] - code - tests/test_p1_remaining.py
- [[dot-test_returns_string_when_win_rate_low()]] - code - tests/test_p1_remaining.py
- [[TestGetAccuracyHaltReason]] - code - tests/test_p1_remaining.py
- [[get_accuracy_halt_reason returns '' when win rate is healthy.]] - rationale - tests/test_p1_remaining.py
- [[get_accuracy_halt_reason returns SPRT info when SPRT signals degradation.]] - rationale - tests/test_p1_remaining.py
- [[get_accuracy_halt_reason returns non-empty string when rolling win rate is low.]] - rationale - tests/test_p1_remaining.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_400
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 1 edge to [[_COMMUNITY_Community 96]]

## Top bridge nodes
- [[TestGetAccuracyHaltReason]] - degree 8, connects to 2 communities