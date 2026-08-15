---
type: community
cohesion: 0.15
members: 16
---

# Community 214

**Cohesion:** 0.15 - loosely connected
**Members:** 16 nodes

## Members
- [[dot-test_gbm_and_platt_not_sequentially_applied()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_has_ml_model_false_when_no_models()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_has_ml_model_helper_exists()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_has_ml_model_true_when_model_present()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_platt_not_called_when_gbm_model_present()]] - code - tests/test_phase2_batch_k.py
- [[dot-test_source_uses_has_ml_model_gate()]] - code - tests/test_phase2_batch_k.py
- [[GBM and Platt must not both be applied to the same city's probability.]] - rationale - tests/test_phase2_batch_k.py
- [[Return True if a trained GBM correction model exists for this city.]] - rationale - ml_bias.py
- [[TestOnlyOneMlCorrectionApplied]] - code - tests/test_phase2_batch_k.py
- [[Verify source Platt block is inside '_city_correction_applied' guard.]] - rationale - tests/test_phase2_batch_k.py
- [[When GBM model exists, apply_platt_per_city must NOT be called.]] - rationale - tests/test_phase2_batch_k.py
- [[analyze_trade source must use has_ml_model to guard Platt application.]] - rationale - tests/test_phase2_batch_k.py
- [[has_ml_model returns False when bias_models is absentempty.]] - rationale - tests/test_phase2_batch_k.py
- [[has_ml_model returns True when a model exists for the city.]] - rationale - tests/test_phase2_batch_k.py
- [[has_ml_model()]] - code - ml_bias.py
- [[ml_bias must export has_ml_model(city).]] - rationale - tests/test_phase2_batch_k.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_214
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 2 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]

## Top bridge nodes
- [[has_ml_model()]] - degree 12, connects to 4 communities
- [[TestOnlyOneMlCorrectionApplied]] - degree 8, connects to 1 community