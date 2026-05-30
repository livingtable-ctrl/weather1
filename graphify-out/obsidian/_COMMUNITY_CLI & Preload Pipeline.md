---
type: community
cohesion: 0.05
members: 68
---

# CLI & Preload Pipeline

**Cohesion:** 0.05 - loosely connected
**Members:** 68 nodes

## Members
- [[Brier score = mean((our_prob - outcome)²).     Lower is better. 0.25 = random,]] - rationale - tracker.py
- [[Build SSE payload. Extracted for testability.]] - rationale - web_app.py
- [[Check if paper trading performance warrants going live.     Returns a summary d]] - rationale - paper.py
- [[Current drawdown from peak as a fraction (0.0 = no drawdown, 1.0 = total loss).]] - rationale - paper.py
- [[Daily briefing — fast single-screen summary.]] - rationale - main.py
- [[Detect when you have 2+ open positions tied to the same city within     a 3-day]] - rationale - paper.py
- [[Directional bias across open positions.     Returns YESNO counts, costs, and w]] - rationale - paper.py
- [[Fetch and cache historical data for all cities. Refreshes stale caches.]] - rationale - climatology.py
- [[For each open paper trade, re-analyze the market and check whether the     mode]] - rationale - paper.py
- [[Gather all data needed for the report.]] - rationale - pdf_report.py
- [[Generate HTML report as fallback when fpdf2 is not installed.]] - rationale - pdf_report.py
- [[Generate PDF using fpdf2.]] - rationale - pdf_report.py
- [[Generate a weekly trading summary report.     Creates a PDF if fpdf2 is install]] - rationale - pdf_report.py
- [[Mark-to-market unrealized P&L for open paper positions.     Fetches current YES]] - rationale - paper.py
- [[Paper trading commands       paper buy ticker yesno qty price]] - rationale - main.py
- [[Path_6]] - code - pdf_report.py
- [[Re-open a backed-up predictions.db, count rows in predictions table. Logs result]] - rationale - main.py
- [[Render a simple ASCII line chart. Returns a multi-line string.     Uses block c]] - rationale - main.py
- [[Replace characters outside Latin-1 so Helvetica doesn't crash.]] - rationale - pdf_report.py
- [[Return a point-in-time snapshot of the paper trading state.     Used for consis]] - rationale - paper.py
- [[Return a time-ordered list of balance snapshots derived from the trade ledger.]] - rationale - paper.py
- [[Return open paper trades whose markets close within warn_hours.     Each entry]] - rationale - paper.py
- [[Return open trades entered more than MAX_POSITION_AGE_DAYS days ago.     Each e]] - rationale - paper.py
- [[Return the highest balance ever reached (high-water mark).]] - rationale - paper.py
- [[Send an email notification via SMTP (STARTTLS).     Reads SMTP_HOST, SMTP_PORT,]] - rationale - notify.py
- [[Single-screen portfolio health view balance, positions, calibration.]] - rationale - main.py
- [[Summary stats across all settled trades.]] - rationale - paper.py
- [[Tests for P0.5 — get_state_snapshot() in paper.py and cron logging.]] - rationale - tests/test_state_consistency.py
- [[Weekly trading report generator. Produces a PDF (requires fpdf2) or HTML fallba]] - rationale - pdf_report.py
- [[_ascii_chart()]] - code - main.py
- [[_build_stream_data()]] - code - web_app.py
- [[_collect_data()]] - code - pdf_report.py
- [[_generate_html()]] - code - pdf_report.py
- [[_generate_pdf()]] - code - pdf_report.py
- [[_pdf()]] - code - pdf_report.py
- [[_send_email()]] - code - notify.py
- [[brier_score()]] - code - tracker.py
- [[check_aged_positions()]] - code - paper.py
- [[check_correlated_event_exposure()]] - code - paper.py
- [[check_expiring_trades()]] - code - paper.py
- [[check_model_exits()]] - code - paper.py
- [[cmd_brief()]] - code - main.py
- [[cmd_dashboard()]] - code - main.py
- [[cmd_paper()]] - code - main.py
- [[generate_weekly_report()]] - code - pdf_report.py
- [[get_all_trades()]] - code - paper.py
- [[get_balance()]] - code - paper.py
- [[get_balance_history()]] - code - paper.py
- [[get_factor_exposure()]] - code - paper.py
- [[get_max_drawdown_pct()]] - code - paper.py
- [[get_open_trades()]] - code - paper.py
- [[get_peak_balance()]] - code - paper.py
- [[get_performance()]] - code - paper.py
- [[get_state_snapshot balance must equal get_balance().]] - rationale - tests/test_state_consistency.py
- [[get_state_snapshot must return balance, open_trades_count, peak_balance, and sna]] - rationale - tests/test_state_consistency.py
- [[get_state_snapshot peak_balance must equal get_peak_balance().]] - rationale - tests/test_state_consistency.py
- [[get_state_snapshot()]] - code - paper.py
- [[get_unrealized_pnl_paper()]] - code - paper.py
- [[graduation_check()]] - code - paper.py
- [[int_12]] - code - main.py
- [[pdf_report.py]] - code - pdf_report.py
- [[preload_all()]] - code - climatology.py
- [[str_25]] - code - pdf_report.py
- [[test_get_state_snapshot_returns_required_keys()]] - code - tests/test_state_consistency.py
- [[test_state_consistency.py]] - code - tests/test_state_consistency.py
- [[test_state_snapshot_balance_matches_get_balance()]] - code - tests/test_state_consistency.py
- [[test_state_snapshot_peak_matches_get_peak_balance()]] - code - tests/test_state_consistency.py
- [[verify_db_backup()]] - code - main.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/CLI__Preload_Pipeline
SORT file.name ASC
```

## Connections to other communities
- 86 edges to [[_COMMUNITY_Python Types & Utilities]]
- 64 edges to [[_COMMUNITY_Paper Trading & Exits]]
- 24 edges to [[_COMMUNITY_Module frosty]]
- 8 edges to [[_COMMUNITY_Cron Scheduler]]
- 8 edges to [[_COMMUNITY_AB Testing System]]
- 5 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 3 edges to [[_COMMUNITY_Module frosty]]
- 3 edges to [[_COMMUNITY_Tracker Analytics (BrierBias)]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Portfolio Kelly & P&L]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]

## Top bridge nodes
- [[brier_score()]] - degree 27, connects to 11 communities
- [[get_open_trades()]] - degree 42, connects to 6 communities
- [[cmd_paper()]] - degree 33, connects to 6 communities
- [[get_all_trades()]] - degree 18, connects to 6 communities
- [[graduation_check()]] - degree 17, connects to 6 communities