---
type: community
cohesion: 0.05
members: 61
---

# Cron Scheduler

**Cohesion:** 0.05 - loosely connected
**Members:** 61 nodes

## Members
- [[.start()]] - code - kalshi_ws.py
- [[All callable dependencies that cmd_cron needs from outside cron.py.      Const]] - rationale - cron.py
- [[Background WebSocket thread for real-time Kalshi order book data.      Usage]] - rationale - kalshi_ws.py
- [[Build a CronContext from the current (possibly monkeypatched) main namespace.]] - rationale - main.py
- [[Core scan logic — extracted from cmd_cron so it can be wrapped in tryfinally.]] - rationale - cron.py
- [[CronContext]] - code - cron.py
- [[Delete RUNNING_FLAG_PATH if it exists.]] - rationale - cron.py
- [[Delete the cron lock file.]] - rationale - cron.py
- [[Determine STRONG-tier per-trade cap from current Brier score.      Returns a c]] - rationale - paper.py
- [[KalshiClient]] - code - cron.py
- [[KalshiWebSocket]] - code - kalshi_ws.py
- [[Prevent accidental live trading before enough settled predictions exist.]] - rationale - cron.py
- [[Print anomaly warnings; no-op when list is empty.]] - rationale - cron.py
- [[Read-only check return True if a cron process holds the lock right now.]] - rationale - cron.py
- [[Reconcile 'pending' execution_log rows against the Kalshi API at startup.]] - rationale - order_executor.py
- [[Return True if rolling win rate over last ACCURACY_WINDOW_TRADES is below     A]] - rationale - paper.py
- [[Return WS thread health info for monitoring.]] - rationale - kalshi_ws.py
- [[Return a human-readable reason string for the current accuracy halt, or '' if no]] - rationale - paper.py
- [[Return signals where blended_prob − market_price  _ANOMALY_THRESHOLD.]] - rationale - cron.py
- [[Returns True if a valid (non-expired) manual override is active.     Auto-clear]] - rationale - cron.py
- [[Silent background scan — writes to datacron.log, auto-places strong paper trade]] - rationale - cron.py
- [[Start a daemon thread that hard-kills the process if cron hangs  timeout_secs.]] - rationale - cron.py
- [[Start the WebSocket listener in a background thread.]] - rationale - kalshi_ws.py
- [[Train a bias correction model per city from tracker DB data.     Saves models t]] - rationale - ml_bias.py
- [[Truncate feature_importance.jsonl to the most recent max_lines entries.      R]] - rationale - feature_importance.py
- [[Try to acquire the cron file lock. Fail CLOSED on every error.      Returns Tr]] - rationale - cron.py
- [[Warn if MAX_DAILY_SPEND exceeds the current paper balance.      A spend cap th]] - rationale - cron.py
- [[Warn if any orders were placed in the last 5 minutes (double-execution guard).]] - rationale - cron.py
- [[Write UTC ISO timestamp to RUNNING_FLAG_PATH; warn if a fresh flag already exist]] - rationale - cron.py
- [[Write all pending ensemble entries to disk in one atomic operation.      Call]] - rationale - weather_markets.py
- [[_CronContext]] - code - main.py
- [[_acquire_cron_lock()]] - code - cron.py
- [[_build_cron_context()]] - code - main.py
- [[_check_graduation_gate()]] - code - cron.py
- [[_check_manual_override()]] - code - cron.py
- [[_check_spend_cap_vs_balance()]] - code - cron.py
- [[_check_startup_orders()]] - code - cron.py
- [[_clear_cron_running_flag()]] - code - cron.py
- [[_cmd_cron_body()]] - code - cron.py
- [[_dynamic_kelly_cap()]] - code - paper.py
- [[_install_cron_watchdog()]] - code - cron.py
- [[_is_cron_running()]] - code - cron.py
- [[_recover_pending_orders()]] - code - order_executor.py
- [[_release_cron_lock()]] - code - cron.py
- [[_write_cron_running_flag()]] - code - cron.py
- [[bool_7]] - code - cron.py
- [[check_market_anomalies()]] - code - cron.py
- [[cmd_cron()]] - code - cron.py
- [[cron.py]] - code - cron.py
- [[cron.py — Background cron runner extracted from main.py.  Contains cmd_cron an]] - rationale - cron.py
- [[float_10]] - code - cron.py
- [[flush_ensemble_disk_cache()]] - code - weather_markets.py
- [[get_accuracy_halt_reason()]] - code - paper.py
- [[get_ws_health()]] - code - kalshi_ws.py
- [[int_7]] - code - cron.py
- [[int_9]] - code - feature_importance.py
- [[is_accuracy_halted()]] - code - paper.py
- [[prune_feature_log()]] - code - feature_importance.py
- [[report_anomalies()]] - code - cron.py
- [[reset_gate_counts()]] - code - weather_markets.py
- [[train_bias_model()]] - code - ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Cron_Scheduler
SORT file.name ASC
```

## Connections to other communities
- 33 edges to [[_COMMUNITY_Python Types & Utilities]]
- 15 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 9 edges to [[_COMMUNITY_Paper Trading & Exits]]
- 9 edges to [[_COMMUNITY_Tracker Analytics (BrierBias)]]
- 8 edges to [[_COMMUNITY_CLI & Preload Pipeline]]
- 8 edges to [[_COMMUNITY_Module frosty]]
- 7 edges to [[_COMMUNITY_Module frosty]]
- 6 edges to [[_COMMUNITY_Module frosty]]
- 5 edges to [[_COMMUNITY_Module frosty]]
- 5 edges to [[_COMMUNITY_AB Testing System]]
- 5 edges to [[_COMMUNITY_Module frosty]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 3 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module frosty]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module frosty]]

## Top bridge nodes
- [[cron.py]] - degree 74, connects to 28 communities
- [[_cmd_cron_body()]] - degree 68, connects to 27 communities
- [[CronContext]] - degree 17, connects to 4 communities
- [[_dynamic_kelly_cap()]] - degree 9, connects to 4 communities
- [[KalshiWebSocket]] - degree 16, connects to 3 communities