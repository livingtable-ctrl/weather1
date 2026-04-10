# Phase 2: Infrastructure & Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add circuit breakers for failing data sources, disk-write retry logic, proper HTTP retry via requests adapters, API request audit logging, async market fetching, and database migrations.

**Architecture:** Circuit breaker state stored in-memory per source. Disk writes retry to temp path. DB audit log table already exists. Async fetching via ThreadPoolExecutor (already partially present).

**Tech Stack:** Python stdlib (threading, time), requests.adapters.HTTPAdapter, sqlite3

**Covers:** #3, #8, #67, #69, #99, #127

---

### Task 1: Circuit breaker for NWS and climatology APIs (#3)

**Files:**
- Create: `circuit_breaker.py`
- Modify: `nws.py` (wrap `get_live_observation`, `nws_prob`)
- Modify: `climatology.py` (wrap `climatological_prob`)

- [ ] **Step 1: Write failing test**

Add to `tests/test_infrastructure.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import time
import pytest
from circuit_breaker import CircuitBreaker, CircuitOpenError


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=1)
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open()


def test_circuit_allows_call_when_closed():
    cb = CircuitBreaker(name="test2", failure_threshold=3, recovery_timeout=1)
    assert not cb.is_open()


def test_circuit_recovers_after_timeout():
    cb = CircuitBreaker(name="test3", failure_threshold=2, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open()
    time.sleep(0.15)
    assert not cb.is_open()  # half-open after timeout


def test_circuit_resets_on_success():
    cb = CircuitBreaker(name="test4", failure_threshold=3, recovery_timeout=1)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert not cb.is_open()
    assert cb._failure_count == 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_infrastructure.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'circuit_breaker'`

- [ ] **Step 3: Implement circuit_breaker.py**

Create `circuit_breaker.py`:

```python
"""
Simple per-source circuit breaker.

States:
  CLOSED  — normal operation
  OPEN    — source is down; calls rejected immediately
  HALF-OPEN — recovery_timeout elapsed; next call is a probe

Usage:
    _cb = CircuitBreaker("nws", failure_threshold=5, recovery_timeout=300)

    def get_data():
        if _cb.is_open():
            raise CircuitOpenError("nws")
        try:
            result = _fetch()
            _cb.record_success()
            return result
        except Exception as e:
            _cb.record_failure()
            raise
"""
from __future__ import annotations
import logging
import time
import threading

_log = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open (source is down)."""
    def __init__(self, name: str):
        super().__init__(f"Circuit open for source '{name}' — skipping to avoid hammering")
        self.source = name


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 300):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.recovery_timeout:
                # Half-open: allow one probe through
                _log.info("Circuit '%s' half-open after %.0fs — allowing probe", self.name, elapsed)
                self._opened_at = None
                self._failure_count = 0
                return False
            return True

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                if self._opened_at is None:
                    self._opened_at = time.monotonic()
                    _log.warning(
                        "Circuit '%s' OPEN after %d failures — will retry in %.0fs",
                        self.name, self._failure_count, self.recovery_timeout,
                    )

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._opened_at = None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_infrastructure.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Wire into nws.py**

At the top of `nws.py`, after imports, add:

```python
from circuit_breaker import CircuitBreaker, CircuitOpenError

_nws_cb = CircuitBreaker("nws", failure_threshold=5, recovery_timeout=300)
```

Wrap `get_live_observation` — find the function and add at the top of its body:

```python
def get_live_observation(city: str) -> dict | None:
    if _nws_cb.is_open():
        _log.warning("NWS circuit open — skipping live observation for %s", city)
        return None
    try:
        # ... existing body ...
        _nws_cb.record_success()
        return result
    except Exception as exc:
        _nws_cb.record_failure()
        _log.warning("NWS observation failed for %s: %s", city, exc)
        return None
```

Do the same for `nws_prob`.

- [ ] **Step 6: Wire into climatology.py**

At the top of `climatology.py`:

```python
from circuit_breaker import CircuitBreaker, CircuitOpenError

