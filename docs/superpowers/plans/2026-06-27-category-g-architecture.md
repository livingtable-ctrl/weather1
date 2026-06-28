# Category G: Architecture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce coupling and file size across the codebase: extract `paths.py` (G1), split `weather_markets.py` (G2), split `main.py` (G3), split `paper.py` (G4), consolidate config (G5), and add composite DB indexes (G6).

**Architecture:** G1 is the prerequisite for everything else — it removes the circular dependency where every module computes its own path to `data/`. G6 (DB indexes) is the quickest win and is fully independent. G2 and G4 are the largest refactors; attempt them only after G1 and G5 are complete.

**Tech Stack:** Python 3.14, SQLite, pytest.

**IMPORTANT — Standing Rule:** Only do G2 (split weather_markets.py) and G4 (split paper.py) after graduation. These are in `docs/superpowers/plans/do-after-graduation.md`. Do NOT start them before ~150-200 settled trades.

**Implementation Order:** G6 → G1 → G5 → G3 → G2 → G4

---

## G6: Composite DB Indexes

**Problem:** The most common query patterns in `tracker.py` are:
1. `WHERE ticker = ? AND settled_yes IS NOT NULL` — for Brier score calculation
2. `WHERE city = ? AND days_out = ? AND created_at >= ?` — for per-city stats
3. `WHERE our_prob IS NOT NULL AND settled_yes IS NOT NULL` — for calibration

None of these have composite indexes. Full table scans on 500+ rows are measurable at 20–50ms. Indexes make them microseconds.

**Files:**
- Modify: `tracker.py` — add composite indexes to `init_db()` (new migration version)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup_data_dir.py — add
def test_composite_indexes_exist_in_db(tmp_path, monkeypatch):
    import tracker
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    with tracker._conn() as con:
        indexes = {
            row[1] for row in
            con.execute("SELECT * FROM sqlite_master WHERE type='index'").fetchall()
        }

    assert "idx_predictions_ticker_settled" in indexes, "Missing ticker+settled index"
    assert "idx_predictions_city_days_created" in indexes, "Missing city+days+created index"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_cleanup_data_dir.py::test_composite_indexes_exist_in_db -v
```
Expected: AssertionError on missing indexes.

- [ ] **Step 3: Add composite indexes to `init_db()` in `tracker.py`**

Find the migration list (`_MIGRATIONS`) in `tracker.py`. Add a new migration at the end of the list (increment the version number):

```python
# Migration v30 (or whatever the next version is after v29):
"""
CREATE INDEX IF NOT EXISTS idx_predictions_ticker_settled
    ON predictions(ticker, settled_yes)
    WHERE settled_yes IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_predictions_city_days_created
    ON predictions(city, days_out, created_at)
    WHERE city IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_predictions_prob_settled
    ON predictions(our_prob, settled_yes)
    WHERE our_prob IS NOT NULL AND settled_yes IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_outcomes_ticker_settled
    ON outcomes(ticker, settled_at)
    WHERE settled_temp_f IS NOT NULL;
""",
```

Note: SQLite partial indexes (`WHERE`) are not supported in all versions — if your SQLite version is <3.8.9, remove the `WHERE` clauses.

- [ ] **Step 4: Run the test**

```
pytest tests/test_cleanup_data_dir.py::test_composite_indexes_exist_in_db -v
```
Expected: PASS

- [ ] **Step 5: Run the full tracker test file**

```
pytest tests/test_db_schema.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```
git add tracker.py tests/test_cleanup_data_dir.py
git commit -m "perf(db): add composite indexes on predictions(ticker+settled, city+days+created, prob+settled)"
```

---

## G1: Extract `paths.py`

**Problem:** Every module (`ml_bias.py`, `tracker.py`, `calibration.py`, `weather_markets.py`, etc.) individually defines `Path(__file__).parent / "data" / "some_file.json"`. If the `data/` directory is ever renamed or relocated, every module breaks. All data paths should live in one place.

**Files:**
- Create: `paths.py` — single source of truth for all data file paths
- Modify: `ml_bias.py`, `tracker.py`, `calibration.py`, `cron.py`, `paper.py`, `weather_markets.py`, `safe_io.py` — import from `paths.py` instead of local `Path(__file__).parent / ...`

