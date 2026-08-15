---
type: community
cohesion: 0.07
members: 33
---

# Community 71

**Cohesion:** 0.07 - loosely connected
**Members:** 33 nodes

## Members
- [[dot-test_component_attribution_key_is_brier_not_brier_score()]] - code - tests/test_web_analytics.py
- [[dot-test_model_calibration_buckets_has_buckets_key()]] - code - tests/test_web_analytics.py
- [[dot-test_roc_auc_has_points_array()]] - code - tests/test_web_analytics.py
- [[Brier score = mean((our_prob - outcome)²). Lower is better. 0.25 = random, 0.0…]] - rationale - tracker.py
- [[Brier score over the most recent `weeks` weeks of settled multi-day predictions.]] - rationale - tracker.py
- [[Ensure KALSHI_ENV=demo so _build_app doesn't require DASHBOARD_PASSWORD._1]] - rationale - tests/test_web_analytics.py
- [[How well-calibrated is OUR MODEL (not market prices) Groups settled…]] - rationale - tracker.py
- [[ROC curve and AUC score for the model. Returns {auc, n, points {fpr, tpr}}…]] - rationale - tracker.py
- [[Regression test Brier score must not degrade more than 1% after refactors.]] - rationale - tests/test_regression.py
- [[TestAnalyticsApiShape]] - code - tests/test_web_analytics.py
- [[Tests for web analytics API shape contracts.]] - rationale - tests/test_web_analytics.py
- [[When MC clamps a probability, the UI should explain this is expecteddefensive.]] - rationale - tests/test_regression.py
- [[_force_demo_env()_2]] - code - tests/test_web_analytics.py
- [[_no_dashboard_password()_1]] - code - tests/test_web_analytics.py
- [[analytics_client()]] - code - tests/test_web_analytics.py
- [[api_analytics component_attribution must use 'brier' key, not 'brier_score'.]] - rationale - tests/test_web_analytics.py
- [[api_analytics must return model_calibration_buckets with a .buckets array whose…]] - rationale - tests/test_web_analytics.py
- [[api_analytics must return roc_auc with points{fpr,tpr} — NOT top-level…]] - rationale - tests/test_web_analytics.py
- [[brier_score()]] - code - tracker.py
- [[brier_score_rolling()]] - code - tracker.py
- [[cmd_simulate must call backtest._fetch_settled_markets (series-based), not…]] - rationale - tests/test_regression.py
- [[fixture_16]] - code
- [[get_model_calibration_buckets()]] - code - tracker.py
- [[get_roc_auc()]] - code - tracker.py
- [[get_weather_markets must not call client.get_markets() without series_ticker.…]] - rationale - tests/test_regression.py
- [[test_brier_score_not_degraded()]] - code - tests/test_regression.py
- [[test_get_weather_markets_does_not_call_global_get_markets()]] - code - tests/test_regression.py
- [[test_montecarlo_explains_clamping_in_output()]] - code - tests/test_regression.py
- [[test_regression.py]] - code - tests/test_regression.py
- [[test_roc_auc_not_degraded()]] - code - tests/test_regression.py
- [[test_simulate_uses_series_fetch_not_global_pagination()]] - code - tests/test_regression.py
- [[test_web_analytics.py]] - code - tests/test_web_analytics.py
- [[utils.DASHBOARD_PASSWORD is cached at import time (conftest.py imports main,…_1]] - rationale - tests/test_web_analytics.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_71
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 9 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 5 edges to [[_COMMUNITY_Community 36]]
- 3 edges to [[_COMMUNITY_Black Swan Halt State]]
- 2 edges to [[_COMMUNITY_Community 52]]
- 2 edges to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 284]]
- 1 edge to [[_COMMUNITY_Community 167]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 245]]
- 1 edge to [[_COMMUNITY_Community 94]]
- 1 edge to [[_COMMUNITY_Community 59]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 176]]

## Top bridge nodes
- [[brier_score()]] - degree 22, connects to 10 communities
- [[test_regression.py]] - degree 13, connects to 4 communities
- [[get_roc_auc()]] - degree 10, connects to 4 communities
- [[test_web_analytics.py]] - degree 11, connects to 3 communities
- [[brier_score_rolling()]] - degree 5, connects to 2 communities