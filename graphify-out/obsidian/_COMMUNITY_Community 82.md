---
type: community
cohesion: 0.11
members: 31
---

# Community 82

**Cohesion:** 0.11 - loosely connected
**Members:** 31 nodes

## Members
- [[Apply beta calibration sigmoid(aln(s) - bln(1-s) + c). params is currently…]] - rationale - ml_bias.py
- [[Apply per-city Platt calibration; returns raw_prob unchanged if no model.]] - rationale - ml_bias.py
- [[Apply temperature calibration; returns prob unchanged if no model is trained.…]] - rationale - ml_bias.py
- [[Compute HMAC-SHA256 of data using MODEL_HMAC_SECRET.]] - rationale - ml_bias.py
- [[Fit Platt scaling (A, B) via cross-entropy minimisation with scipy.]] - rationale - ml_bias.py
- [[Fit Platt scaling on METAR same-day lock-in predictions, returned as a (a, a,…]] - rationale - ml_bias.py
- [[Load bias models from disk after HMAC verification. Refuses to deserialise if…]] - rationale - ml_bias.py
- [[Load the temperature scaling table from disk. Supports two file formats - New…]] - rationale - ml_bias.py
- [[METAR lock-in betaPlatt calibration tests]] - code - tests/test_ml_bias.py
- [[METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR]] - code - ml_bias.py
- [[ML-based probability calibration — GradientBoosting per-city correction of…]] - rationale - ml_bias.py
- [[Numerically stable sigmoid -- branches on the sign of x so math.exp never…]] - rationale - ml_bias.py
- [[Per-city Platt scaling tests]] - code - tests/test_ml_bias.py
- [[Return the HMAC secret from env. Empty string disables verification (dev only).]] - rationale - ml_bias.py
- [[TestMetarSettlementCalibration (force-close gate calibration)]] - code - tests/test_settlement_monitor.py
- [[Train per-city Platt scaling fits (A, B) via cross-entropy on logit(p).…]] - rationale - ml_bias.py
- [[Write HMAC sidecar for a freshly serialised pickle.]] - rationale - ml_bias.py
- [[_compute_hmac()]] - code - ml_bias.py
- [[_fit_platt()]] - code - ml_bias.py
- [[_hmac_secret()]] - code - ml_bias.py
- [[_load_models()]] - code - ml_bias.py
- [[_load_temperature_scale()]] - code - ml_bias.py
- [[_logit()]] - code - ml_bias.py
- [[_sigmoid()]] - code - ml_bias.py
- [[_write_hmac()]] - code - ml_bias.py
- [[apply_metar_calibration()]] - code - ml_bias.py
- [[apply_platt_per_city()]] - code - ml_bias.py
- [[apply_temperature_scaling()]] - code - ml_bias.py
- [[fit_metar_calibration()]] - code - ml_bias.py
- [[ml_bias.py]] - code - ml_bias.py
- [[train_platt_per_city()]] - code - ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_82
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 5]]
- 8 edges to [[_COMMUNITY_Community 3]]
- 6 edges to [[_COMMUNITY_Community 55]]
- 3 edges to [[_COMMUNITY_Community 230]]
- 3 edges to [[_COMMUNITY_Community 6]]
- 3 edges to [[_COMMUNITY_Community 41]]
- 2 edges to [[_COMMUNITY_Community 218]]
- 2 edges to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 101]]
- 1 edge to [[_COMMUNITY_Community 2]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 0]]
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 245]]
- 1 edge to [[_COMMUNITY_Community 99]]
- 1 edge to [[_COMMUNITY_Community 226]]

## Top bridge nodes
- [[ml_bias.py]] - degree 39, connects to 11 communities
- [[_load_models()]] - degree 7, connects to 3 communities
- [[apply_metar_calibration()]] - degree 9, connects to 2 communities
- [[apply_temperature_scaling()]] - degree 8, connects to 2 communities
- [[train_platt_per_city()]] - degree 8, connects to 2 communities