---
type: community
cohesion: 0.20
members: 10
---

# Community 372

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[dot-test_precip_fallback_on_exception()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_precip_uses_clim_prob_when_available()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_snow_fallback_uses_seasonal_default()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_snow_uses_clim_prob_when_available()]] - code - tests/test_phase2_batch_k.py
- [[TestClimPriorUseClimatologicalProb]] - code - tests/test_phase2_batch_k.py
- [[When climatological_prob raises in snow, fallback is seasonal (0.200.05).]] - rationale - tests/test_phase2_batch_k.py
- [[When climatological_prob raises, clim_prior falls back to 0.30.]] - rationale - tests/test_phase2_batch_k.py
- [[_analyze_precip_trade and _analyze_snow_trade must call climatological_prob.]] - rationale - tests/test_phase2_batch_k.py
- [[_analyze_snow_trade must call climatological_prob.]] - rationale - tests/test_phase2_batch_k.py
- [[clim_prior in precip blend should be 0.50 when climatological_prob returns 0.50.]] - rationale - tests/test_phase2_batch_k.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_372
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]

## Top bridge nodes
- [[TestClimPriorUseClimatologicalProb]] - degree 6, connects to 1 community