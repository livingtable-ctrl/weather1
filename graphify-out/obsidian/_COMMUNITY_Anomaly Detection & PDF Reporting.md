---
type: community
cohesion: 0.02
members: 100
---

# Anomaly Detection & PDF Reporting

**Cohesion:** 0.02 - loosely connected
**Members:** 100 nodes

## Members
- [[dot-check()]] - code - trading_gates.py
- [[apipaper-order endpoint]] - code - web_app.py
- [[Clamp a `.last_calibration_count` sentinel value against today's live…]] - rationale - tracker.py
- [[Compute average feature values for winning vs losing trades. Returns a dict…]] - rationale - feature_importance.py
- [[Compute worst-case P&L under a named stress scenario. Returns {scenario,…]] - rationale - monte_carlo.py
- [[For each simulation randomly resolve each open trade as winloss using the…]] - rationale - monte_carlo.py
- [[Gather all data needed for the report.]] - rationale - pdf_report.py
- [[Generate HTML report as fallback when fpdf2 is not installed.]] - rationale - pdf_report.py
- [[Generate PDF using fpdf2.]] - rationale - pdf_report.py
- [[Generate a weekly trading summary report. Creates a PDF if fpdf2 is installed,…]] - rationale - pdf_report.py
- [[I2 _DATA_LOCK RMW Discipline]] - document - docs/grade_audit/outputs
- [[I4 24h Settlement Gate]] - document - docs/grade_audit/outputs
- [[I8 Drawdown Snapshot vs Raw Balance]] - document - docs/grade_audit/outputs
- [[Kalshi Weather Trading Bot README]] - document - README.md
- [[Load paper trades and run anomaly detection. Log any alerts found. Returns…]] - rationale - alerts.py
- [[Path]] - code
- [[Phase 2 Batch I Regression Tests]] - code - tests/test_phase2_batch_i.py
- [[Phase 2 Batch I regression tests P2-28P2-29P2-32P2-33 — paper.py financial…]] - rationale - tests/test_phase2_batch_i.py
- [[Pre-trade live safety gate — single call point before every live order.]] - rationale - trading_gates.py
- [[Prompt for a price; loops on emptyinvalid input, 'q' to cancel.]] - rationale - main.py
- [[Prompt to paper-buy a ticker directly after seeing analyze output.]] - rationale - main.py
- [[Raise RuntimeError if any live trading gate is not satisfied. Pass the `client`…]] - rationale - trading_gates.py
- [[Replace characters outside Latin-1 so Helvetica doesn't crash.]] - rationale - pdf_report.py
- [[Return (allowed, reason). Fail-closed any exception → blocked. `client` should…]] - rationale - trading_gates.py
- [[Return True if today's P&L is worse than -MAX_DAILY_LOSS_PCT  current balance.…]] - rationale - paper.py
- [[Return True only when HOURLY_TRADING_ENABLED=1 AND = 20 settled hourly…]] - rationale - weather_markets.py
- [[Return True only when HURRICANE_NEXT_EVENT_TRADING_ENABLED=1 AND = 20 settled…]] - rationale - weather_markets.py
- [[Return True only when HURRICANE_TRADING_ENABLED=1 AND = 20 settled hurricane-…]] - rationale - weather_markets.py
- [[Return True only when RAIN_TRADING_ENABLED=1 AND = 20 settled monthly-rain…]] - rationale - weather_markets.py
- [[Return True only when SNOW_TRADING_ENABLED=1 AND = 20 settled monthly-snow…]] - rationale - weather_markets.py
- [[Return True only when STORM_ORDER_TRADING_ENABLED=1 AND = 20 settled storm-…]] - rationale - weather_markets.py
- [[Return the number of settled multi-day predictions counted toward the live-…]] - rationale - tracker.py
- [[Single source of truth for the TRADING_PAUSED kill-switch. Was previously re-…]] - rationale - utils.py
- [[Sum of multi-day paper trade costs placed today (UTC date). Used for daily…]] - rationale - order_executor.py
- [[System Priority Checklist]] - document - docs/PRIORITY-CHECKLIST.md
- [[Tests for P0.5 — get_state_snapshot() in paper.py and cron logging.]] - rationale - tests/test_state_consistency.py
- [[True for any real Kalshi hurricanetropical-storm ticker family -- see…]] - rationale - weather_markets.py
- [[True only for the 1 storm-order series with a real probability model…]] - rationale - weather_markets.py
- [[True only for the 2 time-to-next-event series with a real probability model…]] - rationale - weather_markets.py
- [[True only for the 5 season-total hurricanetropical-storm-count series with a…]] - rationale - weather_markets.py
- [[Weekly trading report generator. Produces a PDF (requires fpdf2) or HTML…]] - rationale - pdf_report.py
- [[_analyze_once()]] - code - main.py
- [[_auto_place_trades() Dedup Pipeline AC1-4 Pass (710)]] - document - docs/grade_audit/outputs/order_executor.py.md
- [[_collect_data Function]] - code - pdf_report.py
- [[_collect_data()]] - code - pdf_report.py
- [[_daily_paper_spend()]] - code - order_executor.py
- [[_generate_html()]] - code - pdf_report.py
- [[_generate_pdf()]] - code - pdf_report.py
- [[_hourly_gates_active()]] - code - weather_markets.py
- [[_hurricane_count_gates_active()]] - code - weather_markets.py
- [[_hurricane_next_event_gates_active()]] - code - weather_markets.py
- [[_pdf()]] - code - pdf_report.py
- [[_poll_pending_orders() DEBUGprint Instead of WARNING (610)]] - document - docs/grade_audit/outputs/order_executor.py.md
- [[_prompt_price()]] - code - main.py
- [[_quick_paper_buy()]] - code - main.py
- [[_rain_gates_active()]] - code - weather_markets.py
- [[_snow_gates_active()]] - code - weather_markets.py
- [[_storm_order_gates_active()]] - code - weather_markets.py
- [[clamp_last_calibration_count()]] - code - tracker.py
- [[cmd_analyze()]] - code - main.py
- [[cmd_balance Function]] - code - output_formatters.py
- [[cmd_cron must log a state snapshot line on each run.]] - rationale - tests/test_state_consistency.py
- [[cmd_history Function]] - code - output_formatters.py
- [[count_settled_predictions()]] - code - tracker.py
- [[drawdown_scaling_factor() Tiered Kelly Scaling (910)]] - document - docs/grade_audit/outputs/paper.py.md
- [[generate_weekly_report()]] - code - pdf_report.py
- [[generate_weekly_report() Silent .pdf→.html Switch (710)]] - document - docs/grade_audit/outputs/pdf_report.py.md
- [[get_feature_summary()]] - code - feature_importance.py
- [[get_state_snapshot balance must equal get_balance().]] - rationale - tests/test_state_consistency.py
- [[get_state_snapshot must return balance, open_trades_count, peak_balance, and…]] - rationale - tests/test_state_consistency.py
- [[get_state_snapshot peak_balance must equal get_peak_balance().]] - rationale - tests/test_state_consistency.py
- [[is_daily_loss_halted()]] - code - paper.py
- [[is_hurricane_count_ticker()]] - code - weather_markets.py
- [[is_hurricane_next_event_ticker()]] - code - weather_markets.py
- [[is_hurricane_ticker()]] - code - weather_markets.py
- [[is_storm_order_ticker()]] - code - weather_markets.py
- [[is_trading_paused()]] - code - utils.py
- [[order_executor.py]] - code - order_executor.py
- [[order_executor.py File Grade median 710]] - document - docs/grade_audit/outputs/order_executor.py.md
- [[order_executor.py Grade Audit]] - document - docs/grade_audit/outputs/order_executor.py.md
- [[order_executor.py — Automated order placement and lifecycle management.…]] - rationale - order_executor.py
- [[paper.py File Grade median 7.510]] - document - docs/grade_audit/outputs/paper.py.md
- [[paper.py Grade Audit]] - document - docs/grade_audit/outputs/paper.py.md
- [[pdf_report.py]] - code - pdf_report.py
- [[pdf_report.py File Grade median 710, no red flags]] - document - docs/grade_audit/outputs/pdf_report.py.md
- [[pdf_report.py Grade Audit]] - document - docs/grade_audit/outputs/pdf_report.py.md
- [[place_paper_order()]] - code - order_executor.py
- [[pre_live_trade_check()]] - code - trading_gates.py
- [[run_anomaly_check()]] - code - alerts.py
- [[run_stress_test Function]] - code - monte_carlo.py
- [[run_stress_test()]] - code - monte_carlo.py
- [[settle_paper_trade() I4 Violation Missing 24h Gate (810)]] - document - docs/grade_audit/outputs/paper.py.md
- [[simulate_portfolio()]] - code - monte_carlo.py
- [[test_cmd_cron_logs_state_snapshot()]] - code - tests/test_state_consistency.py
- [[test_get_state_snapshot_returns_required_keys()]] - code - tests/test_state_consistency.py
- [[test_state_consistency.py]] - code - tests/test_state_consistency.py
- [[test_state_snapshot_balance_matches_get_balance()]] - code - tests/test_state_consistency.py
- [[test_state_snapshot_peak_matches_get_peak_balance()]] - code - tests/test_state_consistency.py
- [[trading_gates.py]] - code - trading_gates.py
- [[undo_last_trade() RF2 No _DATA_LOCK, Race Condition (510)]] - document - docs/grade_audit/outputs/paper.py.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Anomaly_Detection__PDF_Reporting
SORT file.name ASC
```

## Connections to other communities
- 28 edges to [[_COMMUNITY_Community 693]]
- 23 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 21 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 14 edges to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 14 edges to [[_COMMUNITY_Community 40]]
- 13 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 9 edges to [[_COMMUNITY_Community 32]]
- 8 edges to [[_COMMUNITY_Community 87]]
- 8 edges to [[_COMMUNITY_Black Swan Halt State]]
- 7 edges to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 6 edges to [[_COMMUNITY_Community 63]]
- 4 edges to [[_COMMUNITY_Community 145]]
- 4 edges to [[_COMMUNITY_Community 45]]
- 4 edges to [[_COMMUNITY_Community 223]]
- 4 edges to [[_COMMUNITY_Community 67]]
- 3 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 3 edges to [[_COMMUNITY_Community 189]]
- 3 edges to [[_COMMUNITY_Community 246]]
- 3 edges to [[_COMMUNITY_Community 328]]
- 3 edges to [[_COMMUNITY_Community 110]]
- 3 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 3 edges to [[_COMMUNITY_Community 183]]
- 2 edges to [[_COMMUNITY_Community 33]]
- 2 edges to [[_COMMUNITY_Community 481]]
- 2 edges to [[_COMMUNITY_Community 208]]
- 2 edges to [[_COMMUNITY_Community 94]]
- 2 edges to [[_COMMUNITY_Community 181]]
- 2 edges to [[_COMMUNITY_Community 57]]
- 2 edges to [[_COMMUNITY_Community 52]]
- 2 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 2 edges to [[_COMMUNITY_Community 134]]
- 2 edges to [[_COMMUNITY_Community 248]]
- 2 edges to [[_COMMUNITY_Community 389]]
- 2 edges to [[_COMMUNITY_Community 198]]
- 2 edges to [[_COMMUNITY_Community 215]]
- 2 edges to [[_COMMUNITY_Kelly Sizing Property-Based Tests]]
- 2 edges to [[_COMMUNITY_Community 74]]
- 1 edge to [[_COMMUNITY_Community 405]]
- 1 edge to [[_COMMUNITY_Community 482]]
- 1 edge to [[_COMMUNITY_Community 520]]
- 1 edge to [[_COMMUNITY_Community 594]]
- 1 edge to [[_COMMUNITY_Community 327]]
- 1 edge to [[_COMMUNITY_Community 417]]
- 1 edge to [[_COMMUNITY_Community 565]]
- 1 edge to [[_COMMUNITY_Community 50]]
- 1 edge to [[_COMMUNITY_Community 56]]
- 1 edge to [[_COMMUNITY_Community 167]]
- 1 edge to [[_COMMUNITY_Community 36]]
- 1 edge to [[_COMMUNITY_Community 237]]
- 1 edge to [[_COMMUNITY_Community 174]]
- 1 edge to [[_COMMUNITY_Community 111]]
- 1 edge to [[_COMMUNITY_Community 144]]
- 1 edge to [[_COMMUNITY_Weather Probability Math Tests]]
- 1 edge to [[_COMMUNITY_Community 157]]
- 1 edge to [[_COMMUNITY_Community 158]]
- 1 edge to [[_COMMUNITY_Community 159]]
- 1 edge to [[_COMMUNITY_Community 164]]
- 1 edge to [[_COMMUNITY_Community 252]]
- 1 edge to [[_COMMUNITY_Community 296]]
- 1 edge to [[_COMMUNITY_Community 300]]
- 1 edge to [[_COMMUNITY_Community 329]]
- 1 edge to [[_COMMUNITY_Community 500]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 85]]
- 1 edge to [[_COMMUNITY_Community 359]]
- 1 edge to [[_COMMUNITY_Community 125]]
- 1 edge to [[_COMMUNITY_Kelly City Multiplier & Edge Realization]]
- 1 edge to [[_COMMUNITY_Community 180]]
- 1 edge to [[_COMMUNITY_Community 93]]
- 1 edge to [[_COMMUNITY_Community 590]]

## Top bridge nodes
- [[order_executor.py]] - degree 97, connects to 39 communities
- [[simulate_portfolio()]] - degree 25, connects to 11 communities
- [[Phase 2 Batch I Regression Tests]] - degree 13, connects to 9 communities
- [[run_anomaly_check()]] - degree 13, connects to 6 communities
- [[_rain_gates_active()]] - degree 9, connects to 6 communities