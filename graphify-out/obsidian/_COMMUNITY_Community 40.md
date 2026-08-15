---
type: community
cohesion: 0.06
members: 42
---

# Community 40

**Cohesion:** 0.06 - loosely connected
**Members:** 42 nodes

## Members
- [[Bool wrapper around trading_gates.pre_live_trade_check() for the micro-live…]] - rationale - order_executor.py
- [[Build the tracker.log_prediction() keyword args shared by the real post-…]] - rationale - order_executor.py
- [[Compute the run-to-run trend signal from an analyze_trade() result dict.…]] - rationale - tracker.py
- [[Extract (ticker, city, target_date, analysis_dict, market_dict) from an opp…]] - rationale - order_executor.py
- [[Live Trading Runbook]] - document - LIVE_TRADING_RUNBOOK.md
- [[LiveTradingGate class]] - code - trading_gates.py
- [[Log predictions for signals that passed analysis but were never placed…]] - rationale - order_executor.py
- [[P0-10 execution_log pre-log ordering for paper trades. Verifies that a…]] - rationale - tests/test_p0_10_paper_prelog.py
- [[P0-2 LiveTradingGate must block live orders when graduationsafety gates fail.]] - rationale - tests/test_trading_gates.py
- [[P10.1 Detect slow Brier score degradation over time. Splits available weekly…]] - rationale - tracker.py
- [[Paper Trading Ledger Module]] - code - paper.py
- [[Patch every external call cmd_cron makes so it can run without network.]] - rationale - tests/test_main_cron_smoke.py
- [[Return a string identifier for the current NWS forecast cycle. NWS model runs…]] - rationale - order_executor.py
- [[Shared Position Read-Model Module]] - code - positions.py
- [[Smoke tests for cmd_cron — the main production execution path. Tests the guards…]] - rationale - tests/test_main_cron_smoke.py
- [[Tests for 3 approved trading improvements 1. MAX_CONCURRENT_POSITIONS cap (20)…]] - rationale - tests/test_trade_improvements.py
- [[TradeCycleResult dataclass]] - code - trade_cycle.py
- [[_DEFAULT_CORRELATIONS Dict]] - code - monte_carlo.py
- [[_current_forecast_cycle()]] - code - order_executor.py
- [[_log_shadow_predictions()]] - code - order_executor.py
- [[_micro_live_gate_ok()]] - code - order_executor.py
- [[_prediction_kwargs_from_analysis()]] - code - order_executor.py
- [[_unpack_opp()]] - code - order_executor.py
- [[backtest.py_1]] - code - backtest.py
- [[cron.py_1]] - code - cron.py
- [[date_4]] - code
- [[detect_brier_drift()]] - code - tracker.py
- [[fixture_9]] - code
- [[format_brier_alert() output should include actionable next steps.]] - rationale - tests/test_main_cron_smoke.py
- [[get_forecast_run_trend_from_analysis()]] - code - tracker.py
- [[main._auto_place_trades]] - code - main.py
- [[main.py CLI Entrypoint]] - code - main.py
- [[minimal_mocks()]] - code - tests/test_main_cron_smoke.py
- [[order_executor.py_1]] - code - order_executor.py
- [[safe_io.py_1]] - code - safe_io.py
- [[test_brier_alert_includes_guidance()]] - code - tests/test_main_cron_smoke.py
- [[test_execution_proof.py_1]] - code - tests/test_execution_proof.py
- [[test_main_cron_smoke.py]] - code - tests/test_main_cron_smoke.py
- [[test_p0_10_paper_prelog.py]] - code - tests/test_p0_10_paper_prelog.py
- [[test_trade_improvements.py]] - code - tests/test_trade_improvements.py
- [[test_trading_gates.py]] - code - tests/test_trading_gates.py
- [[trade_cycle.py (headless trade-cycle engine)]] - code - trade_cycle.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_40
SORT file.name ASC
```

## Connections to other communities
- 14 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 11 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 7 edges to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 5 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 4 edges to [[_COMMUNITY_Community 183]]
- 4 edges to [[_COMMUNITY_Community 244]]
- 3 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 3 edges to [[_COMMUNITY_Community 340]]
- 3 edges to [[_COMMUNITY_Community 54]]
- 3 edges to [[_COMMUNITY_Community 97]]
- 3 edges to [[_COMMUNITY_Community 52]]
- 3 edges to [[_COMMUNITY_Community 92]]
- 2 edges to [[_COMMUNITY_Community 45]]
- 2 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 2 edges to [[_COMMUNITY_Community 424]]
- 2 edges to [[_COMMUNITY_Community 125]]
- 2 edges to [[_COMMUNITY_Community 50]]
- 2 edges to [[_COMMUNITY_Community 74]]
- 2 edges to [[_COMMUNITY_Community 71]]
- 1 edge to [[_COMMUNITY_Community 346]]
- 1 edge to [[_COMMUNITY_Community 444]]
- 1 edge to [[_COMMUNITY_Community 470]]
- 1 edge to [[_COMMUNITY_Community 526]]
- 1 edge to [[_COMMUNITY_Community 550]]
- 1 edge to [[_COMMUNITY_Community 573]]
- 1 edge to [[_COMMUNITY_Community 144]]
- 1 edge to [[_COMMUNITY_Community 159]]
- 1 edge to [[_COMMUNITY_Community 227]]
- 1 edge to [[_COMMUNITY_Community 296]]
- 1 edge to [[_COMMUNITY_Community 36]]
- 1 edge to [[_COMMUNITY_Community 67]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 146]]
- 1 edge to [[_COMMUNITY_Community 85]]
- 1 edge to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Community 196]]
- 1 edge to [[_COMMUNITY_Community 109]]
- 1 edge to [[_COMMUNITY_Community 180]]
- 1 edge to [[_COMMUNITY_Community 75]]
- 1 edge to [[_COMMUNITY_Community 98]]
- 1 edge to [[_COMMUNITY_Community 174]]
- 1 edge to [[_COMMUNITY_Community 176]]
- 1 edge to [[_COMMUNITY_Community 220]]
- 1 edge to [[_COMMUNITY_Community 237]]
- 1 edge to [[_COMMUNITY_Safe IO CRC Validation Tests]]
- 1 edge to [[_COMMUNITY_Community 299]]
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 1 edge to [[_COMMUNITY_Community 228]]
- 1 edge to [[_COMMUNITY_Kelly City Multiplier & Edge Realization]]

## Top bridge nodes
- [[Paper Trading Ledger Module]] - degree 16, connects to 11 communities
- [[main.py CLI Entrypoint]] - degree 17, connects to 9 communities
- [[order_executor.py_1]] - degree 15, connects to 9 communities
- [[_current_forecast_cycle()]] - degree 13, connects to 8 communities
- [[test_main_cron_smoke.py]] - degree 11, connects to 6 communities