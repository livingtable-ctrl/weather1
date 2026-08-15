---
type: community
cohesion: 0.15
members: 13
---

# Community 275

**Cohesion:** 0.15 - loosely connected
**Members:** 13 nodes

## Members
- [[dot-test_heat_dome_overrides_weights()]] - code - tests/test_forecasting.py
- [[dot-test_normal_regime_uses_existing_weights()]] - code - tests/test_forecasting.py
- [[dot-test_notify_does_not_overwrite_existing_key()]] - code - tests/test_forecasting.py
- [[dot-test_notify_writes_feature_activations_file()]] - code - tests/test_forecasting.py
- [[dot-test_regime_blend_active_above_threshold()]] - code - tests/test_forecasting.py
- [[dot-test_regime_blend_inactive_below_threshold()]] - code - tests/test_forecasting.py
- [[TestRegimeBlend]] - code - tests/test_forecasting.py
- [[_notify_feature_activation is idempotent -- does not rewrite if key exists.]] - rationale - tests/test_forecasting.py
- [[_notify_feature_activation writes datafeature_activations.json on first call.]] - rationale - tests/test_forecasting.py
- [[_regime_blend_active returns False when settled count  30.]] - rationale - tests/test_forecasting.py
- [[_regime_blend_active returns True when settled count = 30.]] - rationale - tests/test_forecasting.py
- [[heat_dome regime - ens=0.70, nws=0.25, clim=0.05 (after active).]] - rationale - tests/test_forecasting.py
- [[normal regime - existing conditionseasonal weights unchanged.]] - rationale - tests/test_forecasting.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_275
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[TestRegimeBlend]] - degree 8, connects to 2 communities