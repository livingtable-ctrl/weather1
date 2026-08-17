---
type: community
cohesion: 0.25
members: 8
---

# Community 455

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-test_client_supplied_city_is_ignored_server_value_used()]] - code - tests/test_web_app.py
- [[dot-test_exposure_cap_still_enforced_when_body_omits_city_and_date()]] - code - tests/test_web_app.py
- [[A client-supplied citytarget_date that disagrees with the ticker's real city…]] - rationale - tests/test_web_app.py
- [[Deep-review followup apipaper-order used to take citytarget_date straight…]] - rationale - tests/test_web_app.py
- [[Omitting citytarget_date from the request body must NOT bypass the exposure…]] - rationale - tests/test_web_app.py
- [[Strip TRADING_PAUSED from the real .env so a developer's local pause (e.g.…]] - rationale - tests/conftest.py
- [[TestPaperOrderCityDateServerDerived]] - code - tests/test_web_app.py
- [[_clear_trading_paused()]] - code - tests/conftest.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_455
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 18]]
- 1 edge to [[_COMMUNITY_Community 115]]

## Top bridge nodes
- [[TestPaperOrderCityDateServerDerived]] - degree 5, connects to 1 community
- [[_clear_trading_paused()]] - degree 4, connects to 1 community