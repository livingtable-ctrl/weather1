# Kalshi Weather Trading Bot

An automated paper (and optionally live) trading bot for Kalshi weather prediction markets. It forecasts temperature and precipitation outcomes using NWS data and ICON/GFS ensemble models, sizes positions with Kelly criterion, and graduates to live trading only after passing a calibration gate.

---

## Requirements

- Windows 10/11
- Python 3.12 — download from [python.org](https://www.python.org/downloads/) (do not use 3.13 or 3.14)
- A Kalshi account — sign up at [kalshi.com](https://kalshi.com)

---

## Installation

**1. Clone the repo**

```
git clone https://github.com/livingtable-ctrl/weather1.git
cd weather1
```

**2. Install dependencies**

```
pip install -r requirements.txt
```

**3. Get your Kalshi API credentials**

- Log in to Kalshi → Account → API
- Create a new key and download the `.pem` private key file
- Copy the Key ID shown on screen

**4. Configure credentials**

Create a file called `.env` in the project folder with this content:

```
KALSHI_KEY_ID=your-key-id-here
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem
KALSHI_ENV=demo
```

- Place your downloaded `.pem` file in the project folder and name it `kalshi_private_key.pem`
- Keep `KALSHI_ENV=demo` until you are ready to trade real money

**5. Test the setup**

```
python main.py
```

This opens the interactive menu. If credentials are correct you will see your account balance.

---

## Usage

### Interactive menu

```
python main.py
```

Opens a numbered menu with every feature. Good starting point.

### Commands

| Command | What it does |
|---|---|
| `python main.py scan` | Scan all weather markets, print opportunities |
| `python main.py watch` | Live watch mode — refreshes every 5 minutes |
| `python main.py cron` | Silent scan that auto-places paper trades (used by Task Scheduler) |
| `python main.py web` | Start the dashboard at http://localhost:5000 |
| `python main.py backtest` | Run a backtest against historical settled markets |
| `python main.py analyze` | Deep analysis on a single market ticker |
| `python main.py forecast <city>` | Show raw NWS/ensemble forecast for a city |
| `python main.py pnl-attribution` | P&L broken down by signal source (alias: `pnl`) |
| `python main.py train-bias` | Train ML calibration models from tracker DB (needs 200+ settled trades per city) |
| `python main.py kill` | Activate kill switch to halt all trading |
| `python main.py resume` | Resume trading after kill switch or black swan halt |
| `python main.py weekly` | Weekly performance summary (alias: `y`) |
| `python main.py report` | Generate PDF performance report |
| `python main.py drift` | Detect Brier score drift |
| `python main.py settlement-monitor` | Run settlement lag monitor |
| `python main.py shadow` | Shadow-compare two model versions |
| `python main.py ab-summary` | Show A/B experiment results |
| `python main.py journal` | Trade journal |
| `python main.py export` | Export trade data to CSV |
| `python main.py restore` | Restore data from cloud backup |

### Dashboard

```
python main.py web
```

Open your browser to `http://localhost:5000`. The dashboard shows:
- Open positions and signals
- PnL, win rate, Brier score
- Model accuracy (ICON vs GFS)
- Price improvement and source reliability

---

## How trading works

**Paper trading (default)**

The bot places simulated trades using a virtual $1,000 starting balance. No real money moves. Trades are logged to the local database and tracked for calibration.

**Graduation to live trading**

The bot will not switch to live trading automatically. It checks three criteria:
- 30+ settled paper trades
- Total PnL >= $50
- Brier score <= 0.20 (well-calibrated — random guessing scores 0.25)

When all three pass, the graduation check confirms you are ready. To actually go live, change `KALSHI_ENV=prod` in `.env`.

**Position sizing**

Uses Kelly criterion scaled by forecast confidence, days until market closes, model agreement between ICON and GFS, and existing portfolio exposure. It will never bet the farm on a single market.

You can switch sizing strategies by setting `STRATEGY` in `.env`:

| Value | Behavior |
|---|---|
| `kelly` | Half-Kelly sizing (default) |
| `fixed_pct` | Fixed percentage of balance; set `FIXED_BET_PCT` (default `0.01`) |
| `fixed_dollars` | Fixed dollar amount per trade; set `FIXED_BET_DOLLARS` (default `10.0`) |

**Kill switch**

Run `python main.py kill` to halt all auto-trading immediately. Run `python main.py resume` to re-enable. The `alerts.py` module can also trigger an automatic halt if it detects a black swan or anomalous market condition.

**ML probability calibration**

Once you have 200+ settled trades for a city, run `python main.py train-bias` to train a GradientBoosting model that corrects the bot's raw probability estimates toward observed outcome frequencies. Models are stored locally and picked up automatically on the next cron scan.

---

## Automated scheduling (Windows)

To have the bot scan automatically while your PC sleeps:

1. Open Task Scheduler → Create Task
2. Set the action to run `run_and_sleep.bat` in the project folder
3. Set triggers for your preferred times (e.g. 6am, 9am, 12pm, 3pm, 6pm, 9pm)
4. Under Conditions → Power: check "Wake the computer to run this task"
5. Under Settings: check "Run task as soon as possible after a scheduled start is missed"

The batch file uses Python 3.12 explicitly and puts the PC back to sleep after the scan finishes (only if no one was already using it).

During cron runs, the bot optionally opens a WebSocket connection to the Kalshi order book to fetch real-time mid prices before falling back to the REST API.

---

## Environment variables

All settings have sensible defaults. Override any of them in `.env`:

| Variable | Default | Description |
|---|---|---|
| `KALSHI_KEY_ID` | — | Your Kalshi API key ID (required) |
| `KALSHI_PRIVATE_KEY_PATH` | — | Path to your `.pem` file (required) |
| `KALSHI_ENV` | `demo` | `demo` for paper trading, `prod` for live |
| `MIN_EDGE` | `0.07` | Minimum edge to show in scan output |
| `PAPER_MIN_EDGE` | `0.05` | Minimum edge to auto-place a paper trade |
| `MED_EDGE` | `0.15` | Edge threshold for medium-confidence signal tier |
| `STRONG_EDGE` | `0.25` | Edge threshold for a strong signal |
| `MAX_DAILY_SPEND` | `500.0` | Max dollars to spend per day |
| `MAX_DAILY_LOSS_PCT` | `0.03` | Halt auto-trading if daily loss exceeds this fraction of balance |
| `MAX_DAYS_OUT` | `5` | Only trade markets closing within N days |
| `MAX_POSITION_AGE_DAYS` | `7` | Close positions older than N days |
| `KALSHI_FEE_RATE` | `0.07` | Taker fee rate (7%) |
| `STRATEGY` | `kelly` | Sizing strategy: `kelly`, `fixed_pct`, or `fixed_dollars` |
| `FIXED_BET_PCT` | `0.01` | Fraction of balance per trade when `STRATEGY=fixed_pct` |
| `FIXED_BET_DOLLARS` | `10.0` | Dollars per trade when `STRATEGY=fixed_dollars` |
| `DRAWDOWN_HALT_PCT` | `0.50` | Halt all trading if balance falls below this fraction of peak |
| `LOG_LEVEL` | `WARNING` | Python logging level for the `kalshi` logger |
| `GOOGLE_DRIVE_PATH` | — | Override Google Drive sync folder path for backups |
| `CLOUD_BACKUP_PATH` | — | Override backup destination (any folder: OneDrive, Dropbox, etc.) |

---

## Project structure

```
main.py               — CLI entry point and cron runner
weather_markets.py    — Forecast engine and trade analysis
paper.py              — Paper trading, Kelly sizing, portfolio exposure
tracker.py            — Trade logging, Brier scoring, bias detection
web_app.py            — Flask dashboard API
kalshi_client.py      — Kalshi REST API client
kalshi_ws.py          — WebSocket client for real-time order book prices
ml_bias.py            — ML probability calibration (GradientBoosting per city)
alerts.py             — Anomaly detection and black swan halt
settlement_monitor.py — Settlement lag signal detection
ab_test.py            — A/B experiment framework
circuit_breaker.py    — Trading circuit breaker
execution_log.py      — Execution audit log
safe_io.py            — Atomic file I/O helpers
system_health.py      — System health checks
regime.py             — Market regime detection
calibration.py        — Probability calibration utilities
backtest.py           — Historical backtesting
metar.py              — METAR observation fetching
nws.py                — NWS forecast fetching
mos.py                — MOS forecast data
climatology.py        — Historical climatology data
cloud_backup.py       — OneDrive/Google Drive backup
utils.py              — Shared constants and helpers
run_and_sleep.bat     — Windows Task Scheduler entry point
data/                 — Local SQLite databases (trades, signals, forecasts)
static/               — Dashboard JS and CSS
templates/            — Dashboard HTML
```

---

## Moving to a new PC

Your paper trading history (trades, Brier scores, PnL) lives in the `data/` folder which is gitignored. The bot automatically backs this up to OneDrive or Google Drive after every cron scan — no setup needed if you are already signed in to either service.

To restore on a new PC after cloning:

```
python main.py restore
```

This copies your data back from `OneDrive/KalshiBot/data/` (or Google Drive equivalent) into the local `data/` folder.

**Custom backup location** — if auto-detection does not find your sync folder, set one of these in `.env`:

```
# Point directly to your Google Drive folder
GOOGLE_DRIVE_PATH=G:\My Drive

# Or any other folder (OneDrive, Dropbox, etc.)
CLOUD_BACKUP_PATH=C:\path\to\your\sync\folder
```

---

## Notes

- The `.env` file and `.pem` key are gitignored — never commit them
- The bot only trades Kalshi weather markets (temperature and precipitation). It ignores all other market types.
- `python main.py kill` writes a halt flag that persists across restarts; `python main.py resume` clears it.
- The `train-bias` command requires `scikit-learn` (included in `requirements.txt`) and at least 200 settled predictions per city to produce a model that outperforms the static bias table.
