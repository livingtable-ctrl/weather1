---
type: community
cohesion: 0.04
members: 108
---

# Paper Trading & Exits

**Cohesion:** 0.04 - loosely connected
**Members:** 108 nodes

## Members
- [[101 Remove stray .paper_trades_ temp files left by interrupted atomic writes.]] - rationale - paper.py
- [[44 Scale down Kelly if we already hold an aging position in this ticker.]] - rationale - paper.py
- [[45 Return True if on a 3+ consecutive loss streak AND total streak losses]] - rationale - paper.py
- [[50 Compute a slippage-adjusted fill price for a market order.      Uses the]] - rationale - paper.py
- [[50 Estimate price slippage for a given order quantity.      Returns 0.0 for]] - rationale - paper.py
- [[51 Portfolio Kelly covariance adjustment.      Computes the marginal increas]] - rationale - paper.py
- [[73 74 Simulate a partial fill in a thin market.      If quantity = 20% of]] - rationale - paper.py
- [[Annualised Sharpe ratio over the last window_days calendar days.     Uses daily]] - rationale - paper.py
- [[Atomic JSON write with retry and fallback location.]] - rationale - safe_io.py
- [[AtomicWriteError]] - code - safe_io.py
- [[Check paper_trades.json for structural corruption. Returns a list of error strin]] - rationale - paper.py
- [[Check whether adding qty contracts at price would breach position limits.     C]] - rationale - paper.py
- [[Close an open paper trade at current market price instead of waiting for settlem]] - rationale - paper.py
- [[Composite 0-100 score. Higher = more confidentgreedy.     Components       -]] - rationale - paper.py
- [[Compute full SHA-256 checksum (64 hex chars) of payload excluding '_checksum' ke]] - rationale - paper.py
- [[Decompose P&L into model-edge contribution vs luck (residual).     Expected P&L]] - rationale - paper.py
- [[Export all paper trades to CSV. Returns number of rows written.]] - rationale - paper.py
- [[Export settled trades in Schedule D  capital gains format.     Columns Descri]] - rationale - paper.py
- [[Gross profit  gross loss from settled trades.      Profit factor  1.0 means]] - rationale - paper.py
- [[Log per-model forecast accuracy after settlement for _dynamic_model_weights().]] - rationale - paper.py
- [[P0-4 exposure denominator scales with balance so caps stay proportional.     F]] - rationale - paper.py
- [[Paper trading ledger — simulates trades without using real money. Stored in dat]] - rationale - paper.py
- [[Path_7]] - code - safe_io.py
- [[Place a paper trade. Deducts quantity  entry_price from balance.     exit_targ]] - rationale - paper.py
- [[Prompt to paper-buy a ticker directly after seeing analyze output.]] - rationale - main.py
- [[Record settlement for a paper trade. YES wins if outcome_yes=True.     Returns]] - rationale - paper.py
- [[Return True if today's P&L is worse than -MAX_DAILY_LOSS_PCT  current balance.]] - rationale - paper.py
- [[Return a 0.0–1.0 Kelly multiplier based on drawdown from peak (high-water mark).]] - rationale - paper.py
- [[Return a 0.5–1.0 multiplier to reduce Kelly sizing based on market liquidity.]] - rationale - paper.py
- [[Return fraction of current balance committed to open trades for this ticker (47]] - rationale - paper.py
- [[Return the dollar amount to bet.     120 Respects STRATEGY env var       ke]] - rationale - paper.py
- [[Return the fraction of current balance committed to open trades for this city +]] - rationale - paper.py
- [[Return the fraction of current balance in open trades for this city + date + dir]] - rationale - paper.py
- [[Return the main project root directory, resolving git worktrees correctly.]] - rationale - safe_io.py
- [[Return the total fraction of STARTING_BALANCE committed to open trades     in c]] - rationale - paper.py
- [[Return the total fraction of current balance committed across all open trades.]] - rationale - paper.py
- [[Return tickers whose break-even stop has triggered.      Fires when peak_prof]] - rationale - paper.py
- [[Returns (win, N) or (loss, N) or (none, 0) based on the last N consecutive]] - rationale - paper.py
- [[Reverse the most recently placed (unsettled) paper trade if it was placed     w]] - rationale - paper.py
- [[Scale Kelly by per-method Brier. Poor method (Brier  0.20) → 0.75×.      Uses]] - rationale - paper.py
- [[Scale Kelly down for cities where the model has historically underperformed.]] - rationale - paper.py
- [[Scale down base_fraction based on existing open exposure to this citydate.]] - rationale - paper.py
- [[Scan open paper trades with exit_target set. If the current market price     ha]] - rationale - paper.py
- [[Set needs_manual_settle=True on a trade so the dashboard can flag it.]] - rationale - paper.py
- [[Sum of P&L from trades settled today (UTC).     46 If a live client is provid]] - rationale - paper.py
- [[Update peak_profit_pct on open trades if current unrealized profit is a new high]] - rationale - paper.py
- [[ValueError]] - code
- [[Waive the daily loss limit for the rest of today (UTC).      Writes a flag fil]] - rationale - paper.py
- [[Wipe all paper trades and reset balance.]] - rationale - paper.py
- [[Write atomically with retry via safe_io (8). Embeds SHA-256 checksum (102).]] - rationale - paper.py
- [[Write data to path atomically (write temp → fsync → rename).     Retries up to]] - rationale - safe_io.py
- [[_city_kelly_multiplier()]] - code - paper.py
- [[_compute_checksum()]] - code - paper.py
- [[_env_float()_1]] - code - paper.py
- [[_env_int()_1]] - code - paper.py
- [[_exposure_denom()]] - code - paper.py
- [[_load()_1]] - code - paper.py
- [[_mark_needs_manual_settle()]] - code - paper.py
- [[_method_kelly_multiplier()]] - code - paper.py
- [[_quick_paper_buy()]] - code - main.py
- [[_save()_1]] - code - paper.py
- [[_score_ensemble_members()]] - code - paper.py
- [[atomic_write_json()]] - code - safe_io.py
- [[bool_19]] - code - paper.py
- [[check_breakeven_stops()]] - code - paper.py
- [[check_exit_targets()]] - code - paper.py
- [[check_position_limits()]] - code - paper.py
- [[cleanup_temp_files()]] - code - paper.py
- [[close_paper_early()]] - code - paper.py
- [[covariance_kelly_scale()]] - code - paper.py
- [[drawdown_scaling_factor()]] - code - paper.py
- [[estimate_slippage()]] - code - paper.py
- [[export_tax_csv()]] - code - paper.py
- [[export_trades_csv()]] - code - paper.py
- [[fear_greed_index()]] - code - paper.py
- [[float_24]] - code - paper.py
- [[get_attribution()]] - code - paper.py
- [[get_city_date_exposure()]] - code - paper.py
- [[get_correlated_exposure()]] - code - paper.py
- [[get_current_streak()]] - code - paper.py
- [[get_daily_pnl()]] - code - paper.py
- [[get_directional_exposure()]] - code - paper.py
- [[get_profit_factor()]] - code - paper.py
- [[get_rolling_sharpe()]] - code - paper.py
- [[get_ticker_exposure()]] - code - paper.py
- [[get_total_exposure()]] - code - paper.py
- [[int_19]] - code - paper.py
- [[int_22]] - code - safe_io.py
- [[is_daily_loss_halted()]] - code - paper.py
- [[is_streak_paused()]] - code - paper.py
- [[kelly_bet_dollars()]] - code - paper.py
- [[kelly_quantity()]] - code - paper.py
- [[paper.py]] - code - paper.py
- [[place_paper_order()_1]] - code - paper.py
- [[portfolio_kelly_fraction()]] - code - paper.py
- [[position_age_kelly_scale()]] - code - paper.py
- [[project_root()]] - code - safe_io.py
- [[reset_daily_loss_limit()]] - code - paper.py
- [[reset_paper_account()]] - code - paper.py
- [[safe_io.py]] - code - safe_io.py
- [[settle_paper_trade()]] - code - paper.py
- [[simulate_fill()]] - code - paper.py
- [[slippage_adjusted_price()]] - code - paper.py
- [[slippage_kelly_scale()]] - code - paper.py
- [[str_23]] - code - paper.py
- [[undo_last_trade()]] - code - paper.py
- [[update_peak_profits()]] - code - paper.py
- [[validate_paper_trades_integrity()]] - code - paper.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Paper_Trading__Exits
SORT file.name ASC
```

## Connections to other communities
- 64 edges to [[_COMMUNITY_CLI & Preload Pipeline]]
- 48 edges to [[_COMMUNITY_Python Types & Utilities]]
- 31 edges to [[_COMMUNITY_AB Testing System]]
- 21 edges to [[_COMMUNITY_Module frosty]]
- 13 edges to [[_COMMUNITY_Portfolio Kelly & P&L]]
- 12 edges to [[_COMMUNITY_Module tests]]
- 10 edges to [[_COMMUNITY_Module tests]]
- 9 edges to [[_COMMUNITY_Cron Scheduler]]
- 6 edges to [[_COMMUNITY_Tracker Analytics (BrierBias)]]
- 5 edges to [[_COMMUNITY_Circuit Breaker Fault Tolerance]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 3 edges to [[_COMMUNITY_Module frosty]]
- 3 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 3 edges to [[_COMMUNITY_Module frosty]]
- 3 edges to [[_COMMUNITY_Module tests]]
- 3 edges to [[_COMMUNITY_Module tests]]
- 3 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Kelly Criterion Sizing]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module frosty]]

## Top bridge nodes
- [[paper.py]] - degree 100, connects to 22 communities
- [[ValueError]] - degree 16, connects to 11 communities
- [[float_24]] - degree 40, connects to 8 communities
- [[place_paper_order()_1]] - degree 26, connects to 6 communities
- [[_quick_paper_buy()]] - degree 23, connects to 6 communities