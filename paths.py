"""Single source of truth for all data and state file paths.

Import from here instead of constructing Path(__file__).parent / "data" / ...
in each module individually. Using safe_io.project_root() rather than
Path(__file__).parent so that paths resolve correctly when running from a
git worktree (the worktree dir has no data/ files — only the main project does).
"""

from safe_io import project_root as _project_root

_ROOT = _project_root()
_DATA = _ROOT / "data"
# data/ is gitignored -- create it on first run (fresh clone). parents=True
# is cheap insurance, not a fix for a known failure: importing this module
# now happens very early/widely (utils.py, circuit_breaker.py, kalshi_ws.py,
# nws.py all import from here at module scope), so a mkdir failure here is
# closer to a total-import-crash path than it used to be.
_DATA.mkdir(parents=True, exist_ok=True)

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
# Snapshot of global/above/below/between's pre-EMOS-activation T values,
# written by ml_bias.reset_temperature_scale_for_emos() so deactivate_emos()
# can restore them immediately instead of leaving those keys pinned at the
# 1.0 placeholder until the next scheduled retrain.
TEMPERATURE_SCALE_PRE_EMOS_PATH = _DATA / "temperature_scale_pre_emos.json"
EMOS_PARAMS_PATH = _DATA / "emos_params.json"
CONDITION_WEIGHTS_PATH = _DATA / "condition_weights.json"
SEASONAL_WEIGHTS_PATH = _DATA / "seasonal_weights.json"
CITY_WEIGHTS_PATH = _DATA / "city_weights.json"
LEARNED_WEIGHTS_PATH = _DATA / "learned_weights.json"
MEMBER_QUARANTINE_PATH = _DATA / "member_quarantine.json"
CORRELATIONS_PATH = _DATA / "correlations.json"
LEARNED_CORRELATIONS_PATH = _DATA / "learned_correlations.json"

# System state — these live in data/ (verified against cron.py and watchdog.py)
KILL_SWITCH_PATH = _DATA / ".kill_switch"
BLACK_SWAN_PATH = _DATA / ".black_swan_active"
MANUAL_OVERRIDE_PATH = _DATA / ".manual_override.json"
LOCK_PATH = _DATA / ".cron.lock"
RUNNING_FLAG_PATH = _DATA / ".cron_running"
LAST_HEARTBEAT_PATH = _DATA / "last_heartbeat.txt"
PROD_REMINDER_PATH = _DATA / "last_prod_reminder.txt"
SERIES_DRIFT_PATH = _DATA / "series_drift_check.json"
# Batch-49 item 1: persisted once-per-day gate for the fills-based $0-maker-
# fee guard (fee_change_check.json) and once-per-week gate for the
# best-effort kalshi.com/fee-schedule page watch (fee_schedule_scrape_check.json).
FEE_CHECK_PATH = _DATA / "fee_change_check.json"
FEE_SCHEDULE_SCRAPE_PATH = _DATA / "fee_schedule_scrape_check.json"
CITY_REGISTRY_REPORT_PATH = _DATA / "city_registry_report.json"
RETIREMENT_PROBATION_PATH = _DATA / "retirement_probation_check.json"
HOURLY_TARGET_HOURS_PATH = _DATA / "hourly_target_hours.json"
HURRICANE_COUNT_TO_DATE_PATH = _DATA / "hurricane_count_to_date.json"
NOTIFY_COOLDOWN_STATE_PATH = _DATA / ".notify_cooldowns.json"
RAIN_ARB_SHADOW_PATH = _DATA / "rain_arb_shadow_observations.json"
# batch-24 item 4: persisted false->true edge tracking for risk-halt alerts
# (anomaly/daily-loss/drawdown) so send_system_alert() fires once per
# engagement instead of every cron cycle the halt stays active.
HALT_TRANSITION_STATE_PATH = _DATA / ".halt_transitions.json"

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
LAST_QUARANTINE_SCAN_PATH = _DATA / ".last_quarantine_scan"
LAST_ML_RETRAIN_PATH = _DATA / ".last_ml_retrain"
LAST_WEIGHTS_REFRESH_PATH = _DATA / ".last_weights_refresh"
LAST_PARAM_SWEEP_PATH = _DATA / ".last_param_sweep"
LAST_WALK_FORWARD_PATH = _DATA / ".last_walk_forward"
GRADUATED_FLAG_PATH = _DATA / "graduated.flag"
SIGNALS_CACHE_PATH = _DATA / "signals_cache.json"
PARAM_SWEEP_RESULTS_PATH = _DATA / "param_sweep_results.json"
LAST_BACKTEST_PATH = _DATA / ".last_backtest.json"

