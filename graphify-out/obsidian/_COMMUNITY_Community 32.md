---
type: community
cohesion: 0.05
members: 50
---

# Community 32

**Cohesion:** 0.05 - loosely connected
**Members:** 50 nodes

## Members
- [[dot-_make_trades()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_fewer_than_20_returns_error()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_reduced_hyperparams()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_results_not_saved_when_holdout_fails()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_skips_city_when_holdout_mse_not_better()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_sweep_parameter_unchanged()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_sweep_source_has_split()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_too_few_trades_returns_error()]] - code - tests/test_phase2_batch_m.py
- [[dot-test_train_source_has_holdout_split()]] - code - tests/test_phase2_batch_m.py
- [[City model must not be added when holdout MSE = baseline.]] - rationale - tests/test_phase2_batch_m.py
- [[Cross-Cutting DEBUG-Only Exception Suppression (4 fns)]] - document - docs/grade_audit/outputs/feature_importance.py.md
- [[Cross-market consistency checker. For a given city + date, temperature…]] - rationale - consistency.py
- [[For each value in `values`, simulate applying that parameter value to the…]] - rationale - param_sweep.py
- [[Grade Audit Module Doc TIER 2 Files]] - document - docs/grade_audit/modules/tier2.md
- [[GradientBoostingRegressor must use n_estimators=50, max_depth=2.]] - rationale - tests/test_phase2_batch_m.py
- [[Group markets by (series_ticker, date_str). Returns dict key - list of…]] - rationale - consistency.py
- [[If holdout win rate  baseline, results must NOT be saved.]] - rationale - tests/test_phase2_batch_m.py
- [[Phase 2 Batch M Regression Tests]] - code - tests/test_phase2_batch_m.py
- [[Phase 2 Batch M regression tests P2-353738424446.]] - rationale - tests/test_phase2_batch_m.py
- [[Record which features were present for a trade and (optionally) the outcome.…]] - rationale - feature_importance.py
- [[Run a sweep across key parameters using historical paper trades. Uses a 7030…]] - rationale - param_sweep.py
- [[TestGbmHoldoutValidation]] - code - tests/test_phase2_batch_m.py
- [[TestParamSweepTemporalSplit]] - code - tests/test_phase2_batch_m.py
- [[Train a bias correction model per city from tracker DB data. Saves models to…]] - rationale - ml_bias.py
- [[_group_markets()]] - code - consistency.py
- [[_group_markets() No tryexcept Aborts Whole Scan (710)]] - document - docs/grade_audit/outputs/consistency.py.md
- [[consistency.py]] - code - consistency.py
- [[consistency.py Detect-Only, No Enforcement Path (INFO)]] - document - docs/grade_audit/outputs/consistency.py.md
- [[consistency.py File Grade median 710, no TIER1 promotions]] - document - docs/grade_audit/outputs/consistency.py.md
- [[consistency.py Grade Audit]] - document - docs/grade_audit/outputs/consistency.py.md
- [[cron ML retrain marker (LAST_ML_RETRAIN_PATH)]] - code - cron.py
- [[feature_importance.py]] - code - feature_importance.py
- [[feature_importance.py File Grade 6-710, no TIER1 (analytics side-car)]] - document - docs/grade_audit/outputs/feature_importance.py.md
- [[feature_importance.py Grade Audit]] - document - docs/grade_audit/outputs/feature_importance.py.md
- [[feature_importance.py — Track which forecast signals contribute most to correct…]] - rationale - feature_importance.py
- [[hurricanestorm ticker helpers]] - code - weather_markets.py
- [[param_sweep.py]] - code - param_sweep.py
- [[param_sweep.py Called Dead-Code Candidate (contested)]] - document - docs/grade_audit/outputs/config.py.md
- [[param_sweep.py File Grade not dead code, 1 RF1 promotion]] - document - docs/grade_audit/outputs/param_sweep.py.md
- [[param_sweep.py Grade Audit]] - document - docs/grade_audit/outputs/param_sweep.py.md
- [[param_sweep.py — Auto-test threshold ranges against historical outcomes. Usage…]] - rationale - param_sweep.py
- [[record_feature_contribution()]] - code - feature_importance.py
- [[run_sweep Function]] - code - param_sweep.py
- [[run_sweep must split data 7030 and only save when holdout passes.]] - rationale - tests/test_phase2_batch_m.py
- [[run_sweep source must contain 7030 split logic.]] - rationale - tests/test_phase2_batch_m.py
- [[run_sweep()]] - code - param_sweep.py
- [[sweep_parameter itself must still work on arbitrary lists.]] - rationale - tests/test_phase2_batch_m.py
- [[sweep_parameter()]] - code - param_sweep.py
- [[train_bias_model source must contain 8020 holdout logic.]] - rationale - tests/test_phase2_batch_m.py
- [[train_bias_model()]] - code - ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_32
SORT file.name ASC
```

## Connections to other communities
- 10 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 9 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 6 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 4 edges to [[_COMMUNITY_Community 51]]
- 4 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 3 edges to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 3 edges to [[_COMMUNITY_Community 35]]
- 3 edges to [[_COMMUNITY_Community 109]]
- 2 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 2 edges to [[_COMMUNITY_Black Swan Halt State]]
- 2 edges to [[_COMMUNITY_Community 96]]
- 1 edge to [[_COMMUNITY_Community 33]]
- 1 edge to [[_COMMUNITY_Community 345]]
- 1 edge to [[_COMMUNITY_Community 374]]
- 1 edge to [[_COMMUNITY_Community 555]]
- 1 edge to [[_COMMUNITY_Community 184]]
- 1 edge to [[_COMMUNITY_Community 186]]
- 1 edge to [[_COMMUNITY_Community 151]]
- 1 edge to [[_COMMUNITY_Community 454]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Community 129]]
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 1 edge to [[_COMMUNITY_Community 198]]
- 1 edge to [[_COMMUNITY_Community 296]]
- 1 edge to [[_COMMUNITY_Community 195]]
- 1 edge to [[_COMMUNITY_Community 567]]

## Top bridge nodes
- [[Grade Audit Module Doc TIER 2 Files]] - degree 20, connects to 12 communities
- [[Phase 2 Batch M Regression Tests]] - degree 15, connects to 7 communities
- [[consistency.py]] - degree 17, connects to 5 communities
- [[_group_markets()]] - degree 11, connects to 5 communities
- [[param_sweep.py]] - degree 11, connects to 4 communities