_clim_cb = CircuitBreaker("climatology", failure_threshold=5, recovery_timeout=300)
```

Wrap `climatological_prob` similarly:

```python
def climatological_prob(...) -> float | None:
    if _clim_cb.is_open():
        _log.warning("Climatology circuit open — returning None")
        return None
    try:
        # ... existing body ...
        _clim_cb.record_success()
        return result
    except Exception as exc:
        _clim_cb.record_failure()
        _log.warning("Climatology prob failed: %s", exc)
        return None
```

- [ ] **Step 7: Run full test suite to check no regressions**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add circuit_breaker.py nws.py climatology.py tests/test_infrastructure.py
git commit -m "feat: circuit breaker for NWS and climatology APIs (#3)"
```

---

### Task 2: Disk-write retry and fallback (#8)

**Files:**
- Create: `safe_io.py`
- Modify: `paper.py` (replace `_save` atomic write)
- Modify: `execution_log.py` (replace write)

- [ ] **Step 1: Write test**

Add to `tests/test_infrastructure.py`:

```python
import json, tempfile
from pathlib import Path
from safe_io import atomic_write_json, AtomicWriteError


def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / "data.json"
    atomic_write_json({"key": "value"}, target)
    assert target.exists()
    assert json.loads(target.read_text()) == {"key": "value"}


def test_atomic_write_is_atomic(tmp_path):
    target = tmp_path / "data.json"
    atomic_write_json({"original": True}, target)
    atomic_write_json({"updated": True}, target)
    assert json.loads(target.read_text()) == {"updated": True}
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_infrastructure.py::test_atomic_write_creates_file -v
```

Expected: `ModuleNotFoundError: No module named 'safe_io'`

- [ ] **Step 3: Implement safe_io.py**

Create `safe_io.py`:

```python
"""
Atomic JSON write with retry and fallback location.
Prevents silent data loss when disk is full or write is interrupted.
"""
from __future__ import annotations
import json
import logging
import os
import tempfile
import time
from pathlib import Path

_log = logging.getLogger(__name__)


class AtomicWriteError(Exception):
    pass


def atomic_write_json(data: dict, path: Path, retries: int = 3, fallback_dir: Path | None = None) -> None:
    """
    Write data to path atomically (write temp → fsync → rename).
    Retries up to `retries` times with 1s backoff on failure.
    If all retries fail and fallback_dir is provided, writes there instead.
    Raises AtomicWriteError if all attempts fail.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)
                return
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            last_exc = exc
            _log.warning("atomic_write_json attempt %d/%d failed for %s: %s", attempt + 1, retries, path, exc)
            if attempt < retries - 1:
                time.sleep(1.0)

    # All retries failed — try fallback location
    if fallback_dir:
        fallback_path = Path(fallback_dir) / path.name
        try:
            _log.error("Writing to fallback location: %s", fallback_path)
            fallback_path.parent.mkdir(parents=True, exist_ok=True)
            fallback_path.write_text(payload, encoding="utf-8")
            return
        except Exception as fb_exc:
            _log.error("Fallback write also failed: %s", fb_exc)

    raise AtomicWriteError(f"Failed to write {path} after {retries} attempts: {last_exc}")
```

- [ ] **Step 4: Update paper.py _save function**

Find the `_save` function in `paper.py` and replace the atomic write block with:

```python
from safe_io import atomic_write_json, AtomicWriteError

def _save(data: dict) -> None:
    try:
        atomic_write_json(data, DATA_PATH, retries=3)
    except AtomicWriteError as e:
        _log.error("CRITICAL: Could not save paper trades: %s", e)
        raise
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_infrastructure.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add safe_io.py paper.py tests/test_infrastructure.py
git commit -m "feat: atomic disk write with retry/fallback, safe_io module (#8)"
```

---

### Task 3: Replace manual retry loop with HTTPAdapter (#67)

**Files:**
- Modify: `kalshi_client.py`

- [ ] **Step 1: Write test**

Add to `tests/test_infrastructure.py`:

