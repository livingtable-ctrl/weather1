---
type: community
cohesion: 0.07
members: 28
---

# Community 92

**Cohesion:** 0.07 - loosely connected
**Members:** 28 nodes

## Members
- [[After a paper position settles, was_traded_today() must still block re-entry on…]] - rationale - tests/test_trading.py
- [[Should not place trades when MAX_DAILY_SPEND is already reached.]] - rationale - tests/test_trading.py
- [[Tests for Phase 5 trading improvements 49 dynamic correlation matrix 50…]] - rationale - tests/test_trading.py
- [[With many samples the shrinkage factor is negligible — bias stays near its raw…]] - rationale - tests/test_trading.py
- [[With only min_samples rows, the returned bias must be strictly smaller in…]] - rationale - tests/test_trading.py
- [[_auto_place_trades must log paper orders to execution_log so was_traded_today()…]] - rationale - tests/test_trading.py
- [[_auto_place_trades with cap=20.0 should call kelly_quantity with cap=20.0.]] - rationale - tests/test_trading.py
- [[check_model_exits must include 'market' key in each recommendation (L3-B).]] - rationale - tests/test_trading.py
- [[cmd_readiness returns False and prints FAIL when Brier  0.20.]] - rationale - tests/test_trading.py
- [[cmd_readiness returns True only when all 4 gates pass.]] - rationale - tests/test_trading.py
- [[cmd_watch must call close_paper_early via _check_early_exits, not just print…]] - rationale - tests/test_trading.py
- [[get_quintile_bias must ignore rows where city IS NULL even when no city filter…]] - rationale - tests/test_trading.py
- [[log_prediction(city=None) must write nothing to the DB (L4-B).]] - rationale - tests/test_trading.py
- [[oppci_adjusted_kelly present but None must not raise TypeError from…]] - rationale - tests/test_trading.py
- [[test_auto_place_trades_logs_paper_order_to_execution_log()]] - code - tests/test_trading.py
- [[test_auto_place_trades_med_tier_uses_20_cap()]] - code - tests/test_trading.py
- [[test_auto_place_trades_none_ci_kelly_falls_back_without_crashing()]] - code - tests/test_trading.py
- [[test_auto_place_trades_stops_at_daily_spend_cap()]] - code - tests/test_trading.py
- [[test_check_model_exits_includes_market_in_rec()]] - code - tests/test_trading.py
- [[test_cmd_readiness_fails_when_brier_above_threshold()]] - code - tests/test_trading.py
- [[test_cmd_readiness_passes_when_all_gates_clear()]] - code - tests/test_trading.py
- [[test_cmd_watch_auto_executes_early_exits()]] - code - tests/test_trading.py
- [[test_get_bias_near_full_strength_for_large_samples()]] - code - tests/test_trading.py
- [[test_get_bias_shrinks_toward_zero_for_small_samples()]] - code - tests/test_trading.py
- [[test_get_quintile_bias_excludes_null_city_rows()]] - code - tests/test_trading.py
- [[test_log_prediction_with_null_city_is_noop()]] - code - tests/test_trading.py
- [[test_trading.py]] - code - tests/test_trading.py
- [[test_was_traded_today_blocks_reentry_after_settlement()]] - code - tests/test_trading.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_92
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Community 347]]
- 3 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 3 edges to [[_COMMUNITY_Community 527]]
- 3 edges to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 631]]
- 1 edge to [[_COMMUNITY_Community 383]]
- 1 edge to [[_COMMUNITY_Community 577]]
- 1 edge to [[_COMMUNITY_Community 489]]
- 1 edge to [[_COMMUNITY_Community 557]]
- 1 edge to [[_COMMUNITY_Community 320]]
- 1 edge to [[_COMMUNITY_Community 240]]
- 1 edge to [[_COMMUNITY_Community 445]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 52]]

## Top bridge nodes
- [[test_trading.py]] - degree 40, connects to 15 communities
- [[test_auto_place_trades_stops_at_daily_spend_cap()]] - degree 3, connects to 1 community