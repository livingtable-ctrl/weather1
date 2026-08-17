---
type: community
cohesion: 0.09
members: 25
---

# Community 117

**Cohesion:** 0.09 - loosely connected
**Members:** 25 nodes

## Members
- [[dot-test_clear_accuracy_halt_override_is_a_safe_no_op_when_nothing_active()]] - code - tests/test_risk_control.py
- [[dot-test_clear_accuracy_halt_override_removes_an_active_one()]] - code - tests/test_risk_control.py
- [[dot-test_corrupt_override_file_falls_through_to_real_check_not_open()]] - code - tests/test_risk_control.py
- [[dot-test_expired_override_no_longer_applies()]] - code - tests/test_risk_control.py
- [[dot-test_negative_minutes_rejected()]] - code - tests/test_risk_control.py
- [[dot-test_override_bypasses_a_real_win_rate_halt()]] - code - tests/test_risk_control.py
- [[dot-test_override_bypasses_an_sprt_halt_too()]] - code - tests/test_risk_control.py
- [[dot-test_override_does_not_affect_other_independent_halts()]] - code - tests/test_risk_control.py
- [[dot-test_status_reports_active_override_with_reason_and_expiry()]] - code - tests/test_risk_control.py
- [[dot-test_status_reports_inactive_for_an_expired_override()]] - code - tests/test_risk_control.py
- [[dot-test_status_reports_inactive_when_nothing_set()]] - code - tests/test_risk_control.py
- [[dot-test_zero_minutes_rejected()]] - code - tests/test_risk_control.py
- [[An accuracy-halt override must not accidentally widen into a general bypass --…]] - rationale - tests/test_risk_control.py
- [[An override with expires_at in the past must NOT bypass the real check -- this…]] - rationale - tests/test_risk_control.py
- [[An unreadablecorrupt override file must fail through to the real (fail-closed)…]] - rationale - tests/test_risk_control.py
- [[TestAccuracyHaltOverride]] - code - tests/test_risk_control.py
- [[The override covers BOTH checks is_accuracy_halted() makes, not just the…]] - rationale - tests/test_risk_control.py
- [[The whole point of the feature an active override must make…]] - rationale - tests/test_risk_control.py
- [[admin accuracy-clear command]] - document - COMMANDS.md
- [[admin accuracy-override command]] - document - COMMANDS.md
- [[admin accuracy-status command]] - document - COMMANDS.md
- [[admin reset-loss command]] - document - COMMANDS.md
- [[minutes=0 would produce an already-expired override that reports success while…]] - rationale - tests/test_risk_control.py
- [[override subcommand group]] - document - COMMANDS.md
- [[override_accuracy_halt()clear_accuracy_halt_override()…]] - rationale - tests/test_risk_control.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_117
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 691]]
- 1 edge to [[_COMMUNITY_Community 401]]
- 1 edge to [[_COMMUNITY_Community 437]]

## Top bridge nodes
- [[TestAccuracyHaltOverride]] - degree 19, connects to 3 communities
- [[admin accuracy-override command]] - degree 6, connects to 1 community