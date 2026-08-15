---
type: community
cohesion: 0.12
members: 17
---

# Community 204

**Cohesion:** 0.12 - loosely connected
**Members:** 17 nodes

## Members
- [[dot-_make_cb()]] - code - tests/test_p1_remaining.py
- [[dot-setup_method()_32]] - code - tests/test_p1_remaining.py
- [[dot-teardown_cb()]] - code - tests/test_p1_remaining.py
- [[dot-teardown_method()_24]] - code - tests/test_p1_remaining.py
- [[dot-test_expired_open_state_clears_on_reload()]] - code - tests/test_p1_remaining.py
- [[dot-test_failure_count_persists_across_instances()]] - code - tests/test_p1_remaining.py
- [[dot-test_load_state_blocks_on_save_lock()]] - code - tests/test_p1_remaining.py
- [[dot-test_multiple_breakers_share_one_file()]] - code - tests/test_p1_remaining.py
- [[dot-test_open_state_persists_across_instances()]] - code - tests/test_p1_remaining.py
- [[dot-test_persist_false_does_not_write_state()]] - code - tests/test_p1_remaining.py
- [[An open circuit stays open after process restart.]] - rationale - tests/test_p1_remaining.py
- [[Different circuit breaker names coexist in a single state file.]] - rationale - tests/test_p1_remaining.py
- [[Failure count survives process restart (simulated by creating a new instance).]] - rationale - tests/test_p1_remaining.py
- [[If recovery timeout has elapsed since last open, new instance starts closed.]] - rationale - tests/test_p1_remaining.py
- [[TestCircuitBreakerPersistence]] - code - tests/test_p1_remaining.py
- [[_load_state() must serialize on _CB_STATE_FILE_LOCK like _save_state().…]] - rationale - tests/test_p1_remaining.py
- [[persist=False circuit breaker never writes state file.]] - rationale - tests/test_p1_remaining.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_204
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 1 edge to [[_COMMUNITY_Community 96]]

## Top bridge nodes
- [[TestCircuitBreakerPersistence]] - degree 13, connects to 2 communities