- [ ] **Step 1: Audit all path definitions**

```
grep -n "Path(__file__)\.parent" ml_bias.py tracker.py calibration.py cron.py paper.py weather_markets.py safe_io.py
```

List all paths found. This will be the complete set that moves to `paths.py`.

**Known locations (verified 2026-06-27):**
- `cron.py:45` — `RUNNING_FLAG_PATH = Path(__file__).parent / "data" / ".cron_running"` (re-exported in `main.py:168`)
- `cron.py` — `KILL_SWITCH_PATH`, `LOCK_PATH`
- `tracker.py:21` — `DB_PATH = _project_root() / "data" / "predictions.db"`
- `paper.py` — `_TRADES_PATH` (paper_trades.json)
- `ml_bias.py` — `_TEMP_PATH` (temperature_scale.json), `_EMOS_PARAMS_PATH`

The grep will find all others. Collect the full list before writing `paths.py`.

- [ ] **Step 2: Write failing test**

```python
# tests/test_config_validation.py — add
def test_paths_module_exports_all_data_paths():
    import paths

    # All critical paths must be importable from paths.py
    required = [
        "DB_PATH",
        "PAPER_TRADES_PATH",
        "TEMPERATURE_SCALE_PATH",
        "EMOS_PARAMS_PATH",
        "CORRELATIONS_PATH",
        "CONDITION_WEIGHTS_PATH",
        "SEASONAL_WEIGHTS_PATH",
        "LEARNED_WEIGHTS_PATH",
        "KILL_SWITCH_PATH",
        "LOCK_PATH",
        "RUNNING_FLAG_PATH",
    ]
    for name in required:
        assert hasattr(paths, name), f"paths.py missing: {name}"
        val = getattr(paths, name)
        from pathlib import Path as P
        assert isinstance(val, P), f"paths.{name} should be a Path, got {type(val)}"
```

- [ ] **Step 3: Create `paths.py`**

```python
"""Single source of truth for all data and state file paths.

All modules must import paths here instead of constructing Path(__file__).parent / ...
individually. This makes relocation of data/, logs/, or the project root a one-file change.
"""
from pathlib import Path

_ROOT = Path(__file__).parent
_DATA = _ROOT / "data"
_LOGS = _ROOT / "logs"

# Database
DB_PATH = _DATA / "predictions.db"

# Paper trading
PAPER_TRADES_PATH = _DATA / "paper_trades.json"

# Model artifacts
TEMPERATURE_SCALE_PATH    = _DATA / "temperature_scale.json"
EMOS_PARAMS_PATH          = _DATA / "emos_params.json"
CONDITION_WEIGHTS_PATH    = _DATA / "condition_weights.json"
SEASONAL_WEIGHTS_PATH     = _DATA / "seasonal_weights.json"
LEARNED_WEIGHTS_PATH      = _DATA / "learned_weights.json"
CITY_WEIGHTS_PATH         = _DATA / "city_weights.json"
CORRELATIONS_PATH         = _DATA / "correlations.json"
STATION_BIAS_PATH         = _DATA / "station_bias.json"

# System state
KILL_SWITCH_PATH          = _ROOT / "kill_switch.txt"
LOCK_PATH                 = _ROOT / "bot.lock"
RUNNING_FLAG_PATH         = _ROOT / "running.flag"
PEAK_BALANCE_PATH         = _DATA / "peak_balance.json"
LAST_HEARTBEAT_PATH       = _DATA / "last_heartbeat.txt"
LAST_VACUUM_PATH          = _DATA / "last_vacuum.txt"
AB_TEST_STATE_PATH        = _DATA / "ab_test_state.json"
CIRCUIT_STATE_DIR         = _DATA  # circuit_<name>.json files go here

# Logs
LOG_FILE_PATH             = _ROOT / "bot.log"
```

- [ ] **Step 4: Update `tracker.py` to import `DB_PATH` from `paths`**

Find all `DB_PATH = Path(__file__).parent / ...` definitions in `tracker.py`. Replace with:

