---
type: community
cohesion: 0.14
members: 19
---

# Community 173

**Cohesion:** 0.14 - loosely connected
**Members:** 19 nodes

## Members
- [[dot-_call()_1]] - code - tests/test_phase2_batch_k.py
- [[dot-test_all_identical_flagged_as_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_analyze_trade_skips_degenerate_ensemble()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_degenerate_key_always_present_when_nonempty()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_empty_returns_empty()_1]] - code - tests/test_phase2_batch_k.py
- [[dot-test_exactly_5_members_not_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_no_negative_weights_no_clim()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_six_identical_members_is_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_varied_temps_not_degenerate()]] - code - tests/test_phase2_batch_k.py
- [[10 identical values (std=0) with n5 must be degenerate=True.]] - rationale - tests/test_phase2_batch_k.py
- [[6 identical members triggers degenerate=True.]] - rationale - tests/test_phase2_batch_k.py
- [[Empty input returns empty dict (no degenerate key).]] - rationale - tests/test_phase2_batch_k.py
- [[Exactly 5 identical members degenerate threshold requires 5.]] - rationale - tests/test_phase2_batch_k.py
- [[No negative weights when climatology is unavailable and spread is tight.]] - rationale - tests/test_phase2_batch_k.py
- [[Normal spread must not be flagged as degenerate.]] - rationale - tests/test_phase2_batch_k.py
- [[TestEnsembleStatsDegenerate]] - code - tests/test_phase2_batch_k.py
- [[analyze_trade must return None when ens_stats.degenerate is True.]] - rationale - tests/test_phase2_batch_k.py
- [[degenerate key must be present for any non-empty input.]] - rationale - tests/test_phase2_batch_k.py
- [[ensemble_stats must flag all-identical members as degenerate.]] - rationale - tests/test_phase2_batch_k.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_173
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Community 282]]
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 1 edge to [[_COMMUNITY_Community 160]]

## Top bridge nodes
- [[dot-_call()_1]] - degree 14, connects to 2 communities
- [[TestEnsembleStatsDegenerate]] - degree 10, connects to 1 community
- [[dot-test_no_negative_weights_no_clim()]] - degree 3, connects to 1 community