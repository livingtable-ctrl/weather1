---
type: community
cohesion: 0.33
members: 6
---

# Community 570

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[dot-_make_client()_9]] - code - tests/test_kalshi_client.py
- [[dot-test_same_cycle_produces_the_same_idempotency_key()]] - code - tests/test_kalshi_client.py
- [[dot-test_without_cycle_each_call_gets_a_different_key()]] - code - tests/test_kalshi_client.py
- [[2026-07-09 place_maker_order never forwarded a cycle to place_order, so every…]] - rationale - tests/test_kalshi_client.py
- [[Documents the pre-existing (and still correct for a genuinely distinct manual…]] - rationale - tests/test_kalshi_client.py
- [[TestPlaceMakerOrderIdempotency]] - code - tests/test_kalshi_client.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_570
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 106]]
- 1 edge to [[_COMMUNITY_Community 229]]

## Top bridge nodes
- [[TestPlaceMakerOrderIdempotency]] - degree 5, connects to 1 community
- [[dot-test_without_cycle_each_call_gets_a_different_key()]] - degree 3, connects to 1 community
- [[dot-test_same_cycle_produces_the_same_idempotency_key()]] - degree 2, connects to 1 community