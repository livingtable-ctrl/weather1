---
type: community
cohesion: 0.16
members: 14
---

# Community 248

**Cohesion:** 0.16 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_get_still_retried()]] - code - tests/test_idempotency.py
- [[dot-test_post_not_in_allowed_methods()]] - code - tests/test_idempotency.py
- [[Build a requests Session with automatic retry on transient errors.]] - rationale - kalshi_client.py
- [[GET must remain in allowed_methods.]] - rationale - tests/test_idempotency.py
- [[KalshiClient.place_order()_find_order_by_client_id()]] - code - kalshi_client.py
- [[P0-4 place_order idempotency key and POST retry exclusion.]] - rationale - tests/test_idempotency.py
- [[Session]] - code
- [[TestPostRetryExcluded]] - code - tests/test_idempotency.py
- [[Verify HTTPAdapter Retry has exactly total=3, backoff_factor=1, correct…]] - rationale - tests/test_infrastructure.py
- [[_build_session must not include POST in allowed_methods.]] - rationale - tests/test_idempotency.py
- [[_build_session()]] - code - kalshi_client.py
- [[test_idempotency.py]] - code - tests/test_idempotency.py
- [[test_session_has_retry_adapter()]] - code - tests/test_infrastructure.py
- [[test_session_retry_parameters()]] - code - tests/test_infrastructure.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_248
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 7]]
- 2 edges to [[_COMMUNITY_Community 13]]
- 2 edges to [[_COMMUNITY_Community 191]]
- 2 edges to [[_COMMUNITY_Community 229]]
- 2 edges to [[_COMMUNITY_Community 41]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[test_idempotency.py]] - degree 9, connects to 4 communities
- [[_build_session()]] - degree 9, connects to 2 communities
- [[KalshiClient.place_order()_find_order_by_client_id()]] - degree 4, connects to 2 communities
- [[TestPostRetryExcluded]] - degree 4, connects to 1 community
- [[test_session_retry_parameters()]] - degree 3, connects to 1 community