```python
from paths import DB_PATH
```

Remove the local definition.

- [ ] **Step 5: Update `ml_bias.py` to import model artifact paths from `paths`**

```python
from paths import TEMPERATURE_SCALE_PATH, EMOS_PARAMS_PATH, CONDITION_WEIGHTS_PATH

# Replace local definitions:
# _TEMP_PATH = Path(__file__).parent / "data" / "temperature_scale.json"
# with:
_TEMP_PATH = TEMPERATURE_SCALE_PATH
_EMOS_PARAMS_PATH = EMOS_PARAMS_PATH
```

- [ ] **Step 6: Update `cron.py` to import system state paths from `paths`**

```python
from paths import KILL_SWITCH_PATH, LOCK_PATH, RUNNING_FLAG_PATH
# Replace local string literals with these imported paths
```

- [ ] **Step 7: Update `paper.py` to import `PAPER_TRADES_PATH` and `PEAK_BALANCE_PATH`**

```python
from paths import PAPER_TRADES_PATH, PEAK_BALANCE_PATH
```

- [ ] **Step 8: Update remaining modules**

Repeat the import pattern for `calibration.py`, `safe_io.py`, `weather_markets.py`, `watchdog.py`, and `circuit_breaker.py`.

- [ ] **Step 9: Run the test**

```
pytest tests/test_config_validation.py::test_paths_module_exports_all_data_paths -v
```
Expected: PASS

- [ ] **Step 10: Run all test files that touch data paths**

```
pytest tests/test_db_schema.py tests/test_ml_bias.py tests/test_paper.py tests/test_cleanup_data_dir.py -v
```
Expected: all PASS

- [ ] **Step 11: Commit**

```
git add paths.py ml_bias.py tracker.py cron.py paper.py calibration.py safe_io.py weather_markets.py circuit_breaker.py watchdog.py tests/test_config_validation.py
git commit -m "refactor(arch): extract paths.py — single source of truth for all data and state file paths"
```

---

## G5: Config Consolidation

**Problem:** Configuration is split across `main.py` (env var reads), `paper.py` (more env vars), `order_executor.py` (more env vars), `weather_markets.py` (constants defined inline), and `cron.py` (more constants). A `BotConfig` dataclass in `config.py` would centralize all of this.

**Files:**
- Create: `config.py` — `BotConfig` dataclass with all env vars and tunable constants
- Modify: `main.py`, `paper.py`, `order_executor.py` — use `BotConfig` singleton
- Test: `tests/test_config_validation.py`

- [ ] **Step 1: Write failing test**

```python
def test_bot_config_loads_env_vars(monkeypatch):
    import os
    monkeypatch.setenv("PAPER_MIN_EDGE", "0.08")
    monkeypatch.setenv("KELLY_CAP", "0.20")
    monkeypatch.setenv("KALSHI_ENV", "demo")

    from config import BotConfig
    cfg = BotConfig.from_env()

    assert abs(cfg.paper_min_edge - 0.08) < 0.001
    assert abs(cfg.kelly_cap - 0.20) < 0.001
    assert cfg.kalshi_env == "demo"

def test_bot_config_has_defaults():
    from config import BotConfig
    cfg = BotConfig()  # no env vars set
    assert 0.01 <= cfg.paper_min_edge <= 0.15
    assert 0.10 <= cfg.kelly_cap <= 0.50
```

- [ ] **Step 2: Create `config.py`**

