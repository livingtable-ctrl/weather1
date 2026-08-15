---
type: community
cohesion: 0.06
members: 55
---

# Black Swan Halt State

**Cohesion:** 0.06 - loosely connected
**Members:** 55 nodes

## Members
- [[Apply color to a signal string based on strength.]] - rationale - colors.py
- [[Brier score grouped by ISO week of the MARKET DATE for the last N weeks. Groups…]] - rationale - tracker.py
- [[CITY_WFO_OFFICE Dict]] - code - nws_afd.py
- [[Color a probability bright if extreme (high confidence), dim if near 50%.]] - rationale - colors.py
- [[Color an edge value green if strong positive, red if strong negative, yellow…]] - rationale - colors.py
- [[Color helpers for terminal output using colorama. Gracefully falls back to…]] - rationale - colors.py
- [[Export prediction history with outcomes to CSV. Returns row count.]] - rationale - tracker.py
- [[Fetch and return the current AFD's narrative reasoning text for a city.…]] - rationale - nws_afd.py
- [[KalshiClient]] - code - kalshi_client.py
- [[Output formatting functions extracted from main.py. All functions in this…]] - rationale - output_formatters.py
- [[P10.2 Remove black swan state file (called by cmd_resume). Returns True if…]] - rationale - alerts.py
- [[P10.2 Return active black swan state if any, else None.]] - rationale - alerts.py
- [[Return per-city, per-source reliability over the last N days. Returns {city…]] - rationale - tracker.py
- [[Return recent predictions with outcomes where available.]] - rationale - tracker.py
- [[Returns (brier, n) for the rolling window in a single query. Use this at…]] - rationale - tracker.py
- [[Show P&L attribution by signal source.]] - rationale - output_formatters.py
- [[Tests for menu UX fixes.]] - rationale - tests/test_menu_ux.py
- [[bold()]] - code - colors.py
- [[brier_score_rolling_with_n()]] - code - tracker.py
- [[clear_black_swan_state()]] - code - alerts.py
- [[cmd_balance()]] - code - output_formatters.py
- [[cmd_history()]] - code - output_formatters.py
- [[cmd_pnl_attribution()]] - code - output_formatters.py
- [[cmd_positions()]] - code - output_formatters.py
- [[colors.py]] - code - colors.py
- [[colors.py File Grade Good, median ~810, no TIER1]] - document - docs/grade_audit/outputs/colors.py.md
- [[colors.py Grade Audit]] - document - docs/grade_audit/outputs/colors.py.md
- [[cyan()]] - code - colors.py
- [[dim()]] - code - colors.py
- [[edge_color()]] - code - colors.py
- [[edge_color() Dead Branch Bug (610)]] - document - docs/grade_audit/outputs/colors.py.md
- [[export_predictions_csv()]] - code - tracker.py
- [[fetch_afd_discussion Function]] - code - nws_afd.py
- [[fetch_afd_discussion()]] - code - nws_afd.py
- [[get_black_swan_status()]] - code - alerts.py
- [[get_calibration_trend()]] - code - tracker.py
- [[get_history()]] - code - tracker.py
- [[get_source_reliability()]] - code - tracker.py
- [[green()]] - code - colors.py
- [[liquidity_color()]] - code - colors.py
- [[main._liquidation_price]] - code - main.py
- [[main.py File Grade median T1 710]] - document - docs/grade_audit/outputs/main.py.md
- [[main.py Grade Audit]] - document - docs/grade_audit/outputs/main.py.md
- [[output_formatters.py]] - code - output_formatters.py
- [[output_formatters.py File Grade median 510]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[output_formatters.py Grade Audit]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[prob_color()]] - code - colors.py
- [[red()]] - code - colors.py
- [[signal_color()]] - code - colors.py
- [[signal_color() STRONGBUY Redundant Branches (710)]] - document - docs/grade_audit/outputs/colors.py.md
- [[test_log_rotation.py]] - code - tests/test_log_rotation.py
- [[test_menu_ux.py]] - code - tests/test_menu_ux.py
- [[test_setup_logging_installs_rotating_handler()]] - code - tests/test_log_rotation.py
- [[white()]] - code - colors.py
- [[yellow()]] - code - colors.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Black_Swan_Halt_State
SORT file.name ASC
```

## Connections to other communities
- 29 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 17 edges to [[_COMMUNITY_Community 86]]
- 16 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 12 edges to [[_COMMUNITY_Community 36]]
- 8 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 7 edges to [[_COMMUNITY_Community 57]]
- 7 edges to [[_COMMUNITY_Community 298]]
- 4 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 4 edges to [[_COMMUNITY_Shadow Predictions Auto-Place Trades]]
- 3 edges to [[_COMMUNITY_Community 143]]
- 3 edges to [[_COMMUNITY_Community 351]]
- 3 edges to [[_COMMUNITY_Community 195]]
- 2 edges to [[_COMMUNITY_Community 53]]
- 2 edges to [[_COMMUNITY_Community 417]]
- 2 edges to [[_COMMUNITY_Community 44]]
- 2 edges to [[_COMMUNITY_Community 94]]
- 2 edges to [[_COMMUNITY_Community 182]]
- 2 edges to [[_COMMUNITY_Community 384]]
- 2 edges to [[_COMMUNITY_Community 71]]
- 2 edges to [[_COMMUNITY_Community 184]]
- 2 edges to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Community 84]]
- 1 edge to [[_COMMUNITY_Community 548]]
- 1 edge to [[_COMMUNITY_Community 356]]
- 1 edge to [[_COMMUNITY_Community 283]]
- 1 edge to [[_COMMUNITY_Community 373]]
- 1 edge to [[_COMMUNITY_Community 223]]
- 1 edge to [[_COMMUNITY_Community 80]]
- 1 edge to [[_COMMUNITY_Community 305]]
- 1 edge to [[_COMMUNITY_Community 551]]
- 1 edge to [[_COMMUNITY_Community 592]]
- 1 edge to [[_COMMUNITY_Community 593]]
- 1 edge to [[_COMMUNITY_Community 599]]
- 1 edge to [[_COMMUNITY_Community 68]]

## Top bridge nodes
- [[KalshiClient]] - degree 68, connects to 18 communities
- [[output_formatters.py]] - degree 38, connects to 10 communities
- [[cmd_history()]] - degree 21, connects to 5 communities
- [[colors.py]] - degree 21, connects to 4 communities
- [[test_menu_ux.py]] - degree 6, connects to 4 communities