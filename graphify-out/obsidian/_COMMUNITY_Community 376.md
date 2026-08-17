---
type: community
cohesion: 0.20
members: 10
---

# Community 376

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_full_sizing_near_peak()]] - code - tests/test_drawdown_tiers.py
- [[dot-test_halt_at_20pct_drawdown()]] - code - tests/test_drawdown_tiers.py
- [[dot-test_tier_constants_are_absolute()]] - code - tests/test_drawdown_tiers.py
- [[dot-test_tier_constants_are_ordered()]] - code - tests/test_drawdown_tiers.py
- [[Above TIER_4, full sizing (1.0) is returned.]] - rationale - tests/test_drawdown_tiers.py
- [[At 20% drawdown, scaling factor should be 0.0.]] - rationale - tests/test_drawdown_tiers.py
- [[P2-2 Tiers must be absolute constants, not derived from DRAWDOWN_HALT_PCT.]] - rationale - tests/test_drawdown_tiers.py
- [[P2-2 tiers must not shift when DRAWDOWN_HALT_PCT is non-default.]] - rationale - tests/test_drawdown_tiers.py
- [[TestDrawdownTiersRelativeToHalt]] - code - tests/test_drawdown_tiers.py
- [[Tier ordering invariant TIER_1  TIER_2  TIER_3  TIER_4 = 1.0.]] - rationale - tests/test_drawdown_tiers.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_376
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestDrawdownTiersRelativeToHalt]] - degree 6, connects to 1 community