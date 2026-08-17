---
type: community
cohesion: 0.18
members: 11
---

# Community 338

**Cohesion:** 0.18 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_halted_when_tracker_raises()]] - code - tests/test_risk_control.py
- [[dot-test_halted_when_win_rate_below_threshold()]] - code - tests/test_risk_control.py
- [[dot-test_not_halted_when_sample_too_small()]] - code - tests/test_risk_control.py
- [[dot-test_not_halted_when_win_rate_acceptable()]] - code - tests/test_risk_control.py
- [[2026-07-09 fail closed, not open, on an internal check failure -- a DB read…]] - rationale - tests/test_risk_control.py
- [[Redirect tracker.DB_PATH to a per-test temp DB and initialize the schema.…]] - rationale - tests/conftest.py
- [[TestAccuracyCircuitBreaker]] - code - tests/test_risk_control.py
- [[is_accuracy_halted returns False when fewer than ACCURACY_MIN_SAMPLE trades…]] - rationale - tests/test_risk_control.py
- [[is_accuracy_halted returns False when win rate is 55% over 20 trades.]] - rationale - tests/test_risk_control.py
- [[is_accuracy_halted returns True when win rate is 30% over 20 trades.]] - rationale - tests/test_risk_control.py
- [[isolate_tracker_db()]] - code - tests/conftest.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_338
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 18]]
- 1 edge to [[_COMMUNITY_Community 332]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[isolate_tracker_db()]] - degree 5, connects to 2 communities
- [[TestAccuracyCircuitBreaker]] - degree 6, connects to 1 community