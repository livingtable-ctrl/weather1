---
type: community
cohesion: 0.15
members: 18
---

# Community 191

**Cohesion:** 0.15 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-_make_client()_2]] - code - tests/test_idempotency.py
- [[dot-_make_client()_3]] - code - tests/test_idempotency.py
- [[dot-test_client_order_id_differs_across_cycles()]] - code - tests/test_idempotency.py
- [[dot-test_client_order_id_in_request_body()]] - code - tests/test_idempotency.py
- [[dot-test_client_order_id_is_deterministic()]] - code - tests/test_idempotency.py
- [[dot-test_find_order_by_client_id_returns_none_on_api_error()]] - code - tests/test_idempotency.py
- [[dot-test_no_cycle_uses_random_id()]] - code - tests/test_idempotency.py
- [[dot-test_reraises_when_post_fails_and_order_not_found()]] - code - tests/test_idempotency.py
- [[dot-test_returns_existing_order_when_post_fails_but_order_landed()]] - code - tests/test_idempotency.py
- [[Different cycle → different client_order_id.]] - rationale - tests/test_idempotency.py
- [[If _post raises and no matching order exists, the exception must propagate.]] - rationale - tests/test_idempotency.py
- [[If _post raises but the order exists on exchange, return it without re-raising.…]] - rationale - tests/test_idempotency.py
- [[Omitting cycle produces a random (non-deterministic) client_order_id.]] - rationale - tests/test_idempotency.py
- [[Same inputs + same cycle → same client_order_id.]] - rationale - tests/test_idempotency.py
- [[TestClientOrderId]] - code - tests/test_idempotency.py
- [[TestPostFailureDedup]] - code - tests/test_idempotency.py
- [[_find_order_by_client_id must swallow exceptions and return None.]] - rationale - tests/test_idempotency.py
- [[client_order_id must appear in the POST body.]] - rationale - tests/test_idempotency.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_191
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 13]]
- 2 edges to [[_COMMUNITY_Community 248]]

## Top bridge nodes
- [[TestClientOrderId]] - degree 7, connects to 2 communities
- [[TestPostFailureDedup]] - degree 6, connects to 2 communities