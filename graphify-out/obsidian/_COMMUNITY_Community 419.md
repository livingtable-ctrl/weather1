---
type: community
cohesion: 0.25
members: 8
---

# Community 419

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_triggered_alert_after_cooldown_elapses_is_rearmed()]] - code - tests/test_alerts.py
- [[dot-test_triggered_alert_with_zero_cooldown_never_rearms()]] - code - tests/test_alerts.py
- [[dot-test_triggered_alert_within_cooldown_is_excluded()]] - code - tests/test_alerts.py
- [[dot-test_untriggered_alert_is_active()]] - code - tests/test_alerts.py
- [[A triggered alert whose cooldown has NOT yet elapsed must not reappear in the…]] - rationale - tests/test_alerts.py
- [[P91 once the cooldown period has passed, the alert must be reset to…]] - rationale - tests/test_alerts.py
- [[TestGetAlertsCooldownRearm]] - code - tests/test_alerts.py
- [[cooldown_minutes=0 means never re-arm — must stay excluded even long after…]] - rationale - tests/test_alerts.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_419
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 94]]

## Top bridge nodes
- [[TestGetAlertsCooldownRearm]] - degree 5, connects to 1 community
- [[dot-test_untriggered_alert_is_active()]] - degree 3, connects to 1 community