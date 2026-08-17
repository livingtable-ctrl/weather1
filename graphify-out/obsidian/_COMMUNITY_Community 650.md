---
type: community
cohesion: 0.50
members: 4
---

# Community 650

**Cohesion:** 0.50 - moderately connected
**Members:** 4 nodes

## Members
- [[dot-test_distinct_cooldown_keys_both_send()]] - code - tests/test_notify.py
- [[dot-test_second_call_within_cooldown_sends_nothing()]] - code - tests/test_notify.py
- [[Integration-level send_system_alert() itself (not just the helper) respects…]] - rationale - tests/test_notify.py
- [[TestSendSystemAlertUsesPersistedCooldown]] - code - tests/test_notify.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_650
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestSendSystemAlertUsesPersistedCooldown]] - degree 4, connects to 1 community