```python
"""Centralized configuration for the Kalshi weather trading bot.

All tunable parameters and environment variable reads live here.
Import BotConfig and use the singleton `get_config()` in preference
to reading os.getenv() directly in business logic.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    # API settings
    kalshi_env: str = "demo"
    kalshi_api_key: str = ""
    kalshi_api_secret: str = ""

    # Trading parameters
    paper_min_edge: float = 0.07
    kelly_cap: float = 0.25
    min_kelly_fraction: float = 0.05
    max_positions_per_date: int = 4
    max_same_day_positions: int = 8
    max_same_day_spend: float = 400.0
    max_days_out: int = 3
    method_kelly_gate: float = 50.0
    max_city_date_exposure: float = 50.0

    # Risk parameters
    breakeven_trigger_pct: float = 0.30
    partial_exit_pct: float = 0.50
    gfs_lockout_mins: int = 90
    min_arb_edge: float = 0.03

    # Ensemble / calibration
    below_gate_enabled: bool = False
    same_day_reserve_slots: int = 0
    same_day_reserve_after_hour_utc: int = 18

    # Notifications
    ntfy_topic: str = ""

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Create a BotConfig from environment variables with type coercion."""
        def _float(key: str, default: float) -> float:
            try:
                return float(os.getenv(key, str(default)))
            except ValueError:
                return default

        def _int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, str(default)))
            except ValueError:
                return default

        def _bool(key: str, default: bool) -> bool:
            v = os.getenv(key, "")
            if not v:
                return default
            return v.strip().lower() in ("1", "true", "yes", "on")

        return cls(
            kalshi_env=os.getenv("KALSHI_ENV", "demo"),
            kalshi_api_key=os.getenv("KALSHI_API_KEY", ""),
            kalshi_api_secret=os.getenv("KALSHI_API_SECRET", ""),
            paper_min_edge=_float("PAPER_MIN_EDGE", 0.07),
            kelly_cap=_float("KELLY_CAP", 0.25),
            min_kelly_fraction=_float("MIN_KELLY_FRACTION", 0.05),
            max_positions_per_date=_int("MAX_POSITIONS_PER_DATE", 4),
            max_same_day_positions=_int("MAX_SAME_DAY_POSITIONS", 8),
            max_same_day_spend=_float("MAX_SAME_DAY_SPEND", 400.0),
            max_days_out=_int("MAX_DAYS_OUT", 3),
            method_kelly_gate=_float("METHOD_KELLY_GATE", 50.0),
            max_city_date_exposure=_float("MAX_CITY_DATE_EXPOSURE", 50.0),
            breakeven_trigger_pct=_float("BREAKEVEN_TRIGGER_PCT", 0.30),
            partial_exit_pct=_float("PARTIAL_EXIT_PCT", 0.50),
            gfs_lockout_mins=_int("GFS_LOCKOUT_MINS", 90),
            min_arb_edge=_float("MIN_ARB_EDGE", 0.03),
            below_gate_enabled=_bool("BELOW_GATE_ENABLED", False),
            same_day_reserve_slots=_int("SAME_DAY_RESERVE_SLOTS", 0),
            same_day_reserve_after_hour_utc=_int("SAME_DAY_RESERVE_AFTER_HOUR_UTC", 18),
            ntfy_topic=os.getenv("NTFY_TOPIC", ""),
        )


# Module-level singleton — call get_config() instead of constructing BotConfig directly
_CONFIG: BotConfig | None = None


def get_config() -> BotConfig:
    """Return the global BotConfig singleton, loading from env on first call."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = BotConfig.from_env()
    return _CONFIG


def reset_config() -> None:
    """Reset the singleton (used in tests)."""
    global _CONFIG
    _CONFIG = None
```

- [ ] **Step 3: Gradually migrate one module**

Start with `paper.py` — replace the inline `os.getenv("BREAKEVEN_TRIGGER_PCT", "0.75")` etc. with:

```python
from config import get_config

# In the function that reads BREAKEVEN_TRIGGER_PCT:
_cfg = get_config()
_breakeven_trigger_pct = _cfg.breakeven_trigger_pct
```

Do NOT migrate all modules at once — do one module per commit to keep diffs reviewable.

- [ ] **Step 4: Run the config tests**

