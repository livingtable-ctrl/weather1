---
type: community
cohesion: 0.08
members: 32
---

# Community 77

**Cohesion:** 0.08 - loosely connected
**Members:** 32 nodes

## Members
- [[dot-_call()_4]] - code - tests/test_phase2_batch_k.py
- [[dot-_call()_5]] - code - tests/test_phase2_batch_k.py
- [[dot-test_all_identical_flagged_as_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_analyze_trade_skips_degenerate_ensemble()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_degenerate_key_always_present_when_nonempty()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_empty_returns_empty()_1]] - code - tests/test_phase2_batch_k.py
- [[dot-test_exactly_5_members_not_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_no_negative_weights_no_clim()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_no_negative_weights_no_nws()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_no_negative_weights_tight_spread()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_six_identical_members_is_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_tight_spread_boosts_ensemble()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_varied_temps_not_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_weights_sum_to_one()_5]] - code - tests/test_phase2_batch_k.py
- [[dot-test_wide_spread_reduces_ensemble()]] - code - tests/test_phase2_batch_k.py
- [[10 identical values (std=0) with n5 must be degenerate=True.]] - rationale - tests/test_phase2_batch_k.py
- [[6 identical members triggers degenerate=True.]] - rationale - tests/test_phase2_batch_k.py
- [[All weights must sum to 1.0 regardless of scaling.]] - rationale - tests/test_phase2_batch_k.py
- [[Empty input returns empty dict (no degenerate key).]] - rationale - tests/test_phase2_batch_k.py
- [[Exactly 5 identical members degenerate threshold requires 5.]] - rationale - tests/test_phase2_batch_k.py
- [[No negative weights when NWS is unavailable and spread is tight.]] - rationale - tests/test_phase2_batch_k.py
- [[No negative weights when climatology is unavailable and spread is tight.]] - rationale - tests/test_phase2_batch_k.py
- [[Normal spread must not be flagged as degenerate.]] - rationale - tests/test_phase2_batch_k.py
- [[TestConfidenceScaledBlendWeightsNoNegative]] - code - tests/test_phase2_batch_k.py
- [[TestEnsembleStatsDegenerate]] - code - tests/test_phase2_batch_k.py
- [[Tighter-than-reference spread (std  4°F) must increase w_ens.]] - rationale - tests/test_phase2_batch_k.py
- [[Weights must stay = 0 when scale  1 (tight spread).]] - rationale - tests/test_phase2_batch_k.py
- [[Wider-than-reference spread (std  4°F) must decrease w_ens.]] - rationale - tests/test_phase2_batch_k.py
- [[With ens_std=0.5 (scale=40.5=8, clamped to 1.5), w_climw_nws stay = 0.]] - rationale - tests/test_phase2_batch_k.py
- [[analyze_trade must return None when ens_stats.degenerate is True.]] - rationale - tests/test_phase2_batch_k.py
- [[degenerate key must be present for any non-empty input.]] - rationale - tests/test_phase2_batch_k.py
- [[ensemble_stats must flag all-identical members as degenerate.]] - rationale - tests/test_phase2_batch_k.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_77
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 68]]
- 1 edge to [[_COMMUNITY_Community 183]]

## Top bridge nodes
- [[dot-_call()_5]] - degree 14, connects to 1 community
- [[TestEnsembleStatsDegenerate]] - degree 10, connects to 1 community
- [[TestConfidenceScaledBlendWeightsNoNegative]] - degree 9, connects to 1 community
- [[dot-_call()_4]] - degree 2, connects to 1 community