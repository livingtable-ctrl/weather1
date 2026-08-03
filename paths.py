"""Single source of truth for all data and state file paths.

Import from here instead of constructing Path(__file__).parent / "data" / ...
in each module individually. Using safe_io.project_root() rather than
Path(__file__).parent so that paths resolve correctly when running from a
git worktree (the worktree dir has no data/ files — only the main project does).
"""

from safe_io import project_root as _project_root

_ROOT = _project_root()
_DATA = _ROOT / "data"
_DATA.mkdir(exist_ok=True)  # data/ is gitignored — create it on first run (fresh clone)

# The data/ directory itself, for modules that need to construct their own
# filenames within it (cloud_backup.py's default sync source, calibration.py's
# default output dir, config.py's _DATA_DIR) rather than a single fixed file.
DATA_DIR = _DATA

# Database
DB_PATH = _DATA / "predictions.db"
EXECUTION_LOG_DB_PATH = _DATA / "execution_log.db"

# Paper trading
PAPER_TRADES_PATH = _DATA / "paper_trades.json"

# Live trading hard stops (max trade size, daily loss limit, max open
# positions, GTC cancel window) — must resolve identically regardless of
# which worktree watch --auto --live happens to run from.
LIVE_CONFIG_PATH = _DATA / "live_config.json"

# Model artifacts
TEMPERATURE_SCALE_PATH = _DATA / "temperature_scale.json"
EMOS_PARAMS_PATH = _DATA / "emos_params.json"
CONDITION_WEIGHTS_PATH = _DATA / "condition_weights.json"
SEASONAL_WEIGHTS_PATH = _DATA / "seasonal_weights.json"
CITY_WEIGHTS_PATH = _DATA / "city_weights.json"
LEARNED_WEIGHTS_PATH = _DATA / "learned_weights.json"
CORRELATIONS_PATH = _DATA / "correlations.json"
LEARNED_CORRELATIONS_PATH = _DATA / "learned_correlations.json"

# System state — these live in data/ (verified against cron.py and watchdog.py)
KILL_SWITCH_PATH = _DATA / ".kill_switch"
BLACK_SWAN_PATH = _DATA / ".black_swan_active"
MANUAL_OVERRIDE_PATH = _DATA / ".manual_override.json"
LOCK_PATH = _DATA / ".cron.lock"
RUNNING_FLAG_PATH = _DATA / ".cron_running"
PEAK_BALANCE_PATH = _DATA / "peak_balance.json"
LAST_HEARTBEAT_PATH = _DATA / "last_heartbeat.txt"
PROD_REMINDER_PATH = _DATA / "last_prod_reminder.txt"
SERIES_DRIFT_PATH = _DATA / "series_drift_check.json"
CITY_REGISTRY_REPORT_PATH = _DATA / "city_registry_report.json"
RETIREMENT_PROBATION_PATH = _DATA / "retirement_probation_check.json"
HOURLY_TARGET_HOURS_PATH = _DATA / "hourly_target_hours.json"
NOTIFY_COOLDOWN_STATE_PATH = _DATA / ".notify_cooldowns.json"

# cron.py periodic-task gate sentinels — each gates a weekly/periodic
# maintenance task (calibration, ML retrain, param sweep, walk-forward, weights
# refresh) behind a "last ran" marker file. These must resolve to the same
# location regardless of which worktree cron.py happens to run from, or every
# worktree run starts with a fresh (nonexistent) marker and re-triggers every
# gated task unconditionally, while the real gate in the main clone never sees
# that the task ran.
LAST_CALIBRATION_COUNT_PATH = _DATA / ".last_calibration_count"
CRON_LAST_RUN_PATH = _DATA / ".cron_last_run"
CRON_HEARTBEAT_PATH = _DATA / "cron_heartbeat.json"
LAST_MONDAY_SWEEP_PATH = _DATA / ".last_monday_sweep"
LAST_ML_RETRAIN_PATH = _DATA / ".last_ml_retrain"
LAST_WEIGHTS_REFRESH_PATH = _DATA / ".last_weights_refresh"
LAST_PARAM_SWEEP_PATH = _DATA / ".last_param_sweep"
LAST_WALK_FORWARD_PATH = _DATA / ".last_walk_forward"
GRADUATED_FLAG_PATH = _DATA / "graduated.flag"
SIGNALS_CACHE_PATH = _DATA / "signals_cache.json"
PARAM_SWEEP_RESULTS_PATH = _DATA / "param_sweep_results.json"
LAST_BACKTEST_PATH = _DATA / ".last_backtest.json"
