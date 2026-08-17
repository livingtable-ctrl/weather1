---
type: community
cohesion: 0.14
members: 14
---

# Community 257

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_default_halt_no_warning()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_non_default_halt_emits_warning()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_scaling_at_tier_boundaries()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_tier1_is_0_80()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_tier2_is_0_85()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_tier3_is_0_90()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_tier4_is_0_95()]] - code - tests/test_phase2_batch_b.py
- [[dot-test_tiers_unchanged_with_non_default_halt()]] - code - tests/test_phase2_batch_b.py
- [[Default DRAWDOWN_HALT_PCT=0.20 must NOT emit the tier warning.]] - rationale - tests/test_phase2_batch_b.py
- [[Non-default DRAWDOWN_HALT_PCT must log a warning about tier misalignment.]] - rationale - tests/test_phase2_batch_b.py
- [[P2-2 root cause old code shifted all boundaries when halt% changed.]] - rationale - tests/test_phase2_batch_b.py
- [[P2-2 _DRAWDOWN_TIER_ constants must be hardcoded absolute values.]] - rationale - tests/test_phase2_batch_b.py
- [[Spot-check the step function at each canonical boundary.]] - rationale - tests/test_phase2_batch_b.py
- [[TestDrawdownTierAbsolute]] - code - tests/test_phase2_batch_b.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_257
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestDrawdownTierAbsolute]] - degree 10, connects to 1 community