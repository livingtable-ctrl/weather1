---
type: community
cohesion: 0.40
members: 5
---

# Community 548

**Cohesion:** 0.40 - moderately connected
**Members:** 5 nodes

## Members
- [[dot-test_get_still_retried()]] - code - tests/test_idempotency.py
- [[dot-test_post_not_in_allowed_methods()]] - code - tests/test_idempotency.py
- [[GET must remain in allowed_methods.]] - rationale - tests/test_idempotency.py
- [[TestPostRetryExcluded]] - code - tests/test_idempotency.py
- [[_build_session must not include POST in allowed_methods.]] - rationale - tests/test_idempotency.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_548
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Community 143]]

## Top bridge nodes
- [[TestPostRetryExcluded]] - degree 4, connects to 2 communities
- [[dot-test_get_still_retried()]] - degree 3, connects to 1 community
- [[dot-test_post_not_in_allowed_methods()]] - degree 3, connects to 1 community