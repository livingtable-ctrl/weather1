---
type: community
cohesion: 0.06
members: 39
---

# Community 52

**Cohesion:** 0.06 - loosely connected
**Members:** 39 nodes

## Members
- [[dot-_enriched()_6]] - code - tests/test_signal_quality.py
- [[dot-_enriched()_7]] - code - tests/test_signal_quality.py
- [[dot-setup_method()_35]] - code - tests/test_signal_quality.py
- [[dot-setup_method()_36]] - code - tests/test_signal_quality.py
- [[dot-teardown_method()_27]] - code - tests/test_signal_quality.py
- [[dot-teardown_method()_28]] - code - tests/test_signal_quality.py
- [[dot-test_bias_correction_condition_type_param_accepted()]] - code - tests/test_signal_quality.py
- [[dot-test_condition_type_scale_in_kelly()]] - code - tests/test_signal_quality.py
- [[dot-test_get_member_accuracy_respects_days_back()]] - code - tests/test_signal_quality.py
- [[dot-test_monthly_rain_and_snow_condition_confidence()]] - code - tests/test_signal_quality.py
- [[dot-test_narrow_spread_allows_signal()]] - code - tests/test_signal_quality.py
- [[dot-test_passes_sufficient_volume()]] - code - tests/test_signal_quality.py
- [[dot-test_skips_low_volume_market()]] - code - tests/test_signal_quality.py
- [[dot-test_strong_edge_above_med_edge()]] - code - tests/test_signal_quality.py
- [[dot-test_strong_edge_default_is_0_30()]] - code - tests/test_signal_quality.py
- [[dot-test_wide_spread_suppresses_signal()]] - code - tests/test_signal_quality.py
- [[Old scores (90 days ago) are excluded; recent scores (10 days ago) are included.]] - rationale - tests/test_signal_quality.py
- [[Opus-review-caught gap _CONDITION_CONFIDENCEsnow_month_total had zero test…]] - rationale - tests/test_signal_quality.py
- [[Query the last `window` settled predictions and count wins. A win is (our_prob…]] - rationale - tracker.py
- [[Run SPRT on the last `window` settled trades. Sequential Probability Ratio Test…]] - rationale - tracker.py
- [[Softmax-normalised inverse-MAE weights for each ensemble model. Uses…]] - rationale - tracker.py
- [[TestAnalyzeTradeConditionType]] - code - tests/test_signal_quality.py
- [[TestGetMemberAccuracyDaysBack]] - code - tests/test_signal_quality.py
- [[TestMaxModelSpreadGate]] - code - tests/test_signal_quality.py
- [[TestMinSignalVolume]] - code - tests/test_signal_quality.py
- [[TestStrongEdgeThreshold]] - code - tests/test_signal_quality.py
- [[Tests for Group 2 signal quality improvements.]] - rationale - tests/test_signal_quality.py
- [[_CONDITION_CONFIDENCE values correctly rank precip_snow  precip_any  above.]] - rationale - tests/test_signal_quality.py
- [[_get_recent_win_loss()]] - code - tracker.py
- [[analyze_trade() returns None when model spread exceeds MAX_MODEL_SPREAD_F.]] - rationale - tests/test_signal_quality.py
- [[analyze_trade() skips markets below MIN_SIGNAL_VOLUME.]] - rationale - tests/test_signal_quality.py
- [[apply_ml_prob_correction Function]] - code - ml_bias.py
- [[get_bias accepts condition_type kwarg — confirms the interface exists for…]] - rationale - tests/test_signal_quality.py
- [[get_model_weights()]] - code - tracker.py
- [[kalshi_client.py_1]] - code - kalshi_client.py
- [[sprt_model_health()]] - code - tracker.py
- [[test_signal_quality.py]] - code - tests/test_signal_quality.py
- [[tracker.py_2]] - code - tracker.py
- [[train_bias_model Function]] - code - ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_52
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 5 edges to [[_COMMUNITY_Community 40]]
- 4 edges to [[_COMMUNITY_Community 36]]
- 3 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Community 127]]
- 2 edges to [[_COMMUNITY_Community 190]]
- 2 edges to [[_COMMUNITY_Community 328]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Black Swan Halt State]]
- 2 edges to [[_COMMUNITY_Community 353]]
- 2 edges to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 2 edges to [[_COMMUNITY_Community 71]]
- 2 edges to [[_COMMUNITY_Community 74]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Community 184]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 380]]
- 1 edge to [[_COMMUNITY_Community 53]]
- 1 edge to [[_COMMUNITY_Community 220]]
- 1 edge to [[_COMMUNITY_Community 43]]
- 1 edge to [[_COMMUNITY_Community 228]]
- 1 edge to [[_COMMUNITY_Community 92]]

## Top bridge nodes
- [[tracker.py_2]] - degree 20, connects to 11 communities
- [[test_signal_quality.py]] - degree 20, connects to 9 communities
- [[get_model_weights()]] - degree 11, connects to 5 communities
- [[kalshi_client.py_1]] - degree 5, connects to 4 communities
- [[sprt_model_health()]] - degree 6, connects to 3 communities