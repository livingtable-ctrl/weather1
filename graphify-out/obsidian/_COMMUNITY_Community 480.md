---
type: community
cohesion: 0.33
members: 7
---

# Community 480

**Cohesion:** 0.33 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-_make_trade()_1]] - code - tests/test_phase2_batch_a.py
- [[dot-test_is_streak_paused_uses_settled_at_for_magnitude_check()]] - code - tests/test_phase2_batch_a.py
- [[dot-test_sort_key_falls_back_to_entered_at_when_no_settled_at()]] - code - tests/test_phase2_batch_a.py
- [[P2-3 is_streak_paused must sort by settled_at when computing streak PnL.…]] - rationale - tests/test_phase2_batch_a.py
- [[P2-3 is_streak_paused must sort trades by settled_at, not entered_at.]] - rationale - tests/test_phase2_batch_a.py
- [[TestStreakPausedSortOrder]] - code - tests/test_phase2_batch_a.py
- [[Trades without settled_at fall back to entered_at without crashing.]] - rationale - tests/test_phase2_batch_a.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_480
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 168]]

## Top bridge nodes
- [[TestStreakPausedSortOrder]] - degree 5, connects to 1 community