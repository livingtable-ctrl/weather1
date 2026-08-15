---
type: community
cohesion: 0.33
members: 9
---

# Community 404

**Cohesion:** 0.33 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-_call_with_recovery()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_exactly_tier4_returns_full()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_full_recovery_returns_full()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_just_below_tier4_returns_reduced()]] - code - tests/test_phase2_batch_g.py
- [[dot-test_tier3_boundary()]] - code - tests/test_phase2_batch_g.py
- [[P2-31 exactly 95% recovery must return 1.0 (full sizing), not 0.70.]] - rationale - tests/test_phase2_batch_g.py
- [[TestDrawdownTier4Boundary]] - code - tests/test_phase2_batch_g.py
- [[recovery == 0.949 (just below tier-4) must return 0.70.]] - rationale - tests/test_phase2_batch_g.py
- [[recovery == 0.95 (exactly at tier-4) must return 1.0, not 0.70.]] - rationale - tests/test_phase2_batch_g.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_404
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 248]]

## Top bridge nodes
- [[TestDrawdownTier4Boundary]] - degree 7, connects to 1 community