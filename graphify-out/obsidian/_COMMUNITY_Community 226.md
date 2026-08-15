---
type: community
cohesion: 0.15
members: 15
---

# Community 226

**Cohesion:** 0.15 - loosely connected
**Members:** 15 nodes

## Members
- [[dot-test_delete_uses_write_cb()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_get_uses_read_cb()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_post_uses_write_cb()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_read_and_write_cbs_are_separate_objects()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_read_cb_name_distinct_from_write()]] - code - tests/test_phase3_batch_b.py
- [[dot-test_read_failures_do_not_open_write_cb()]] - code - tests/test_phase3_batch_b.py
- [[Call _SESSION.request with automatic retry via HTTPAdapter (67). Falls back to…]] - rationale - kalshi_client.py
- [[DELETE requests go through the write circuit breaker.]] - rationale - tests/test_phase3_batch_b.py
- [[GET requests go through the read circuit breaker.]] - rationale - tests/test_phase3_batch_b.py
- [[P3-5 Read failures must not block write operations.]] - rationale - tests/test_phase3_batch_b.py
- [[POST requests go through the write circuit breaker.]] - rationale - tests/test_phase3_batch_b.py
- [[Response]] - code
- [[TestKalshiCircuitBreakerSplit]] - code - tests/test_phase3_batch_b.py
- [[Tripping the read CB must leave the write CB closed.]] - rationale - tests/test_phase3_batch_b.py
- [[_request_with_retry()]] - code - kalshi_client.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_226
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 84]]
- 2 edges to [[_COMMUNITY_Community 44]]
- 2 edges to [[_COMMUNITY_Community 298]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 86]]
- 1 edge to [[_COMMUNITY_Community 36]]
- 1 edge to [[_COMMUNITY_Community 351]]

## Top bridge nodes
- [[_request_with_retry()]] - degree 14, connects to 6 communities
- [[TestKalshiCircuitBreakerSplit]] - degree 10, connects to 2 communities
- [[dot-test_read_failures_do_not_open_write_cb()]] - degree 3, connects to 1 community