```
pytest tests/test_config_validation.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit `config.py`**

```
git add config.py tests/test_config_validation.py
git commit -m "feat(arch): BotConfig dataclass in config.py — single source of truth for all env var config"
```

---

## G3: Split `main.py` CLI Commands

**Problem:** `main.py` contains the CLI dispatcher, all `_cmd_*` functions, logging setup, config validation, and the main loop. It's likely 500+ lines. The CLI commands should be in a `commands/` directory or a `cli.py` module.

**Files:**
- Create: `cli.py` — dispatch and all `_cmd_*` functions extracted from `main.py`
- Modify: `main.py` — reduce to: imports, `_setup_logging()`, `_validate_config()`, and the `if __name__ == "__main__":` block that calls `cli.main()`
- Test: `tests/test_commands.py`

- [ ] **Step 1: Audit `main.py` line count and function list**

```
python -c "
import ast, sys
tree = ast.parse(open('main.py').read())
fns = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
print(f'{len(open(\"main.py\").readlines())} lines, {len(fns)} functions: {fns}')
"
```

- [ ] **Step 2: Write failing test for CLI dispatch**

```python
# tests/test_commands.py
def test_cli_dispatch_emos_train_exists():
    from cli import dispatch
    import sys
    # dispatch("emos-train") should call _cmd_emos_train without error
    # (mocked to avoid actually running)
    called = []
    import cli as _cli
    original = getattr(_cli, "_cmd_emos_train", None)
    if original is None:
        pytest.skip("_cmd_emos_train not yet in cli.py — expected after migration")
    _cli._cmd_emos_train = lambda: called.append("emos-train")
    dispatch("emos-train")
    assert called == ["emos-train"]
    _cli._cmd_emos_train = original
```

- [ ] **Step 3: Create `cli.py` with the extracted dispatch and `_cmd_*` functions**

Move all `_cmd_*` functions from `main.py` to `cli.py`. Add:

```python
"""CLI command dispatch for the Kalshi weather trading bot.

Each public CLI subcommand maps to a _cmd_* function in this module.
main.py calls dispatch() with the first argument.
"""

def dispatch(cmd: str) -> None:
    """Dispatch to the appropriate command handler."""
    _COMMANDS = {
        "loop":          _cmd_loop,
        "scan":          _cmd_scan,
        "analyze":       _cmd_analyze,
        "emos-train":    _cmd_emos_train,
        "backfill-emos": _cmd_backfill_emos,
        "calibrate":     _cmd_calibrate,
        "admin":         _cmd_admin,
        "status":        _cmd_status,
    }
    handler = _COMMANDS.get(cmd)
    if handler is None:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(_COMMANDS)}")
        raise SystemExit(1)
    handler()
```

- [ ] **Step 4: Update `main.py` to call `cli.dispatch`**

```python
# main.py — reduced to essentials
from cli import dispatch

if __name__ == "__main__":
    import sys
    _setup_logging()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "loop"
    if cmd not in ("help", "--help", "-h"):
        _validate_config()
    dispatch(cmd)
```

- [ ] **Step 5: Run all CLI-related tests**

```
pytest tests/test_commands.py tests/test_config_validation.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```
git add cli.py main.py tests/test_commands.py
git commit -m "refactor(arch): extract CLI command handlers to cli.py — main.py is now the thin entrypoint"
```

---

## G2: Split `weather_markets.py`

*Defer until after graduation — do NOT start before 150-200 settled trades.*

*See `docs/superpowers/plans/do-after-graduation.md` for rationale.*

**Proposed split when ready:**
- `weather_markets.py` → keep `analyze_trade()`, signal generation, market scanning
- `ensemble_fetch.py` → all Open-Meteo API calls (`get_ensemble_temps`, HRRR, Previous Runs)
- `probability_calc.py` → blend weights, exceedance fraction, EMOS calls, temperature scaling
- `metar_lock.py` → METAR observation fetch, lock-in logic, dew point correction

Each resulting file should be < 400 lines.

---

## G4: Split `paper.py`

*Defer until after graduation — do NOT start before 150-200 settled trades.*

*See `docs/superpowers/plans/do-after-graduation.md` for rationale.*

**Proposed split when ready:**
- `paper.py` → keep `place_paper_order()`, `settle_paper_trade()`, `load_paper_trades()`, `save_paper_trades()`
- `paper_analytics.py` → `get_profit_factor()`, `get_portfolio_expected_value()`, `get_edge_realization_by_city()`, all aggregate reporting functions
- `paper_exits.py` → `check_early_exits()`, `_check_breakeven_exits()`, `partial_close_position()`, take-profit ladder

Each resulting file should be < 300 lines.