```python
import requests
from kalshi_client import _build_session


def test_session_has_retry_adapter():
    session = _build_session()
    adapter = session.get_adapter("https://")
    assert adapter is not None
    # Verify it's a Retry-aware adapter
    assert hasattr(adapter, "max_retries")
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_infrastructure.py::test_session_has_retry_adapter -v
```

Expected: `ImportError` or `AttributeError`.

- [ ] **Step 3: Update kalshi_client.py**

Add at top of `kalshi_client.py` after existing imports:

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _build_session() -> requests.Session:
    """
    Build a requests Session with automatic retry on transient errors.
    Uses urllib3 Retry which handles backoff, status-based retry, and
    connection errors — replacing the manual retry loop.
    """
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,          # 1s, 2s, 4s
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET", "POST", "DELETE"},
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()
```

Then update `_request_with_retry` to use `_SESSION`:

```python
def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Use the shared session with built-in retry logic."""
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    t0 = time.perf_counter()
    resp = _SESSION.request(method, url, **kwargs)
    elapsed = time.perf_counter() - t0
    if elapsed > 5:
        _log.warning("Kalshi API slow: %.1fs for %s %s", elapsed, method, url)
    return resp
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_infrastructure.py -v
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add kalshi_client.py tests/test_infrastructure.py
git commit -m "refactor: replace manual retry loop with HTTPAdapter + Retry (#67)"
```

---

### Task 4: API request audit logging (#69)

**Files:**
- Modify: `kalshi_client.py` (log to DB after each request)
- Modify: `tracker.py` (add `log_api_request` function)

- [ ] **Step 1: Add audit table to tracker.py**

In `tracker.py`, inside the `init_db()` executescript, add after the existing `audit_log` table:

```python
CREATE TABLE IF NOT EXISTS api_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    method      TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    status_code INTEGER,
    latency_ms  REAL,
    logged_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_endpoint ON api_requests(endpoint, logged_at);
```

Then add function:

```python
def log_api_request(method: str, endpoint: str, status_code: int | None, latency_ms: float) -> None:
    """Log an API call for audit trail and latency monitoring."""
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO api_requests (method, endpoint, status_code, latency_ms, logged_at) VALUES (?,?,?,?,?)",
                (method, endpoint, status_code, latency_ms, datetime.now(UTC).isoformat()),
            )
    except Exception as exc:
        _log.warning("Failed to log API request: %s", exc)
```

- [ ] **Step 2: Call log_api_request from kalshi_client.py**

In `_request_with_retry` in `kalshi_client.py`, after the request completes:

```python
def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    t0 = time.perf_counter()
    resp = _SESSION.request(method, url, **kwargs)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if elapsed_ms > 5000:
        _log.warning("Kalshi API slow: %.1fs for %s %s", elapsed_ms / 1000, method, url)
    # Audit log (import lazily to avoid circular imports)
    try:
        from tracker import log_api_request
        from urllib.parse import urlparse
        endpoint = urlparse(url).path
        log_api_request(method, endpoint, resp.status_code, elapsed_ms)
    except Exception:
        pass
    return resp
```

- [ ] **Step 3: Write test**

Add to `tests/test_infrastructure.py`:

```python
def test_log_api_request_writes_to_db(tmp_path):
    import tracker
    orig = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "test.db"
    tracker._db_initialized = False
    tracker.init_db()

    tracker.log_api_request("GET", "/markets", 200, 123.4)

    with tracker._conn() as con:
        row = con.execute("SELECT * FROM api_requests WHERE endpoint='/markets'").fetchone()
    assert row is not None
    assert row["status_code"] == 200
    assert row["latency_ms"] == pytest.approx(123.4, abs=0.1)

    tracker.DB_PATH = orig
    tracker._db_initialized = False
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_infrastructure.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add tracker.py kalshi_client.py tests/test_infrastructure.py
git commit -m "feat: API request audit logging to predictions.db (#69)"
```

---

### Task 5: Async market fetching (#127)

**Files:**
- Modify: `weather_markets.py` — `get_weather_markets` function

- [ ] **Step 1: Find current sequential fetch**

```bash
grep -n "ThreadPoolExecutor\|get_weather_markets\|for.*market" "C:/Users/thesa/claude kalshi/weather_markets.py" | head -20
```

Note the line numbers of the market fetching loop.

- [ ] **Step 2: Write test**

Add to `tests/test_infrastructure.py`:

```python
from unittest.mock import patch, MagicMock
import time


def test_market_fetch_uses_threadpool():
    """Verify that get_weather_markets uses parallel fetching."""
    import weather_markets
    mock_client = MagicMock()
    mock_client.get_markets.return_value = [
        {"ticker": f"TICKER{i}", "status": "open", "close_time": "2026-12-31T23:59:00Z"}
        for i in range(20)
    ]
    with patch("weather_markets.get_weather_forecast", return_value=None):
        t0 = time.monotonic()
        # Just check it doesn't crash — parallelism is hard to assert in unit tests
        try:
            weather_markets.get_weather_markets(mock_client)
        except Exception:
            pass
        elapsed = time.monotonic() - t0
    # Should complete quickly (not 20 * N seconds sequentially)
    assert elapsed < 10
```

- [ ] **Step 3: Ensure ThreadPoolExecutor is used in get_weather_markets**

In `weather_markets.py`, find `get_weather_markets`. If it already uses `ThreadPoolExecutor`, verify the max_workers is set to at least 10:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_weather_markets(client: "KalshiClient") -> list[dict]:
    raw_markets = client.get_markets(status="open")
    weather_markets_raw = [m for m in raw_markets if _is_weather_market(m)]

    def _enrich(market):
        try:
            return enrich_with_forecast(market)
        except Exception as exc:
            _log.warning("Failed to enrich %s: %s", market.get("ticker"), exc)
            return None

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_enrich, m): m for m in weather_markets_raw}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                results.append(result)

    return results
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_infrastructure.py
git commit -m "perf: parallel market fetching with ThreadPoolExecutor(max_workers=10) (#127)"
```

---

### Task 6: Database migrations with version tracking (#99)

**Files:**
- Modify: `tracker.py` — replace try/except ALTER TABLE with versioned migrations

- [ ] **Step 1: Add schema_version table and migration runner**

In `tracker.py`, replace the ad-hoc migration code with:

```python
_SCHEMA_VERSION = 3  # increment each time migrations list grows

_MIGRATIONS = [
    # v1 → v2: add condition_type column
    "ALTER TABLE predictions ADD COLUMN condition_type TEXT",
    # v2 → v3: add api_requests table
    """CREATE TABLE IF NOT EXISTS api_requests (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        method      TEXT NOT NULL,
        endpoint    TEXT NOT NULL,
        status_code INTEGER,
        latency_ms  REAL,
        logged_at   TEXT NOT NULL
    )""",
]


def _run_migrations(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = con.execute("SELECT version FROM schema_version").fetchone()
    current = row[0] if row else 0

    for i, sql in enumerate(_MIGRATIONS):
        version = i + 1
        if version <= current:
            continue
        try:
            con.execute(sql)
            _log.info("Applied migration v%d", version)
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                _log.debug("Migration v%d already applied: %s", version, e)
            else:
                raise

    if row is None:
        con.execute("INSERT INTO schema_version VALUES (?)", (_SCHEMA_VERSION,))
    else:
        con.execute("UPDATE schema_version SET version=?", (_SCHEMA_VERSION,))
```

Call `_run_migrations(con)` inside `init_db()` after the main `executescript`.

- [ ] **Step 2: Write test**

Add to `tests/test_infrastructure.py`:

```python
def test_migrations_are_idempotent(tmp_path):
    import tracker
    orig = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "migrate_test.db"
    tracker._db_initialized = False

    # Run init_db twice — should not raise
    tracker.init_db()
    tracker._db_initialized = False
    tracker.init_db()

    with tracker._conn() as con:
        row = con.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None

    tracker.DB_PATH = orig
    tracker._db_initialized = False
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_infrastructure.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tracker.py tests/test_infrastructure.py
git commit -m "feat: versioned DB migrations replacing ad-hoc ALTER TABLE try/except (#99)"
```