# Non-safety-critical caches / model artifacts / logs (backlog.txt "~13
# NON-SAFETY-CRITICAL FILES STILL BYPASS paths.py" migration, 2026-08-05).
# None of these feed live-order gates, but each is still real state that
# should resolve to the main clone's data/ regardless of which worktree the
# process happens to run from -- see the safety-critical constants above for
# the original incident this same bug class caused.
AB_TEST_DIR = _DATA / "ab_tests"
ALERTS_PATH = _DATA / "alerts.json"
FEATURE_IMPORTANCE_LOG_PATH = _DATA / "feature_importance.jsonl"
CB_STATE_PATH = _DATA / ".cb_state.json"
FLASH_CRASH_COOLDOWN_PATH = _DATA / ".flash_crash_cooldowns.json"
FLASH_CRASH_HISTORY_PATH = _DATA / ".flash_crash_history.json"
PDO_PNA_PATH = _DATA / "pdo_pna.json"
ORDERBOOK_CACHE_PATH = _DATA / "orderbook_cache.json"
ML_BIAS_MODEL_PATH = _DATA / "bias_models.pkl"
ML_BIAS_HMAC_PATH = _DATA / ".bias_models.hmac"
NOTIFY_TEMPLATES_PATH = _DATA / "notify_templates.json"
CONFIG_HASH_PATH = _DATA / ".config_hash"
CRASH_LOG_PATH = _DATA / "crash.log"
WATCH_STATE_PATH = _DATA / ".watch_state.json"
EXPORTS_DIR = _DATA / "exports"
ONBOARDED_MARKER_PATH = _DATA / ".onboarded"
WALK_FORWARD_RESULTS_PATH = _DATA / "walk_forward_results.json"
CITIES_JSON_PATH = _DATA / "cities.json"
FEATURE_ACTIVATIONS_PATH = _DATA / "feature_activations.json"
PLATT_MODELS_PATH = _DATA / "platt_models.json"
METAR_CALIBRATION_PATH = _DATA / "metar_lockout_calibration.json"
FORECAST_SNAPSHOTS_DIR = _DATA / "forecast_snapshots"
ENSEMBLE_CACHE_DIR = _DATA / "ensemble_cache"
ENSEMBLE_DISK_CACHE_PATH = _DATA / "ensemble_cache.json"
# Shared by weather_markets.py (writer) and web_app.py (2 read-only API
# endpoints) -- previously each constructed its own path independently
# (weather_markets.py's own was even cwd-relative, not __file__-relative).
# In the real deployed configuration cwd and __file__ both resolved to the
# same place historically (the operator always launched from the project
# root -- run_and_sleep.bat, which did this via its own `cd`, has since been
# removed as dead code (AUD batch-30 item 2); web_app.py still spawns cron
# with cwd=Path(__file__).parent), so this was never a production bug -- but
# it silently broke for a worktree run or any manual invocation from a
# different cwd, which is exactly this migration's scope.
FORECAST_CACHE_PATH = _DATA / "forecast_cache.json"
# Shared by cron.py (writer) and web_app.py (2 read-only viewers).
CRON_LOG_PATH = _DATA / "cron.log"
CRON_WEB_LOG_PATH = _DATA / "cron_web.log"
# nws.py's persistent station-ID cache -- missed in the first pass of this
# migration since it used `Path(__file__).resolve().parent / "data"` (an
# extra `.resolve()` call the original bypass-detection grep didn't match),
# caught by tests/test_paths_bypass_guard.py's own tightened regex after a
# bug in that guard's directory-exclusion logic was fixed.
NWS_STATION_CACHE_PATH = _DATA / ".nws_station_cache.json"
