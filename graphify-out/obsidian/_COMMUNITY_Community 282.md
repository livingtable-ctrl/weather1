---
type: community
cohesion: 0.15
members: 13
---

# Community 282

**Cohesion:** 0.15 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-_call()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_no_negative_weights_no_nws()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_no_negative_weights_tight_spread()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_tight_spread_boosts_ensemble()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_weights_sum_to_one()_2]] - code - tests/test_phase2_batch_k.py
- [[dot-test_wide_spread_reduces_ensemble()]] - code - tests/test_phase2_batch_k.py
- [[All weights must sum to 1.0 regardless of scaling.]] - rationale - tests/test_phase2_batch_k.py
- [[No negative weights when NWS is unavailable and spread is tight.]] - rationale - tests/test_phase2_batch_k.py
- [[TestConfidenceScaledBlendWeightsNoNegative]] - code - tests/test_phase2_batch_k.py
- [[Tighter-than-reference spread (std  4°F) must increase w_ens.]] - rationale - tests/test_phase2_batch_k.py
- [[Weights must stay = 0 when scale  1 (tight spread).]] - rationale - tests/test_phase2_batch_k.py
- [[Wider-than-reference spread (std  4°F) must decrease w_ens.]] - rationale - tests/test_phase2_batch_k.py
- [[With ens_std=0.5 (scale=40.5=8, clamped to 1.5), w_climw_nws stay = 0.]] - rationale - tests/test_phase2_batch_k.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_282
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Community 173]]
- 2 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]

## Top bridge nodes
- [[TestConfidenceScaledBlendWeightsNoNegative]] - degree 9, connects to 2 communities
- [[dot-test_no_negative_weights_no_nws()]] - degree 3, connects to 1 community
- [[dot-test_no_negative_weights_tight_spread()]] - degree 3, connects to 1 community
- [[dot-test_tight_spread_boosts_ensemble()]] - degree 3, connects to 1 community
- [[dot-test_weights_sum_to_one()_2]] - degree 3, connects to 1 community