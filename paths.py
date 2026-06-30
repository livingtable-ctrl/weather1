"""Single source of truth for all data and state file paths.

Import from here instead of constructing Path(__file__).parent / "data" / ...
in each module individually. Using safe_io.project_root() rather than
Path(__file__).parent so that paths resolve correctly when running from a
git worktree (the worktree dir has no data/ files — only the main project does).
"""

from safe_io import project_root as _project_root

_ROOT = _project_root()
_DATA = _ROOT / "data"
if not _DATA.is_dir():
    raise FileNotFoundError(
        f"Data directory not found: {_DATA} — expected project_root()/data to exist."
    )

# Database
DB_PATH = _DATA / "predictions.db"

# Paper trading
PAPER_TRADES_PATH = _DATA / "paper_trades.json"

# Model artifacts
TEMPERATURE_SCALE_PATH = _DATA / "temperature_scale.json"
EMOS_PARAMS_PATH = _DATA / "emos_params.json"
CONDITION_WEIGHTS_PATH = _DATA / "condition_weights.json"
SEASONAL_WEIGHTS_PATH = _DATA / "seasonal_weights.json"
LEARNED_WEIGHTS_PATH = _DATA / "learned_weights.json"
CORRELATIONS_PATH = _DATA / "correlations.json"

# System state — these live in data/ (verified against cron.py and watchdog.py)
KILL_SWITCH_PATH = _DATA / ".kill_switch"
LOCK_PATH = _DATA / ".cron.lock"
RUNNING_FLAG_PATH = _DATA / ".cron_running"
PEAK_BALANCE_PATH = _DATA / "peak_balance.json"
LAST_HEARTBEAT_PATH = _DATA / "last_heartbeat.txt"
PROD_REMINDER_PATH = _DATA / "last_prod_reminder.txt"
