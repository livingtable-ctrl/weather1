# Category E: Infrastructure & Operations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden operational reliability: log rotation (E1), database VACUUM scheduling (E2), circuit breaker state persistence across restarts (E3), dead man's switch (E4), paper trades to SQLite (E5), config validation on startup (E6), health endpoint (E7), SYNCHRONOUS=NORMAL (E11), analysis_attempts pruning (E10), and dynamic station bias training fix (E12 — correctness bug, highest priority).

**Architecture:** E12 (correctness bug fix) and E6 (startup validation) are the most urgent. E5 (paper trades to SQLite) is a large refactor that unlocks better analytics. E3 (circuit state persistence) and E4 (dead man's switch) are safety improvements. All others are maintenance/reliability.

**Tech Stack:** Python 3.14, SQLite (WAL mode), pytest, logging module.

**Implementation Order:** E12 → E6 → E3 → E1 → E2 → E11 → E4 → E7 → E10 → E5

---

## E12: Fix Dynamic Station Bias Training (Correctness Bug)

**Problem:** `paper._score_ensemble_members()` logs forecast accuracy after settlement. It fetches `actual_temp` from `nws.get_live_observation()` — a live METAR reading at settlement time (e.g., 5 PM). For above-condition markets, this reading can be 5–10°F lower than the daily HIGH that Kalshi actually settled on. The bug trains the dynamic station bias model with inverted error signs, corrupting `get_dynamic_station_bias()` readings. Must be fixed before 10+ samples accumulate per city. `settled_temp_f` (the Kalshi-official daily max) is already available in the trade dict at settlement time and is the correct value to use.

**Files:**
- Read: `paper.py:955` — `_score_ensemble_members()` — where the actual_temp bug lives
- Modify: `paper.py` — use `trade.get("settled_temp_f")` instead of live NWS observation

- [ ] **Step 1: Confirm the call site**

Verify the bug location:

```
grep -n "get_live_observation\|actual_temp\|settled_temp_f" paper.py | head -20
```

Confirm that `_score_ensemble_members` at `paper.py:955` calls `nws.get_live_observation` for `actual_temp`, not `trade.get("settled_temp_f")`.

- [ ] **Step 2: Write failing test**

**Architecture of the actual call chain (verified 2026-06-27):**
- `paper._score_ensemble_members(trade, outcome_yes)` at `paper.py:955` logs bias training data
- It calls `nws.get_live_observation(city, coords)` to get `actual_temp` — this is the METAR
  current-temperature snapshot, NOT the Kalshi settled daily max
- It then calls `tracker.log_member_score(city, model, predicted_temp, actual_temp, target_date)`
- `tracker.get_dynamic_station_bias(city)` reads back the mean signed error from `ensemble_member_scores`

The bug: `actual_temp` is `obs["temp_f"]` from a live METAR at settlement time, not `settled_temp_f`.

```python
# tests/test_paper_metrics.py — add (paper_metrics covers paper.py util functions)
def test_score_ensemble_members_uses_settled_temp_not_metar(monkeypatch, tmp_path):
    """_score_ensemble_members must log settled_temp_f as actual_temp, not live METAR.

    The live METAR at 5 PM may be 81°F even though the daily high (Kalshi-settled) was 88°F.
    Using METAR temperature trains the bias model on the wrong observation.
    """
    import tracker
    import paper

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    # Trade dict with the actual settled daily max stored
    trade = {
        "ticker": "KXHIGHNY-26JUL04-T85",
        "city": "NYC",
        "target_date": "2026-07-04",
        "forecast_temp": 85.0,    # blended forecast that was used at trade entry
        "settled_temp_f": 88.0,   # Kalshi official daily max — this is what we want
    }

    # Patch nws.get_live_observation to return a different (wrong) temperature
    monkeypatch.setattr(
        "paper.nws",
        type("FakeNWS", (), {"get_live_observation": staticmethod(lambda *a, **k: {"temp_f": 81.0})}),
    )

    paper._score_ensemble_members(trade, outcome_yes=True)

    with tracker._conn() as con:
        rows = con.execute(
            "SELECT actual_temp FROM ensemble_member_scores WHERE city='NYC'"
        ).fetchall()

    assert rows, "_score_ensemble_members must insert at least one row"
    actual_temps = [r[0] for r in rows]
    assert all(t == pytest.approx(88.0, abs=0.1) for t in actual_temps), (
        f"Expected actual_temp=88.0 (settled daily max), got: {actual_temps}. "
        "The function is using METAR temperature (81.0) instead of settled_temp_f."
    )
```

- [ ] **Step 3: Run to confirm the test fails**

```
pytest tests/test_paper_metrics.py::test_score_ensemble_members_uses_settled_temp_not_metar -v
```
Expected: `AssertionError: Expected actual_temp=88.0, got [81.0]` — confirming the bug.

- [ ] **Step 4: Trace the actual call site**

Read `paper._score_ensemble_members` (at `paper.py:955`). The bug is on the line:
```python
actual_temp = obs.get("temp_f") if obs else None
```
This is the METAR current-temperature snapshot. The fix is to use `trade.get("settled_temp_f")` instead, because it is populated from the Kalshi outcome at settlement time.

- [ ] **Step 5: Fix `_score_ensemble_members` in `paper.py`**

Find `_score_ensemble_members` (around `paper.py:955`). Replace the live METAR fetch with:

```python
def _score_ensemble_members(trade: dict, outcome_yes: bool) -> None:
    """Log per-model forecast accuracy after settlement for _dynamic_model_weights().

    Uses settled_temp_f (the Kalshi-official daily HIGH or LOW) as the observed
    temperature, NOT a live METAR snapshot. METAR readings at settlement time are
    consistently lower than the daily max for above-condition markets, which would
    train the bias model with inverted error signs.
    """
    city = trade.get("city")
    target_date = trade.get("target_date")
    if not city or not target_date:
        return

    # Use Kalshi-official settled temperature, not a METAR snapshot
    actual_temp = trade.get("settled_temp_f")
    if actual_temp is None:
        _log.debug(
            "_score_ensemble_members: skipping %s — settled_temp_f not available",
            trade.get("ticker", "?"),
        )
        return

    _log.info(
        "station bias update: city=%s settled_temp=%.1f forecast=%.1f error=%.1f",
        city, actual_temp,
        trade.get("forecast_temp", float("nan")),
        actual_temp - trade.get("forecast_temp", actual_temp),
    )

    model_means: dict[str, float | None] = {
        "icon_seamless": trade.get("icon_forecast_mean"),
        "gfs_seamless": trade.get("gfs_forecast_mean"),
        "blended": trade.get("forecast_temp"),
    }
    try:
        from tracker import log_member_score as _log_ms

        for model, predicted_temp in model_means.items():
            if predicted_temp is not None:
                _log_ms(city, model, predicted_temp, actual_temp, target_date)
    except Exception as exc:
        _log.debug("_score_ensemble_members: skipped tracker update: %s", exc)
```

**Note:** `settled_temp_f` is populated by `settle_paper_trade()` which calls `auto_settle_paper_trades()` with the Kalshi-synced settlement value. Verify that `settle_paper_trade` includes `"settled_temp_f": outcome["settled_temp_f"]` in the trade dict before calling `_score_ensemble_members`.

- [ ] **Step 6: Run the regression test**

```
pytest tests/test_paper_metrics.py::test_score_ensemble_members_uses_settled_temp_not_metar -v
```
Expected: PASS

- [ ] **Step 7: Run the full paper test file**

```
pytest tests/test_paper_metrics.py -v
```
Expected: all PASS

- [ ] **Step 8: Commit**

```
git add paper.py tests/test_paper_metrics.py
git commit -m "fix(bias): use Kalshi settled_temp_f (daily max) for station bias training, not METAR snapshot"
```

---

## E6: Config Validation on Startup

**Problem:** Missing `.env` variables (e.g., `KALSHI_API_KEY`) cause silent failures or cryptic errors deep in a cron run. Startup should validate all required config and fail loudly.

**Files:**
- Modify: `main.py` — add `_validate_config()` call before any loop/cron command
- Test: `tests/test_config_validation.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config_validation.py
import pytest
import os

def test_validate_config_raises_when_key_missing(monkeypatch):
    import main
    monkeypatch.delenv("KALSHI_API_KEY", raising=False)
    monkeypatch.delenv("KALSHI_API_SECRET", raising=False)
    with pytest.raises(SystemExit) as exc:
        main._validate_config()
    assert exc.value.code != 0

def test_validate_config_passes_with_all_required_vars(monkeypatch):
    import main
    monkeypatch.setenv("KALSHI_API_KEY", "test-key")
    monkeypatch.setenv("KALSHI_API_SECRET", "test-secret")
    # Should not raise
    try:
        main._validate_config()
    except SystemExit as e:
        # May exit for other missing vars — check it's not the API key one
        pytest.fail(f"validate_config raised SystemExit({e.code})")
```

- [ ] **Step 2: Add `_validate_config()` to `main.py`**

```python
_REQUIRED_ENV_VARS = [
    ("KALSHI_API_KEY",    "Kalshi API key — get from Kalshi account settings"),
    ("KALSHI_API_SECRET", "Kalshi API secret — get from Kalshi account settings"),
]

_OPTIONAL_ENV_VARS_WITH_DEFAULTS = {
    "KALSHI_ENV":              "demo",
    "MIN_KELLY_FRACTION":      "0.05",
    "KELLY_CAP":               "0.25",
    "MAX_POSITIONS_PER_DATE":  "4",
    "MAX_SAME_DAY_POSITIONS":  "8",
    "PAPER_MIN_EDGE":          "0.07",
    "BREAKEVEN_TRIGGER_PCT":   "0.30",
    "GFS_LOCKOUT_MINS":        "90",
}


def _validate_config() -> None:
    """Validate required environment variables and warn about missing optionals.

    Exits with code 1 if any required variable is missing.
    Logs warnings for optional variables using their defaults.
    """
    import os
    missing = []
    for var, description in _REQUIRED_ENV_VARS:
        if not os.getenv(var):
            missing.append(f"  {var}: {description}")

    if missing:
        print("FATAL: Missing required environment variables:")
        for m in missing:
            print(m)
        print("\nAdd these to your .env file and restart.")
        raise SystemExit(1)

    for var, default in _OPTIONAL_ENV_VARS_WITH_DEFAULTS.items():
        if not os.getenv(var):
            _log.debug("config: %s not set, using default=%s", var, default)
```

- [ ] **Step 3: Call `_validate_config()` in `main.py` before any loop/cron command**

Find the top-level dispatch in `main.py`. Before the `if cmd == "loop"` or `elif cmd == "cron"` branch, add:

```python
if cmd in ("loop", "cron", "scan", "analyze", "emos-train", "backfill-emos"):
    _validate_config()
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_config_validation.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```
git add main.py tests/test_config_validation.py
git commit -m "feat(ops): validate required env vars on startup — fail loudly before any cron run"
```

---

## E3: Circuit Breaker State Persistence

**Problem:** `circuit_breaker.py` holds state (CLOSED/OPEN/HALF_OPEN, failure counts, last-failure timestamp) in memory. On process restart, the breaker resets to CLOSED regardless of whether the API was actually healthy. A persistent breaker would maintain protection across restarts.

**Files:**
- Modify: `circuit_breaker.py` — persist state to `data/circuit_state.json` on every transition
- Modify: `circuit_breaker.py` — load persisted state on `CircuitBreaker.__init__`
- Test: `tests/test_flash_crash_cb.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_flash_crash_cb.py — add
def test_circuit_breaker_restores_open_state_after_restart(tmp_path, monkeypatch):
    """When a breaker is OPEN and the process restarts, the breaker must remain OPEN."""
    from circuit_breaker import CircuitBreaker

    state_path = tmp_path / "circuit_state.json"
    # Create a breaker, trip it, and check state is saved
    cb = CircuitBreaker(name="test_api", failure_threshold=1, state_path=state_path)
    cb.record_failure()  # trips to OPEN

    assert cb.get_state() == "OPEN"

    # Simulate restart: create a new CircuitBreaker instance with same state_path
    cb2 = CircuitBreaker(name="test_api", failure_threshold=1, state_path=state_path)
    assert cb2.get_state() == "OPEN", "State must persist across restart"
```

- [ ] **Step 2: Add state persistence to `CircuitBreaker`**

Read the existing `CircuitBreaker` class first. Then add:

```python
import json
import threading
from pathlib import Path
from datetime import datetime, UTC

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3,
                 recovery_timeout_seconds: int = 300,
                 state_path: Path | None = None):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout_seconds
        self._lock = threading.Lock()
        self._state_path = state_path or Path("data") / f"circuit_{name}.json"

        # Attempt to restore from disk
        self._state = "CLOSED"
        self._failure_count = 0
        self._last_failure_time: datetime | None = None
        self._load_state()

    def _load_state(self) -> None:
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text())
                self._state = data.get("state", "CLOSED")
                self._failure_count = int(data.get("failure_count", 0))
                lft = data.get("last_failure_time")
                if lft:
                    self._last_failure_time = datetime.fromisoformat(lft)
        except Exception:
            pass  # corrupt state file → start fresh CLOSED

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(exist_ok=True)
            payload = {
                "state": self._state,
                "failure_count": self._failure_count,
                "last_failure_time": self._last_failure_time.isoformat() if self._last_failure_time else None,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._state_path.write_text(json.dumps(payload, indent=2))
        except Exception:
            pass  # non-critical: log and continue

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now(UTC)
            if self._failure_count >= self.failure_threshold:
                self._state = "OPEN"
            self._save_state()

    def record_success(self) -> None:
        with self._lock:
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
                self._failure_count = 0
                self._last_failure_time = None
            self._save_state()

    def get_state(self) -> str:
        with self._lock:
            if self._state == "OPEN" and self._last_failure_time:
                elapsed = (datetime.now(UTC) - self._last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    self._state = "HALF_OPEN"
                    self._save_state()
            return self._state
```

- [ ] **Step 3: Run the persistence test**

```
pytest tests/test_flash_crash_cb.py -v
```
Expected: all PASS

- [ ] **Step 4: Commit**

```
git add circuit_breaker.py tests/test_flash_crash_cb.py
git commit -m "feat(ops): persist circuit breaker state across restarts (data/circuit_*.json)"
```

---

## E1: Log Rotation

**Problem:** `bot.log` grows unboundedly. On Windows, it can reach gigabytes. The existing `logging.FileHandler` doesn't rotate. `RotatingFileHandler` fixes this with a 10MB cap and 5 backups.

**Files:**
- Modify: `main.py` (or wherever `logging.basicConfig` / `FileHandler` is called)
- Test: `tests/test_log_rotation.py`

- [ ] **Step 1: Find the logging setup**

```
grep -n "FileHandler\|basicConfig\|bot.log" main.py cron.py
```

Identify the exact line that creates the file handler.

- [ ] **Step 2: Write failing test**

```python
# tests/test_log_rotation.py
def test_log_handler_is_rotating(tmp_path, monkeypatch):
    """The file log handler must be RotatingFileHandler, not FileHandler."""
    import logging
    import main

    # Re-initialize logging with a temp path
    test_log = tmp_path / "bot.log"
    monkeypatch.setenv("LOG_FILE", str(test_log))

    main._setup_logging(log_file=str(test_log))

    # Find the file handler on the root logger
    root_handlers = logging.getLogger().handlers
    file_handlers = [h for h in root_handlers if hasattr(h, 'baseFilename')]
    assert file_handlers, "No file handler found on root logger"
    from logging.handlers import RotatingFileHandler
    assert isinstance(file_handlers[0], RotatingFileHandler), (
        f"Expected RotatingFileHandler, got {type(file_handlers[0]).__name__}"
    )
```

- [ ] **Step 3: Add `_setup_logging()` to `main.py`**

Replace the existing `logging.basicConfig(...)` or `FileHandler(...)` call with:

```python
def _setup_logging(log_file: str = "bot.log") -> None:
    """Configure rotating file handler (10 MB × 5 backups) and console handler."""
    from logging.handlers import RotatingFileHandler
    import logging

    log_format = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-20s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Rotating file: 10 MB max, 5 backups
    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(log_format)
    fh.setLevel(logging.DEBUG)

    # Console: INFO and above
    ch = logging.StreamHandler()
    ch.setFormatter(log_format)
    ch.setLevel(logging.INFO)

    # Remove any existing handlers before adding ours
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(fh)
    root.addHandler(ch)
```

Call `_setup_logging()` at the top of `if __name__ == "__main__":`.

- [ ] **Step 4: Run the test**

```
pytest tests/test_log_rotation.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add main.py tests/test_log_rotation.py
git commit -m "feat(ops): rotating file log handler (10MB × 5 backups)"
```

---

## E2: Weekly VACUUM Scheduling

**Problem:** SQLite WAL mode accumulates deleted rows as free pages. After 500+ writes (predictions, outcomes, ensemble scores), the database can be 2–3× its logical size. `VACUUM` defragments and reclaims space. It should run weekly during a low-activity window.

**Files:**
- Modify: `tracker.py` — add `vacuum_database()`
- Modify: `cron.py` — call `vacuum_database()` once per week (check `last_vacuum_at` in a file)

- [ ] **Step 1: Write failing test**

```python
# tests/test_cleanup_data_dir.py — add
def test_vacuum_database_runs_without_error(tmp_path, monkeypatch):
    import tracker
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    # Insert some rows and delete them to create fragmentation
    with tracker._conn() as con:
        for i in range(100):
            con.execute("INSERT INTO predictions (ticker, our_prob, market_prob, created_at, days_out) "
                        "VALUES (?, 0.5, 0.5, '2026-01-01', 1)", (f"TICKER-{i}",))
        con.execute("DELETE FROM predictions WHERE ticker LIKE 'TICKER-%'")

    # VACUUM should run without error
    tracker.vacuum_database()
```

- [ ] **Step 2: Add `vacuum_database()` to `tracker.py`**

```python
def vacuum_database() -> None:
    """Run SQLite VACUUM to reclaim free pages after bulk deletes.

    WAL mode requires setting WAL to DELETE temporarily for VACUUM.
    This is a blocking operation — call only during low-activity windows.
    Emits INFO log with before/after page counts.
    """
    import logging
    _log = logging.getLogger(__name__)
    init_db()
    with _conn() as con:
        before = con.execute("PRAGMA page_count").fetchone()[0]
        # WAL mode: must checkpoint before VACUUM is effective
        con.execute("PRAGMA wal_checkpoint(FULL)")
        con.execute("VACUUM")
        after = con.execute("PRAGMA page_count").fetchone()[0]
        _log.info("VACUUM complete: page_count %d → %d (freed %d pages)", before, after, before - after)
```

- [ ] **Step 3: Wire into cron with weekly cadence**

In `cron.py`, at the top of `_cron_scan_inner()`, add:

```python
# Weekly VACUUM — checks last-run timestamp stored in a file
_VACUUM_STATE_PATH = Path("data") / "last_vacuum.txt"
def _should_vacuum() -> bool:
    """Return True if more than 7 days have passed since last VACUUM."""
    try:
        if _VACUUM_STATE_PATH.exists():
            from datetime import UTC, datetime, timedelta
            last = datetime.fromisoformat(_VACUUM_STATE_PATH.read_text().strip())
            return (datetime.now(UTC) - last).days >= 7
        return True  # first run
    except Exception:
        return False  # on error, skip VACUUM

if _should_vacuum():
    try:
        from tracker import vacuum_database
        vacuum_database()
        from datetime import UTC, datetime
        _VACUUM_STATE_PATH.write_text(datetime.now(UTC).isoformat())
    except Exception as _vac_exc:
        _log.warning("VACUUM failed: %s", _vac_exc)
```

- [ ] **Step 4: Run the test**

```
pytest tests/test_cleanup_data_dir.py::test_vacuum_database_runs_without_error -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add tracker.py cron.py tests/test_cleanup_data_dir.py
git commit -m "feat(ops): weekly SQLite VACUUM to reclaim free pages after deletions"
```

---

## E11: SYNCHRONOUS=NORMAL for SQLite WAL

**Problem:** By default, SQLite uses `SYNCHRONOUS=FULL` which issues `fsync()` after every write. In WAL mode, `SYNCHRONOUS=NORMAL` is safe (WAL journal ensures crash recovery) and 5–10× faster for writes.

**Files:**
- Modify: `tracker.py` — add `PRAGMA synchronous=NORMAL` to `init_db()`

- [ ] **Step 1: Write test confirming pragma is set**

```python
def test_db_uses_synchronous_normal(tmp_path, monkeypatch):
    import tracker
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()
    with tracker._conn() as con:
        result = con.execute("PRAGMA synchronous").fetchone()[0]
    # NORMAL = 1, FULL = 2, OFF = 0
    assert result == 1, f"Expected synchronous=NORMAL(1), got {result}"
```

- [ ] **Step 2: Add to `init_db()` in `tracker.py`**

Find `init_db()` where `PRAGMA journal_mode=WAL` is set. Add immediately after:

```python
con.execute("PRAGMA synchronous=NORMAL")
```

- [ ] **Step 3: Run the test**

```
pytest tests/test_cleanup_data_dir.py::test_db_uses_synchronous_normal -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```
git add tracker.py
git commit -m "perf(db): PRAGMA synchronous=NORMAL — safe with WAL, 5-10x faster writes"
```

---

## E4: Dead Man's Switch (48-Hour Alert)

**Problem:** If the bot fails silently (Windows sleep, power loss, process crash), no alert is sent. A dead man's switch file (`last_heartbeat.txt`) updated on every cron cycle, with a separate check that alerts if no update in 48 hours, provides early warning.

**Files:**
- Modify: `cron.py` — update `last_heartbeat.txt` on every cycle
- Add: `watchdog.py` — standalone script that checks the heartbeat and sends a push notification
- Test: `tests/test_dead_man.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_dead_man.py
import pytest
from pathlib import Path
from datetime import datetime, UTC, timedelta

def test_heartbeat_stale_detection(tmp_path, monkeypatch):
    from watchdog import is_heartbeat_stale

    heartbeat_file = tmp_path / "last_heartbeat.txt"
    monkeypatch.setattr("watchdog.HEARTBEAT_PATH", heartbeat_file)

    # No file → stale
    assert is_heartbeat_stale(max_age_hours=48) is True

    # Recent file → not stale
    heartbeat_file.write_text(datetime.now(UTC).isoformat())
    assert is_heartbeat_stale(max_age_hours=48) is False

    # Old file → stale
    old_time = (datetime.now(UTC) - timedelta(hours=49)).isoformat()
    heartbeat_file.write_text(old_time)
    assert is_heartbeat_stale(max_age_hours=48) is True
```

- [ ] **Step 2: Create `watchdog.py`**

```python
"""Dead man's switch watchdog.

Run with: py watchdog.py
Checks last_heartbeat.txt; if stale, sends a push notification via ntfy.sh
or emails the configured alert address.

Usage: add to a Windows Scheduled Task (NOT Task Scheduler — see standing rules).
Or run manually to check: py watchdog.py
"""
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

HEARTBEAT_PATH = Path("data") / "last_heartbeat.txt"
_log = logging.getLogger("watchdog")


def is_heartbeat_stale(max_age_hours: int = 48) -> bool:
    """Return True if the heartbeat file is missing or older than max_age_hours."""
    if not HEARTBEAT_PATH.exists():
        return True
    try:
        last = datetime.fromisoformat(HEARTBEAT_PATH.read_text().strip())
        # Ensure timezone-aware comparison
        if last.tzinfo is None:
            from datetime import timezone
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(UTC) - last) > timedelta(hours=max_age_hours)
    except Exception:
        return True  # corrupt file → treat as stale


def send_alert(message: str) -> None:
    """Send a push notification via ntfy.sh if NTFY_TOPIC is configured."""
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        print(f"[WATCHDOG ALERT] {message}")
        _log.warning("WATCHDOG: %s (set NTFY_TOPIC in .env to enable push notifications)", message)
        return
    try:
        import requests
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode(),
            headers={"Title": "Kalshi Bot Dead Man Switch", "Priority": "urgent", "Tags": "warning"},
            timeout=10,
        )
        resp.raise_for_status()
        _log.info("WATCHDOG alert sent to ntfy.sh/%s", topic)
    except Exception as exc:
        _log.error("WATCHDOG: failed to send alert: %s", exc)


def update_heartbeat() -> None:
    """Write current UTC timestamp to heartbeat file. Called by cron on every cycle."""
    HEARTBEAT_PATH.parent.mkdir(exist_ok=True)
    HEARTBEAT_PATH.write_text(datetime.now(UTC).isoformat(timespec="seconds"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if is_heartbeat_stale(max_age_hours=48):
        send_alert("Kalshi bot has not run in 48+ hours — check the bot process!")
    else:
        last = HEARTBEAT_PATH.read_text().strip()
        print(f"Bot is alive. Last heartbeat: {last}")
```

- [ ] **Step 3: Update heartbeat in `cron.py`**

At the end of `_cron_scan_inner()`, after a successful scan:

```python
from watchdog import update_heartbeat
update_heartbeat()
```

- [ ] **Step 4: Add `NTFY_TOPIC` to `.env.example`**

```bash
# Dead man's switch push notifications (free, no account required)
# Create a topic at https://ntfy.sh and put the topic name here
# NTFY_TOPIC=my_kalshi_bot_alerts
```

- [ ] **Step 5: Run the test**

```
pytest tests/test_dead_man.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```
git add watchdog.py cron.py tests/test_dead_man.py .env.example
git commit -m "feat(ops): dead man's switch — 48h heartbeat check with ntfy.sh push notification"
```

---

## E7: Health Endpoint

**Problem:** No HTTP health check endpoint. Tools like UptimeRobot and Windows monitoring scripts need a URL to probe. The dashboard already has Flask running — adding one route is trivial.

**Files:**
- Modify: `web_app.py` — add `/health` endpoint

- [ ] **Step 1: Add the endpoint**

In `web_app.py`, add without authentication:

```python
@_app.route("/health")
def health():
    """Public health check endpoint for monitoring tools.

    Returns 200 with system status summary.
    Does NOT require authentication — safe to expose to monitoring services.
    """
    from tracker import _conn, init_db
    import datetime

    try:
        init_db()
        with _conn() as con:
            row_count = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        db_ok = True
    except Exception:
        row_count = 0
        db_ok = False

    from paper import get_balance
    try:
        balance = get_balance()
        paper_ok = True
    except Exception:
        balance = 0.0
        paper_ok = False

    return {
        "status": "ok" if (db_ok and paper_ok) else "degraded",
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "db_ok": db_ok,
        "prediction_rows": row_count,
        "paper_ok": paper_ok,
        "balance": round(balance, 2),
    }, 200 if db_ok else 500
```

- [ ] **Step 2: Test manually**

```
curl http://localhost:5000/health
```
Expected: `{"status": "ok", "timestamp": "...", "db_ok": true, ...}`

- [ ] **Step 3: Commit**

```
git add web_app.py
git commit -m "feat(ops): add /health endpoint for monitoring tools (public, no auth)"
```

---

## E10: analysis_attempts Pruning

**Problem:** `analysis_attempts` or `analysis_cache` (depending on implementation) is never pruned. Old analysis records from months ago accumulate. Should keep only last 30 days.

**Files:**
- Read: `tracker.py` — find the `analysis_attempts` table or equivalent
- Modify: `tracker.py` — add `prune_old_analysis_attempts(days=30)`
- Modify: `cron.py` — call weekly alongside VACUUM

- [ ] **Step 1: Find the table**

```
grep -n "analysis_attempts\|analysis_cache" tracker.py
```

Read the schema to understand the timestamp column name.

- [ ] **Step 2: Add pruning function**

```python
def prune_old_analysis_attempts(days: int = 30) -> int:
    """Delete analysis_attempts rows older than N days. Returns deleted row count."""
    init_db()
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM analysis_attempts WHERE created_at < ?", (cutoff,)
        )
        n = cur.rowcount
    _log.info("pruned %d old analysis_attempts (older than %d days)", n, days)
    return n
```

- [ ] **Step 3: Wire into the same weekly maintenance block as VACUUM in `cron.py`**

```python
# Add alongside vacuum call:
try:
    from tracker import prune_old_analysis_attempts
    prune_old_analysis_attempts(days=30)
except Exception as _prune_exc:
    _log.warning("prune_old_analysis_attempts failed: %s", _prune_exc)
```

- [ ] **Step 4: Commit**

```
git add tracker.py cron.py
git commit -m "feat(ops): prune analysis_attempts older than 30 days (runs weekly with VACUUM)"
```

---

## E5: Paper Trades to SQLite

*Large refactor — defer until after EMOS is live and stable.*

**Problem:** `paper_trades.json` is an append-only flat JSON file. At 500+ trades it's slow to parse, prone to corruption on Windows atomic-write failures (WinError 32), and hard to query analytically.

**Migration plan (do NOT implement until paper_trades.json exceeds 300 KB):**
1. Add `paper_trades` table to `tracker.py` schema (new migration v30)
2. Write `migrate_paper_trades_json_to_sqlite()` that reads the JSON and inserts all rows
3. Update all `load_paper_trades()` calls to read from SQLite
4. Update all `save_paper_trades()` calls to upsert to SQLite
5. Keep JSON as read-only backup for 30 days, then delete
6. Add `get_open_positions()` as a SQL query (replaces Python list comprehension)

This is 6+ tasks and should have its own dedicated plan file when ready.
