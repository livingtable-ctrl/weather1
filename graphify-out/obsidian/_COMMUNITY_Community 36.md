---
type: community
cohesion: 0.09
members: 49
---

# Community 36

**Cohesion:** 0.09 - loosely connected
**Members:** 49 nodes

## Members
- [[65 Record the difference between the desired price and the actual fill price.…]] - rationale - tracker.py
- [[65 Return aggregate price improvement statistics. Returns None if fewer than…]] - rationale - tracker.py
- [[84 Brier score broken down by dominant blend source. For each settled…]] - rationale - tracker.py
- [[Apply any pending schema migrations and update schema_version (99).]] - rationale - tracker.py
- [[Average edge and Brier score grouped by forecast horizon (days_out) (14).…]] - rationale - tracker.py
- [[Bayesian credible interval for a proportion using Beta(1+s, 1+f) posterior…]] - rationale - tracker.py
- [[Brier Skill Score (BSS) vs market baseline (11). BSS = 1 - (BS_model …]] - rationale - tracker.py
- [[Compute systematic bias for a citymonth weighted mean(our_prob -…]] - rationale - tracker.py
- [[Connection_1]] - code
- [[Dashboard Modernization Plan]] - document - docs/superpowers/plans/2026-04-10-dashboard-modernization.md
- [[Group B Data Integrity Plan]] - document - docs/superpowers/plans/2026-04-10-group-b-data-integrity.md
- [[How well-calibrated are the MARKET PRICES (not our model) Groups settled…]] - rationale - tracker.py
- [[Log an API call for audit trail and latency monitoring (69).]] - rationale - tracker.py
- [[Per-city Brier score and sample count (54, 56). Returns {city {brier, n,…]] - rationale - tracker.py
- [[Per-model MAE from ensemble_member_scores, stratified by city and season (18).…]] - rationale - tracker.py
- [[Per-quintile bias correction. Bins settled predictions by ``our_prob`` into 5…]] - rationale - tracker.py
- [[Phase 1 Testing Foundation Plan]] - document - docs/plans/2026-04-10-phase1-testing-foundation.md
- [[Phase 3 Tracker Analytics Plan]] - document - docs/plans/2026-04-10-phase3-tracker-analytics.md
- [[Phase 5 Trading Portfolio Plan]] - document - docs/plans/2026-04-10-phase5-trading-portfolio.md
- [[Phase 6 Dashboard Plan]] - document - docs/plans/2026-04-10-phase6-dashboard.md
- [[Rational approximation of the inverse normal CDF (Abramowitz & Stegun 26.2.17).]] - rationale - tracker.py
- [[Return mean Brier score per ISO week for the last `weeks` weeks. Joins settled…]] - rationale - tracker.py
- [[Sweep thresholds 0.05..0.95 (step 0.05) and find the one maximizing F1 (60).…]] - rationale - tracker.py
- [[TPFPTNFN classification of model predictions. Positive = model predicted YES…]] - rationale - tracker.py
- [[Tracker Grade Audit]] - document - docs/grade_audit/outputs/tracker.py.md
- [[_inv_normal_cdf()]] - code - tracker.py
- [[_request_with_retry Function]] - code - kalshi_client.py
- [[_run_migrations()_1]] - code - tracker.py
- [[bayesian_confidence_interval()]] - code - tracker.py
- [[brier_skill_score()]] - code - tracker.py
- [[get_bias()]] - code - tracker.py
- [[get_brier_over_time()]] - code - tracker.py
- [[get_calibration_by_city()]] - code - tracker.py
- [[get_component_attribution returns Brier score by dominant source.]] - rationale - tests/test_tracker.py
- [[get_component_attribution()]] - code - tracker.py
- [[get_confusion_matrix()]] - code - tracker.py
- [[get_edge_decay_curve()]] - code - tracker.py
- [[get_ensemble_member_accuracy()]] - code - tracker.py
- [[get_market_calibration()]] - code - tracker.py
- [[get_optimal_threshold()]] - code - tracker.py
- [[get_price_improvement_stats()]] - code - tracker.py
- [[get_quintile_bias()]] - code - tracker.py
- [[init_db()]] - code - tracker.py
- [[log_api_request()]] - code - tracker.py
- [[log_price_improvement()]] - code - tracker.py
- [[test_get_component_attribution_returns_per_source_brier()]] - code - tests/test_tracker.py
- [[test_get_component_attribution_works()]] - code - tests/test_tracker.py
- [[tracker.py_1]] - code - tracker.py
- [[web_app.py]] - code - web_app.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_36
SORT file.name ASC
```

## Connections to other communities
- 83 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 20 edges to [[_COMMUNITY_Community 59]]
- 12 edges to [[_COMMUNITY_Black Swan Halt State]]
- 9 edges to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 7 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 6 edges to [[_COMMUNITY_Community 184]]
- 5 edges to [[_COMMUNITY_Community 71]]
- 4 edges to [[_COMMUNITY_Community 52]]
- 4 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 3 edges to [[_COMMUNITY_Community 494]]
- 3 edges to [[_COMMUNITY_Community 385]]
- 2 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 2 edges to [[_COMMUNITY_Community 296]]
- 2 edges to [[_COMMUNITY_Community 582]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 226]]
- 1 edge to [[_COMMUNITY_Kelly Sizing Property-Based Tests]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 384]]
- 1 edge to [[_COMMUNITY_Community 581]]
- 1 edge to [[_COMMUNITY_Community 533]]
- 1 edge to [[_COMMUNITY_Community 580]]
- 1 edge to [[_COMMUNITY_Community 570]]
- 1 edge to [[_COMMUNITY_Community 500]]
- 1 edge to [[_COMMUNITY_Community 575]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Community 351]]
- 1 edge to [[_COMMUNITY_Community 160]]

## Top bridge nodes
- [[init_db()]] - degree 105, connects to 19 communities
- [[log_api_request()]] - degree 10, connects to 4 communities
- [[get_quintile_bias()]] - degree 14, connects to 3 communities
- [[Phase 5 Trading Portfolio Plan]] - degree 11, connects to 3 communities
- [[get_brier_over_time()]] - degree 10, connects to 3 communities