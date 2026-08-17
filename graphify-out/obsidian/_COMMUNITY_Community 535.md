---
type: community
cohesion: 0.29
members: 7
---

# Community 535

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_200_with_correct_credentials()]] - code - tests/test_web_app.py
- [[dot-test_401_when_password_set_and_no_credentials()]] - code - tests/test_web_app.py
- [[dot-test_no_auth_required_when_password_unset()]] - code - tests/test_web_app.py
- [[Dashboard is open when DASHBOARD_PASSWORD is empty.]] - rationale - tests/test_web_app.py
- [[Dashboard returns 200 with correct Basic Auth credentials.]] - rationale - tests/test_web_app.py
- [[Dashboard returns 401 when password is set and no Authorization header sent.]] - rationale - tests/test_web_app.py
- [[TestDashboardAuth]] - code - tests/test_web_app.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_535
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 115]]

## Top bridge nodes
- [[TestDashboardAuth]] - degree 4, connects to 1 community