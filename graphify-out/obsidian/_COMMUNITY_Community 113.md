---
type: community
cohesion: 0.11
members: 25
---

# Community 113

**Cohesion:** 0.11 - loosely connected
**Members:** 25 nodes

## Members
- [[dot-_load_table()]] - code - tests/test_ml_bias.py
- [[dot-test_falls_back_to_global_when_condition_absent()]] - code - tests/test_ml_bias.py
- [[dot-test_global_T_compresses_toward_0p5()]] - code - tests/test_ml_bias.py
- [[dot-test_hourly_pool_ignored_when_days_out_passed_alongside()]] - code - tests/test_ml_bias.py
- [[dot-test_hourly_pool_no_fallback_to_sameday_or_global()]] - code - tests/test_ml_bias.py
- [[dot-test_hourly_pool_uses_hourly_T()]] - code - tests/test_ml_bias.py
- [[dot-test_multiday_unaffected_by_sameday_key()]] - code - tests/test_ml_bias.py
- [[dot-test_no_file_returns_prob_unchanged()]] - code - tests/test_ml_bias.py
- [[dot-test_ordinary_sameday_call_unaffected_by_hourly_key_presence()]] - code - tests/test_ml_bias.py
- [[dot-test_per_condition_T_used_when_available()]] - code - tests/test_ml_bias.py
- [[dot-test_sameday_no_fallback_to_global()]] - code - tests/test_ml_bias.py
- [[dot-test_sameday_uses_sameday_T()]] - code - tests/test_ml_bias.py
- [[Existing callers (no pool arg) must be completely unaffected by an 'hourly' key…]] - rationale - tests/test_ml_bias.py
- [[Falls back to global T when condition_type is not in the table.]] - rationale - tests/test_ml_bias.py
- [[No 'hourly' key yet (fewer than 20 settled hourly predictions) must return prob…]] - rationale - tests/test_ml_bias.py
- [[Returns prob unchanged when temperature_scale.json does not exist.]] - rationale - tests/test_ml_bias.py
- [[TestApplyTemperatureScaling]] - code - tests/test_ml_bias.py
- [[Tests for apply_temperature_scaling — the per-condition calibration step. Each…]] - rationale - tests/test_ml_bias.py
- [[With a global T  1, output is compressed toward 0.5 from both sides.]] - rationale - tests/test_ml_bias.py
- [[Write content to a temp file and wire ml_bias to read it.]] - rationale - tests/test_ml_bias.py
- [[condition_type='between' uses the between T, not the global T.]] - rationale - tests/test_ml_bias.py
- [[days_out=0 returns prob unchanged when 'sameday' key absent — no global…]] - rationale - tests/test_ml_bias.py
- [[days_out=0 uses 'sameday' T, not the global T.]] - rationale - tests/test_ml_bias.py
- [[days_out=1 still uses per-conditionglobal T even when sameday key is present.]] - rationale - tests/test_ml_bias.py
- [[pool='hourly' must win over days_out=0's sameday branch -- callers pass both,…]] - rationale - tests/test_ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_113
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]

## Top bridge nodes
- [[TestApplyTemperatureScaling]] - degree 14, connects to 1 community