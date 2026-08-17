---
type: community
cohesion: 0.20
members: 10
---

# Community 388

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_build_client_reads_env_at_call_time()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_kalshi_env_function_exists()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_kalshi_env_reads_fresh()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_market_base_url_function_exists()]] - code - tests/test_phase2_batch_l.py
- [[dot-test_market_base_url_switches_with_env()]] - code - tests/test_phase2_batch_l.py
- [[TestKalshiEnvLiveRead]] - code - tests/test_phase2_batch_l.py
- [[_kalshi_env() and _market_base_url() must read os.getenv each call.]] - rationale - tests/test_phase2_batch_l.py
- [[_kalshi_env() reflects env changes without re-import.]] - rationale - tests/test_phase2_batch_l.py
- [[_market_base_url() returns correct URL for current env.]] - rationale - tests/test_phase2_batch_l.py
- [[build_client reads the env fresh at call time, not the stale module constant —…]] - rationale - tests/test_phase2_batch_l.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_388
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 187]]

## Top bridge nodes
- [[TestKalshiEnvLiveRead]] - degree 8, connects to 2 communities