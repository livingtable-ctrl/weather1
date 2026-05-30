---
type: community
cohesion: 0.07
members: 53
---

# Tracker Analytics (Brier/Bias)

**Cohesion:** 0.07 - loosely connected
**Members:** 53 nodes

## Members
- [[110 Write a row to the audit_log table for any manual user action     (e.g. m]] - rationale - tracker.py
- [[55 Log every analyzed market (traded or not) for bias detection.]] - rationale - tracker.py
- [[65 Record the difference between the desired price and the actual fill price.]] - rationale - tracker.py
- [[perf Bulk-insert analysis attempts in a single transaction (much faster than]] - rationale - tracker.py
- [[Apply any pending schema migrations and update schema_version (99).]] - rationale - tracker.py
- [[Compute Brier score and win rate grouped by signal_source.     Reveals which si]] - rationale - tracker.py
- [[Compute systematic bias for a citymonth weighted mean(our_prob - actual_outcom]] - rationale - tracker.py
- [[Connection_1]] - code - tracker.py
- [[Delete settled predictions older than retention_days and their outcomes.]] - rationale - tracker.py
- [[How well-calibrated are the MARKET PRICES (not our model)     Groups settled p]] - rationale - tracker.py
- [[How well-calibrated is OUR MODEL (not market prices)     Groups settled predic]] - rationale - tracker.py
- [[Log an API call for audit trail and latency monitoring (69).]] - rationale - tracker.py
- [[Log every analyzed market (traded or not) to analysis_attempts (55).]] - rationale - tracker.py
- [[P2-13 Delete api_requests rows older than days_to_keep. Returns row count delet]] - rationale - tracker.py
- [[P9.1 Brier score and sample count grouped by edge_calc_version.      Returns]] - rationale - tracker.py
- [[Per-model MAE filtered to recent predictions, used by learn_seasonal_weights().]] - rationale - tracker.py
- [[Per-quintile bias correction.      Bins settled predictions by ``our_prob`` in]] - rationale - tracker.py
- [[Query the last `window` settled predictions and count wins.      A win is (ou]] - rationale - tracker.py
- [[ROC curve and AUC score for the model.     Returns {auc, n, points {fpr, tpr}]] - rationale - tracker.py
- [[Record a micro live fill for slippage tracking (P10.4).]] - rationale - tracker.py
- [[Return mean signed temperature error (predicted - actual) per city from     rea]] - rationale - tracker.py
- [[Return the number of predictions with a known outcome.]] - rationale - tracker.py
- [[Softmax-normalised inverse-MAE weights for each ensemble model.      Uses ense]] - rationale - tracker.py
- [[Sweep thresholds 0.05..0.95 (step 0.05) and find the one maximizing F1 (60).]] - rationale - tracker.py
- [[Win rate over the last `window` settled predictions.      Returns (win_rate, c]] - rationale - tracker.py
- [[_conn()_1]] - code - tracker.py
- [[_get_recent_win_loss()]] - code - tracker.py
- [[_run_migrations()]] - code - tracker.py
- [[analyze_all_markets()]] - code - tracker.py
- [[batch_log_analysis_attempts()]] - code - tracker.py
- [[count_settled_predictions()]] - code - tracker.py
- [[get_bias()]] - code - tracker.py
- [[get_brier_by_version()]] - code - tracker.py
- [[get_dynamic_station_bias()]] - code - tracker.py
- [[get_market_calibration()]] - code - tracker.py
- [[get_member_accuracy()]] - code - tracker.py
- [[get_model_calibration_buckets()]] - code - tracker.py
- [[get_model_weights()]] - code - tracker.py
- [[get_optimal_threshold()]] - code - tracker.py
- [[get_pnl_by_signal_source()]] - code - tracker.py
- [[get_quintile_bias()]] - code - tracker.py
- [[get_roc_auc()]] - code - tracker.py
- [[get_rolling_win_rate()]] - code - tracker.py
- [[init_db()]] - code - tracker.py
- [[int_24]] - code - tracker.py
- [[log_analysis_attempt()]] - code - tracker.py
- [[log_api_request()]] - code - tracker.py
- [[log_audit()]] - code - tracker.py
- [[log_live_fill()]] - code - tracker.py
- [[log_price_improvement()]] - code - tracker.py
- [[prune_api_requests()]] - code - tracker.py
- [[purge_old_predictions()]] - code - tracker.py
- [[test_log_analysis_attempt_stores_all_markets()]] - code - tests/test_tracker.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Tracker_Analytics_Brier/Bias
SORT file.name ASC
```

## Connections to other communities
- 54 edges to [[_COMMUNITY_Module frosty]]
- 24 edges to [[_COMMUNITY_Module frosty]]
- 23 edges to [[_COMMUNITY_Module frosty]]
- 19 edges to [[_COMMUNITY_Python Types & Utilities]]
- 12 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 9 edges to [[_COMMUNITY_Cron Scheduler]]
- 9 edges to [[_COMMUNITY_Module tests]]
- 6 edges to [[_COMMUNITY_Paper Trading & Exits]]
- 4 edges to [[_COMMUNITY_AB Testing System]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 3 edges to [[_COMMUNITY_CLI & Preload Pipeline]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Model Weights & Ensemble Blend]]

## Top bridge nodes
- [[_conn()_1]] - degree 58, connects to 9 communities
- [[init_db()]] - degree 58, connects to 9 communities
- [[int_24]] - degree 31, connects to 6 communities
- [[count_settled_predictions()]] - degree 13, connects to 6 communities
- [[get_model_weights()]] - degree 11, connects to 5 communities