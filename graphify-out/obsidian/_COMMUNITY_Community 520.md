---
type: community
cohesion: 0.29
members: 7
---

# Community 520

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[$50 trade on a $5000 account = 1% exposure — well under 50% cap.]] - rationale - tests/test_phase2_batch_i.py
- [[dot-test_exposure_denom_called()_1]] - code - tests/test_phase2_batch_i.py
- [[dot-test_global_cap_triggers_correctly()]] - code - tests/test_phase2_batch_i.py
- [[dot-test_small_order_passes_on_grown_account()]] - code - tests/test_phase2_batch_i.py
- [[49% existing + 10% new = 59% → must breach MAX_TOTAL_OPEN_EXPOSURE (50%).]] - rationale - tests/test_phase2_batch_i.py
- [[Global exposure cap must use _exposure_denom(), not STARTING_BALANCE.]] - rationale - tests/test_phase2_batch_i.py
- [[TestCheckPositionLimitsDenom]] - code - tests/test_phase2_batch_i.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_520
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestCheckPositionLimitsDenom]] - degree 5, connects to 1 community