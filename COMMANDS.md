# Kalshi Weather Bot — Command Reference

All commands: `py main.py <command> [args]`

---

## Daily Use

| Command | Description |
|---|---|
| `cron` | Run one scan cycle — fetch markets, score edges, place paper trades, settle outcomes |
| `cron --edge 0.12` | Same but override minimum edge threshold |
| `brief` | Single-screen daily summary (balance, positions, Brier, graduation gates) |
| `brief --email` | Same + send email notification |
| `today` | Plain-English "what should I do today?" recommendation |
| `positions` | Show all open paper trade positions |
| `balance` | Show current paper balance, P&L, win rate |
| `dashboard` | Full portfolio health view (balance, positions, calibration) |
| `markets` | List all open Kalshi weather markets |
| `market <TICKER>` | Show details for a single market |
| `market <TICKER> --verbose` | Show full market data including order book |
| `forecast <city>` | Show ensemble forecast for a city (e.g. `forecast NYC`) |
| `analyze` | Scan markets and score edges (display only, no trades placed) |
| `analyze --live` | Same but also shows live market prices |

---

## Trading

| Command | Description |
|---|---|
| `paper buy <TICKER> <yes/no> <price>` | Manually place a paper trade (auto-sizes via Kelly) |
| `paper buy <TICKER> <yes/no> <price> <qty>` | Manually place with specific quantity |
| `paper results` | Show all paper trades with P&L |
| `paper settle <trade_id> <yes/no>` | Manually settle a specific paper trade |
| `paper reset` | **⚠ Destructive** — wipe all paper trades and reset balance to $1,000 |
| `settle` | Sync settled market outcomes from Kalshi and record in tracker |
| `watch-settle` | Poll until all same-day open trades are settled |
| `cancel <order_id>` | Cancel a live order |
| `buy <TICKER> <yes/no> <qty> <price>` | Place a live order |
| `sell <TICKER> <yes/no> <qty> <price>` | Place a live sell order |

---

## Analysis & Calibration

| Command | Description |
|---|---|
| `backtest` | Run backtest on historical data |
| `backtest --days 180` | Backtest over the last 180 days |
| `validate` | Walk-forward validation — checks if performance is degrading over time |
| `calibrate` | Refit Platt scaling and temperature scaling from settled predictions |
| `train-bias` | Retrain GBM bias model + Platt per city + temperature scaling |
| `drift` | Check for model drift (compares recent vs historical Brier) |
| `features` | Show feature importance for current model |
| `sweep` | Parameter sweep to find optimal edge/Kelly thresholds |
| `shadow` | Shadow compare: simulate trades against real outcomes |
| `replay <trade_id>` | Replay a specific trade's decision logic |
| `consistency` | Scan for arbitrage / consistency violations across related markets |
| `montecarlo` | Monte Carlo simulation of portfolio outcomes |
| `ab-summary` | Show A/B experiment results (edge threshold variants) |

---

## Reporting

| Command | Description |
|---|---|
| `history` | Show recent market history |
| `journal` | Show all paper trades that have a thesis note |
| `export` | Export prediction history and trades to CSV in `data/exports/` |
| `report` | Generate PDF report |
| `weekly` | Weekly performance summary |
| `walk-forward` | Full walk-forward backtest with rolling windows |
| `pnl-attribution` | Break down P&L by city, model source, condition type |

---

## System & Safety

| Command | Description |
|---|---|
| `kill` | Activate kill switch — halts all new trades immediately |
| `resume` | Deactivate kill switch — resumes trading |
| `override set [minutes]` | Temporarily pause trading for N minutes (default 60) |
| `override clear` | Cancel the active pause override early |
| `override status` | Show current override status and time remaining |
| `unlock` | Remove stale cron lock file (if cron crashed mid-run) |
| `readiness` | Full system readiness check (API, DB, kill switch, graduation gates) |
| `sync` | Force-sync market data from Kalshi API |
| `restore` | Restore data from cloud backup (OneDrive/Drive) |
| `settlement-monitor` | Run METAR settlement lag monitor (polls 5–7 PM local) |
| `loop` | Self-scheduling run loop — runs cron every N hours automatically |

---

## Admin (use with care)

| Command | Description |
|---|---|
| `admin reset-loss` | Waive today's daily loss limit (expires midnight UTC) — use after a bug caused phantom losses |
| `admin reset-loss "reason"` | Same with a reason string logged |
| `paper reset` | **⚠ Wipes all paper trades** and resets balance to $1,000 |

---

## Setup & Config

| Command | Description |
|---|---|
| `setup` | First-time setup wizard |
| `menu` | Interactive terminal menu (alternative to CLI commands) |
| `web` | Start Flask web dashboard on localhost |
| `settings` | View/edit bot settings interactively |
| `config-check` | Validate `.env` config — checks all required vars are set |
| `version-compare` | Compare current code version against last known good |
| `code-audit` | Run internal code audit checks |
| `onboard` | Run onboarding flow for new users |

---

## Subcommand Notes

**`paper` subcommands:**
```
py main.py paper buy <TICKER> <yes/no> <price> [qty]
py main.py paper results
py main.py paper settle <trade_id> <yes/no>
py main.py paper reset
```

**`override` subcommands:**
```
py main.py override set [minutes]   # default 60 min
py main.py override clear
py main.py override status
```

**`backtest` flags:**
```
py main.py backtest --days 90
py main.py backtest --days 180
```

**`analyze` flags:**
```
py main.py analyze
py main.py analyze --live
py main.py analyze --edge 0.12
```
