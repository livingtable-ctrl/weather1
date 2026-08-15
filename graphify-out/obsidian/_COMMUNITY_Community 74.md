---
type: community
cohesion: 0.12
members: 32
---

# Community 74

**Cohesion:** 0.12 - loosely connected
**Members:** 32 nodes

## Members
- [[0% baseline win rate (all losses) → cap = 1, not max_positions. The wins==0…]] - rationale - tests/test_sameday_reserve.py
- [[Band with no historical data → treated as baseline → cap = MAX.]] - rationale - tests/test_sameday_reserve.py
- [[Dynamic enabled but band-stats baseline  threshold → full cap, feature stays…]] - rationale - tests/test_sameday_reserve.py
- [[Dynamic gate must key off get_sameday_band_stats' own baseline total, not…]] - rationale - tests/test_sameday_reserve.py
- [[Effective same-day slot cap for the current UTC hour. Dynamic mode scales cap…]] - rationale - order_executor.py
- [[If count_settled_sameday_predictions raises, return full cap (fail open).]] - rationale - tests/test_sameday_reserve.py
- [[Return a fake datetime class that reports the given UTC hour.]] - rationale - tests/test_sameday_reserve.py
- [[SAME_DAY_RESERVE_SLOTS=0 → full cap, no DB call.]] - rationale - tests/test_sameday_reserve.py
- [[Slots  0 but settled  threshold → full cap (not enough data).]] - rationale - tests/test_sameday_reserve.py
- [[Slots  0, threshold met, hour  cutoff → cap reduced.]] - rationale - tests/test_sameday_reserve.py
- [[Slots  0, threshold met, hour = cutoff → full cap released.]] - rationale - tests/test_sameday_reserve.py
- [[Sparse band (N=3) → shrinkage pulls toward baseline, moderate reduction.]] - rationale - tests/test_sameday_reserve.py
- [[Strong band win rate (baseline) → cap clamped to MAX.]] - rationale - tests/test_sameday_reserve.py
- [[Tests for the same-day slot reservation system…]] - rationale - tests/test_sameday_reserve.py
- [[Weak band with enough data → cap materially reduced.]] - rationale - tests/test_sameday_reserve.py
- [[_fake_dt()]] - code - tests/test_sameday_reserve.py
- [[_patch_dynamic_env()]] - code - tests/test_sameday_reserve.py
- [[_patch_env()]] - code - tests/test_sameday_reserve.py
- [[_sameday_effective_cap()]] - code - order_executor.py
- [[test_db_error_fails_open()]] - code - tests/test_sameday_reserve.py
- [[test_dynamic_gate_ignores_tracker_prediction_count()]] - code - tests/test_sameday_reserve.py
- [[test_dynamic_insufficient_samples()]] - code - tests/test_sameday_reserve.py
- [[test_dynamic_sparse_band()]] - code - tests/test_sameday_reserve.py
- [[test_dynamic_strong_band()]] - code - tests/test_sameday_reserve.py
- [[test_dynamic_unknown_band()]] - code - tests/test_sameday_reserve.py
- [[test_dynamic_weak_band()]] - code - tests/test_sameday_reserve.py
- [[test_dynamic_zero_baseline_wins_returns_minimum()]] - code - tests/test_sameday_reserve.py
- [[test_feature_disabled_returns_max()]] - code - tests/test_sameday_reserve.py
- [[test_reservation_active_before_cutoff()]] - code - tests/test_sameday_reserve.py
- [[test_reservation_released_at_cutoff()]] - code - tests/test_sameday_reserve.py
- [[test_sameday_reserve.py]] - code - tests/test_sameday_reserve.py
- [[test_threshold_not_met_returns_max()]] - code - tests/test_sameday_reserve.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_74
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 40]]
- 2 edges to [[_COMMUNITY_Community 52]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 228]]

## Top bridge nodes
- [[_sameday_effective_cap()]] - degree 22, connects to 7 communities
- [[test_sameday_reserve.py]] - degree 19, connects to 2 communities