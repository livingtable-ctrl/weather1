---
type: community
cohesion: 0.11
members: 18
---

# Community 188

**Cohesion:** 0.11 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-setUp()_9]] - code - tests/test_paper.py
- [[dot-tearDown()_9]] - code - tests/test_paper.py
- [[dot-test_full_scaling_at_peak()]] - code - tests/test_paper.py
- [[dot-test_kelly_scaled_at_partial_recovery()]] - code - tests/test_paper.py
- [[dot-test_kelly_zero_below_20_pct()]] - code - tests/test_paper.py
- [[dot-test_tier2_scaling_between_80_and_85_pct()]] - code - tests/test_paper.py
- [[dot-test_tier3_scaling_between_85_and_90_pct()]] - code - tests/test_paper.py
- [[dot-test_tier4_scaling_between_90_and_95_pct()]] - code - tests/test_paper.py
- [[dot-test_zero_scaling_below_20_pct()]] - code - tests/test_paper.py
- [[At full balance, scaling factor is 1.0.]] - rationale - tests/test_paper.py
- [[Balance at 82% of peak → step tier = 0.10 (TIER_1–TIER_2 with 20% halt).]] - rationale - tests/test_paper.py
- [[Balance at 87% of peak → step tier = 0.30 (TIER_2–TIER_3 with 20% halt).]] - rationale - tests/test_paper.py
- [[Balance at 92% of peak → step tier = 0.70 (TIER_3–TIER_4 with 20% halt).]] - rationale - tests/test_paper.py
- [[Below 20% of peak → scale = 0.0 (fully paused).]] - rationale - tests/test_paper.py
- [[Kelly dollars are scaled by recovery factor, not all-or-nothing.]] - rationale - tests/test_paper.py
- [[Kelly still returns 0.0 when fully in drawdown (scale=0.0).]] - rationale - tests/test_paper.py
- [[TestDrawdownScaling]] - code - tests/test_paper.py
- [[Tests for the gradual drawdown recovery sizing feature.]] - rationale - tests/test_paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_188
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 56]]
- 1 edge to [[_COMMUNITY_Community 45]]

## Top bridge nodes
- [[TestDrawdownScaling]] - degree 12, connects to 2 communities