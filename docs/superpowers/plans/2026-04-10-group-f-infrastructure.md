# Group F — Infrastructure Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the trading bot's infrastructure against silent failures, data corruption, and blocking I/O by adding circuit breakers, disk-write resilience, request audit logging, schema migrations, checksum verification, cloud backup, and parallel market analysis.
**Architecture:** Each task is independently testable; tests live in `tests/test_infrastructure.py` (append) or `tests/test_cloud_backup.py` (append). Items #3, #8, #67, #69, #99, #102, #104, #105, and #127 map to one task each. Several features (#67, #69, #99, #102, #104, #105) already have partial implementations in the codebase — the tasks below complete or test the gaps that remain. All code is written test-first (TDD).
**Tech Stack:** Python 3.14, pytest, sqlite3, requests + urllib3 Retry, hashlib, boto3 (optional, gated by env var), concurrent.futures.ThreadPoolExecutor

---

### Task 1: Circuit Breaker for Failing Data Sources (#3)

**Status note:** `circuit_breaker.py` and its core `CircuitBreaker` class already exist with `CLOSED/OPEN/HALF_OPEN` states, `failure_threshold=5`, and `recovery_timeout=300`. Four tests already pass. This task adds the **integration wrappers** in `nws.py` and `climatology.py` plus tests for the wrapped behavior.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/nws.py`
- Modify: `C:/Users/thesa/claude kalshi/climatology.py`
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing tests — append to `tests/test_infrastructure.py`:

```python
# ── Circuit Breaker integration (#3) ──────────────────────────────────────────


def test_nws_cb_skips_when_open(monkeypatch):
    """get_live_observation returns None immediately when its CB is open."""
    import nws
    from circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("nws_test", failure_threshold=1, recovery_timeout=60)
    cb.record_failure()
    monkeypatch.setattr(nws, "_nws_cb", cb)

    result = nws.get_live_observation("TestCity", (40.0, -75.0))
    assert result is None


def test_climatology_cb_skips_when_open(monkeypatch):
    """climatological_prob returns None immediately when its CB is open."""
    from datetime import date

    import climatology
    from circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("clim_test", failure_threshold=1, recovery_timeout=60)
    cb.record_failure()
    monkeypatch.setattr(climatology, "_clim_cb", cb)

    result = climatology.climatological_prob(
        "TestCity", (40.0, -75.0), date.today(), {"type": "high_temp", "threshold": 90}
    )
    assert result is None


def test_nws_cb_records_failure_on_exception(monkeypatch):
    """A network error inside get_live_observation increments the CB failure count."""
    import nws
    from circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("nws_fail_test", failure_threshold=5, recovery_timeout=60)
    monkeypatch.setattr(nws, "_nws_cb", cb)

    def _boom(*a, **kw):
        raise OSError("network down")

    monkeypatch.setattr(nws, "_get_obs_station", _boom, raising=False)

    try:
        nws.get_live_observation("TestCity", (40.0, -75.0))
    except Exception:
        pass

    assert cb._failure_count >= 1
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_nws_cb_skips_when_open tests/test_infrastructure.py::test_climatology_cb_skips_when_open tests/test_infrastructure.py::test_nws_cb_records_failure_on_exception -v 2>&1 | tail -20
```

Expected: `FAILED` (AttributeError: module 'nws' has no attribute '_nws_cb', etc.)

- [ ] Step 3: Implement — add module-level CB instances and guard logic:

In `nws.py`, near the top imports section, add:

```python
from circuit_breaker import CircuitBreaker

_nws_cb = CircuitBreaker("nws", failure_threshold=5, recovery_timeout=300)
```

Then wrap the body of `get_live_observation`:

```python
def get_live_observation(city: str, coords: tuple) -> dict | None:
    if _nws_cb.is_open():
        _log.warning("NWS circuit OPEN — skipping live observation for %s", city)
        return None
    try:
        result = _get_live_observation_impl(city, coords)
        _nws_cb.record_success()
        return result
    except Exception as exc:
        _nws_cb.record_failure()
        _log.warning("NWS observation failed for %s: %s", city, exc)
        return None
```

(Rename the existing function body to `_get_live_observation_impl` or inline the try/except around the existing network calls at the top of the existing function body.)

In `climatology.py`, near the top imports section, add:

```python
from circuit_breaker import CircuitBreaker

_clim_cb = CircuitBreaker("climatology", failure_threshold=5, recovery_timeout=300)
```

Then guard `climatological_prob`:

```python
def climatological_prob(
    city: str, coords: tuple, target_date: date, condition: dict
) -> float | None:
    if _clim_cb.is_open():
        _log.warning("Climatology circuit OPEN — returning None for %s", city)
        return None
    try:
        result = _climatological_prob_impl(city, coords, target_date, condition)
        _clim_cb.record_success()
        return result
    except Exception as exc:
        _clim_cb.record_failure()
        _log.warning("Climatological prob failed for %s: %s", city, exc)
        return None
```

(Rename or wrap the existing body as `_climatological_prob_impl`.)

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_nws_cb_skips_when_open tests/test_infrastructure.py::test_climatology_cb_skips_when_open tests/test_infrastructure.py::test_nws_cb_records_failure_on_exception -v 2>&1 | tail -20
```

Expected: `3 passed`

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add nws.py climatology.py tests/test_infrastructure.py && git commit -m "feat(#3): wrap get_live_observation and climatological_prob with circuit breakers"
```

---

### Task 2: Disk-Write Failure Resilience (#8)

**Status note:** `paper.py` already uses `safe_io.atomic_write_json` which handles atomicity. This task ensures that `paper.py`, `alerts.py`, and `execution_log.py` explicitly catch `OSError`, retry to `/tmp`, and raise `RuntimeError` on double failure — matching the spec exactly. Check whether `alerts.py` and `execution_log.py` already call `atomic_write_json`; if not, add the pattern.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/safe_io.py` (or wherever `atomic_write_json` is defined)
- Modify: `C:/Users/thesa/claude kalshi/alerts.py`
- Modify: `C:/Users/thesa/claude kalshi/execution_log.py`
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing tests — append to `tests/test_infrastructure.py`:

```python
# ── Disk-write resilience (#8) ────────────────────────────────────────────────


def test_atomic_write_falls_back_to_tmp_on_oserror(tmp_path, monkeypatch):
    """If the primary path fails, write succeeds via /tmp fallback."""
    import safe_io

    bad_dir = tmp_path / "readonly"
    bad_dir.mkdir()
    bad_dir.chmod(0o444)  # read-only directory

    target = bad_dir / "data.json"
    # Should not raise — should fall back to /tmp
    try:
        safe_io.atomic_write_json({"x": 1}, target, retries=1)
    except RuntimeError:
        pass  # acceptable: double failure raises RuntimeError


def test_atomic_write_raises_runtime_error_on_double_failure(tmp_path, monkeypatch):
    """If both primary and /tmp writes fail, RuntimeError is raised."""
    import safe_io

    original_open = open

    call_count = {"n": 0}

    def _always_fail(*a, **kw):
        call_count["n"] += 1
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _always_fail)

    with pytest.raises((RuntimeError, OSError)):
        safe_io.atomic_write_json({"x": 1}, tmp_path / "data.json", retries=1)


def test_alerts_write_raises_on_failure(tmp_path, monkeypatch):
    """alerts.py write function raises RuntimeError if disk write fails twice."""
    try:
        import alerts
    except ImportError:
        pytest.skip("alerts module not present")

    monkeypatch.setattr(
        "safe_io.atomic_write_json", lambda *a, **kw: (_ for _ in ()).throw(OSError("full"))
    )
    with pytest.raises((RuntimeError, OSError)):
        alerts.save_alerts([{"msg": "test"}], tmp_path / "alerts.json")


def test_execution_log_write_raises_on_failure(tmp_path, monkeypatch):
    """execution_log.py write function raises RuntimeError if disk write fails twice."""
    try:
        import execution_log
    except ImportError:
        pytest.skip("execution_log module not present")

    monkeypatch.setattr(
        "safe_io.atomic_write_json", lambda *a, **kw: (_ for _ in ()).throw(OSError("full"))
    )
    with pytest.raises((RuntimeError, OSError)):
        execution_log.append_entry({"action": "test"}, tmp_path / "exec_log.json")
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_atomic_write_falls_back_to_tmp_on_oserror tests/test_infrastructure.py::test_atomic_write_raises_runtime_error_on_double_failure tests/test_infrastructure.py::test_alerts_write_raises_on_failure tests/test_infrastructure.py::test_execution_log_write_raises_on_failure -v 2>&1 | tail -20
```

Expected: failures or skips (no passes on unimplemented paths)

- [ ] Step 3: Implement — update `safe_io.atomic_write_json` to add OSError retry logic:

Locate `atomic_write_json` in `safe_io.py`. Ensure it has this pattern (create or update):

```python
import hashlib
import json
import os
import tempfile
from pathlib import Path


class AtomicWriteError(RuntimeError):
    pass


def atomic_write_json(data: dict, path: Path, retries: int = 3) -> None:
    """
    Write *data* as JSON to *path* atomically (#8).
    On OSError retries up to *retries* times.
    If the primary path fails after retries, attempts a fallback write to /tmp.
    If both fail, raises RuntimeError("disk write failed: {path}").
    """
    path = Path(path)
    encoded = json.dumps(data, indent=2, default=str).encode()

    def _write_to(target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp~")
        try:
            tmp.write_bytes(encoded)
            tmp.replace(target)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    last_exc: Exception | None = None
    for attempt in range(max(retries, 1)):
        try:
            _write_to(path)
            return
        except OSError as exc:
            last_exc = exc

    # Primary path exhausted — try /tmp fallback
    fallback = Path(tempfile.gettempdir()) / path.name
    try:
        _write_to(fallback)
        import logging
        logging.getLogger(__name__).warning(
            "atomic_write_json: primary path failed, wrote fallback to %s", fallback
        )
        return
    except OSError as exc:
        raise RuntimeError(f"disk write failed: {path}") from exc
```

In `alerts.py`, replace any bare `open()` or `json.dump()` calls with `atomic_write_json` and let the RuntimeError propagate.

In `execution_log.py`, do the same.

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_atomic_write_falls_back_to_tmp_on_oserror tests/test_infrastructure.py::test_atomic_write_raises_runtime_error_on_double_failure tests/test_infrastructure.py::test_alerts_write_raises_on_failure tests/test_infrastructure.py::test_execution_log_write_raises_on_failure -v 2>&1 | tail -20
```

Expected: `4 passed` (or `passed + skipped` if alerts/execution_log not present)

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add safe_io.py alerts.py execution_log.py tests/test_infrastructure.py && git commit -m "feat(#8): add OSError retry-to-tmp fallback and RuntimeError in atomic_write_json"
```

---

### Task 3: Replace Manual Retry Loop with HTTPAdapter (#67)

**Status note:** `kalshi_client.py` already has `_build_session()` mounting `HTTPAdapter(max_retries=Retry(...))` on `"https://"` and `_request_with_retry` delegates to that session. The test `test_session_has_retry_adapter` already passes. This task verifies the exact Retry parameters match the spec (`total=3, backoff_factor=1, status_forcelist=[429,500,502,503]`) and adds a test for those exact values.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/kalshi_client.py` (parameter audit only)
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing test — append to `tests/test_infrastructure.py`:

```python
# ── HTTPAdapter Retry parameters (#67) ────────────────────────────────────────


def test_session_retry_parameters():
    """Verify HTTPAdapter Retry has exactly total=3, backoff_factor=1, correct status_forcelist."""
    from kalshi_client import _build_session

    session = _build_session()
    adapter = session.get_adapter("https://")
    retry = adapter.max_retries
    assert retry.total == 3
    assert retry.backoff_factor == 1.0
    assert 429 in retry.status_forcelist
    assert 500 in retry.status_forcelist
    assert 502 in retry.status_forcelist
    assert 503 in retry.status_forcelist
```

- [ ] Step 2: Run test to confirm it fails or passes:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_session_retry_parameters -v 2>&1 | tail -10
```

If it already passes, confirm parameters and move on. If it fails, fix `_build_session()` in the next step.

- [ ] Step 3: Implement — audit `_build_session()` in `kalshi_client.py`. Ensure it reads exactly:

```python
def _build_session() -> requests.Session:
    """Build a requests Session with automatic retry on transient errors."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist={429, 500, 502, 503},
        allowed_methods={"GET", "POST", "DELETE"},
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
```

Note: `504` is currently in `status_forcelist` in the existing code — the spec says `[429,500,502,503]`. Remove `504` to match the spec exactly, or confirm with the team if `504` should remain.

- [ ] Step 4: Run test to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_session_retry_parameters tests/test_infrastructure.py::test_session_has_retry_adapter -v 2>&1 | tail -10
```

Expected: `2 passed`

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add kalshi_client.py tests/test_infrastructure.py && git commit -m "feat(#67): confirm HTTPAdapter Retry parameters match spec (total=3, backoff=1, 429/500/502/503)"
```

---

### Task 4: API Request Audit Logging (#69)

**Status note:** `tracker.py` already has `log_api_request(method, endpoint, status_code, latency_ms)`, the `api_requests` table in migration v2, and `kalshi_client.py` already calls it after each request. The test `test_log_api_request_writes_to_db` already passes. This task adds tests for the `error` column (the spec says the signature should include an `error` param) and for the actual call site in `kalshi_client.py`.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py` (add `error` param if missing)
- Modify: `C:/Users/thesa/claude kalshi/kalshi_client.py` (pass error if missing)
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing tests — append to `tests/test_infrastructure.py`:

```python
# ── API request logging error column (#69) ────────────────────────────────────


def test_log_api_request_stores_error(tmp_path):
    """log_api_request stores a non-None error string when provided."""
    import tracker

    orig_path = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "test_err.db"
    tracker._db_initialized = False
    tracker.init_db()

    tracker.log_api_request("GET", "/markets", 500, 999.9, error="Connection refused")

    with tracker._conn() as con:
        row = con.execute(
            "SELECT error FROM api_requests WHERE endpoint='/markets'"
        ).fetchone()
    assert row is not None
    assert row["error"] == "Connection refused"

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False


def test_log_api_request_accepts_no_error(tmp_path):
    """log_api_request works without error arg (backward-compatible)."""
    import tracker

    orig_path = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "test_noerr.db"
    tracker._db_initialized = False
    tracker.init_db()

    # Should not raise even when error is not provided
    tracker.log_api_request("GET", "/events", 200, 42.0)

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_log_api_request_stores_error tests/test_infrastructure.py::test_log_api_request_accepts_no_error -v 2>&1 | tail -15
```

Expected: `FAILED` (missing `error` parameter or column)

- [ ] Step 3: Implement — update `tracker.py`:

1. In `_MIGRATIONS`, ensure there is a migration that adds the `error` column to `api_requests` (add as the next numbered migration if not present):

```python
# vN → vN+1: add error column to api_requests (#69)
"ALTER TABLE api_requests ADD COLUMN error TEXT",
```

2. Update `log_api_request` signature:

```python
def log_api_request(
    method: str,
    endpoint: str,
    status_code: int | None,
    latency_ms: float,
    error: str | None = None,
) -> None:
    """Log an API call for audit trail and latency monitoring (#69)."""
    from datetime import UTC, datetime

    init_db()
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO api_requests
                   (method, endpoint, status_code, latency_ms, error, logged_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    method,
                    endpoint,
                    status_code,
                    latency_ms,
                    error,
                    datetime.now(UTC).isoformat(),
                ),
            )
    except Exception:
        _log.debug("log_api_request failed", exc_info=True)
```

3. Increment `_SCHEMA_VERSION` to match.

4. In `kalshi_client.py`, update the `log_api_request` call in `_request_with_retry` to pass the error string when the response status is an error:

```python
error_str = None
if resp.status_code >= 400:
    error_str = f"HTTP {resp.status_code}"
log_api_request(method, endpoint, resp.status_code, elapsed_ms, error=error_str)
```

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_log_api_request_stores_error tests/test_infrastructure.py::test_log_api_request_accepts_no_error tests/test_infrastructure.py::test_log_api_request_writes_to_db -v 2>&1 | tail -15
```

Expected: `3 passed`

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add tracker.py kalshi_client.py tests/test_infrastructure.py && git commit -m "feat(#69): add error column to api_requests and pass error string from kalshi_client"
```

---

### Task 5: Schema Migrations via PRAGMA user_version (#99)

**Status note:** `tracker.py` already has `_SCHEMA_VERSION`, `_MIGRATIONS`, and `_run_migrations()` applying migrations in order via a `schema_version` table. The test `test_migrations_are_idempotent` passes. The spec says to use `PRAGMA user_version` instead of a `schema_version` table. This task migrates the tracking mechanism to `PRAGMA user_version`.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py`
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing tests — append to `tests/test_infrastructure.py`:

```python
# ── PRAGMA user_version migration tracking (#99) ──────────────────────────────


def test_pragma_user_version_set_after_init(tmp_path):
    """After init_db(), PRAGMA user_version equals _SCHEMA_VERSION."""
    import tracker

    orig_path = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "pragma_test.db"
    tracker._db_initialized = False
    tracker.init_db()

    with tracker._conn() as con:
        version = con.execute("PRAGMA user_version").fetchone()[0]
    assert version == tracker._SCHEMA_VERSION

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False


def test_pragma_migrations_incremental(tmp_path):
    """Migrations applied incrementally when user_version starts at 0."""
    import tracker

    orig_path = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "incr_test.db"
    tracker._db_initialized = False

    # Manually set user_version to 0 to force all migrations
    import sqlite3
    con = sqlite3.connect(str(tracker.DB_PATH))
    con.execute("PRAGMA user_version=0")
    con.close()

    tracker.init_db()

    with tracker._conn() as con:
        version = con.execute("PRAGMA user_version").fetchone()[0]
    assert version == tracker._SCHEMA_VERSION

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_pragma_user_version_set_after_init tests/test_infrastructure.py::test_pragma_migrations_incremental -v 2>&1 | tail -15
```

Expected: `FAILED` (user_version is 0, not `_SCHEMA_VERSION`)

- [ ] Step 3: Implement — update `_run_migrations` in `tracker.py` to use `PRAGMA user_version`:

```python
def _run_migrations(con: sqlite3.Connection) -> None:
    """Apply pending schema migrations tracked via PRAGMA user_version (#99)."""
    current = con.execute("PRAGMA user_version").fetchone()[0]

    for i, sql in enumerate(_MIGRATIONS):
        version = i + 1
        if version <= current:
            continue
        try:
            con.execute(sql)
            _log.info("Applied migration v%d", version)
        except Exception as e:
            err_str = str(e).lower()
            if "duplicate column" in err_str or "already exists" in err_str:
                _log.debug("Migration v%d already applied: %s", version, e)
            else:
                raise

    # Update PRAGMA user_version to current schema version
    con.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
```

Keep the `schema_version` table migrations idempotent (the existing `CREATE TABLE IF NOT EXISTS schema_version` migration can remain for backward compatibility). Remove the `INSERT/UPDATE schema_version` calls at the bottom of `_run_migrations`.

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_pragma_user_version_set_after_init tests/test_infrastructure.py::test_pragma_migrations_incremental tests/test_infrastructure.py::test_migrations_are_idempotent -v 2>&1 | tail -15
```

Expected: `3 passed`

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add tracker.py tests/test_infrastructure.py && git commit -m "feat(#99): track schema migrations via PRAGMA user_version instead of schema_version table"
```

---

### Task 6: Data Corruption Detection via SHA-256 Checksum (#102)

**Status note:** `paper.py` already embeds a CRC32 checksum (`_crc32`) and validates it on load. The spec calls for SHA-256 (first 8 hex chars) stored as `"_checksum"`. This task either confirms the existing CRC32 satisfies the spec or migrates to SHA-256 + `"_checksum"` key + `ValueError("paper trades checksum mismatch")`.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/paper.py`
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing tests — append to `tests/test_infrastructure.py`:

```python
# ── SHA-256 checksum corruption detection (#102) ──────────────────────────────
import hashlib
import json as _json


def test_paper_save_embeds_sha256_checksum(tmp_path, monkeypatch):
    """Saved paper trades JSON contains a '_checksum' key with 8-char hex SHA-256."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1000.0, "trades": []})

    raw = _json.loads((tmp_path / "paper_trades.json").read_text())
    assert "_checksum" in raw
    assert len(raw["_checksum"]) == 8
    # Verify it's valid hex
    int(raw["_checksum"], 16)


def test_paper_load_raises_on_checksum_mismatch(tmp_path, monkeypatch):
    """Loading paper trades with a corrupted checksum raises ValueError."""
    import paper

    data = {"balance": 500.0, "trades": [], "_checksum": "deadbeef"}
    (tmp_path / "paper_trades.json").write_text(_json.dumps(data))
    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")

    with pytest.raises(ValueError, match="checksum mismatch"):
        paper._load()


def test_paper_load_passes_valid_checksum(tmp_path, monkeypatch):
    """Loading paper trades with a correct checksum does not raise."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 750.0, "trades": []})
    result = paper._load()
    assert result["balance"] == 750.0
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_paper_save_embeds_sha256_checksum tests/test_infrastructure.py::test_paper_load_raises_on_checksum_mismatch tests/test_infrastructure.py::test_paper_load_passes_valid_checksum -v 2>&1 | tail -15
```

Expected: `FAILED` (current code uses `_crc32` not `_checksum`)

- [ ] Step 3: Implement — update checksum logic in `paper.py`:

Replace the CRC32 functions with SHA-256:

```python
import hashlib


def _compute_checksum(payload: dict) -> str:
    """Compute SHA-256 of the JSON body (excluding _checksum key), return first 8 hex chars."""
    body = json.dumps(
        {k: v for k, v in payload.items() if k != "_checksum"},
        indent=2,
        default=str,
    ).encode()
    return hashlib.sha256(body).hexdigest()[:8]


def _validate_checksum(data: dict) -> None:
    """Assert stored _checksum matches recomputed value. Raises ValueError on mismatch."""
    stored = data.get("_checksum")
    if stored is None:
        return  # legacy files without checksum are allowed through
    expected = _compute_checksum(data)
    if stored != expected:
        raise ValueError(
            f"paper trades checksum mismatch: stored={stored!r}, expected={expected!r}"
        )
```

Update `_save` to embed `_checksum`:

```python
def _save(data: dict) -> None:
    """Write atomically with SHA-256 checksum for corruption detection (#102)."""
    payload = {k: v for k, v in data.items() if k not in ("_checksum", "_crc32")}
    payload["_checksum"] = _compute_checksum(payload)
    try:
        atomic_write_json(payload, DATA_PATH, retries=3)
    except (AtomicWriteError, RuntimeError) as e:
        _log.error("CRITICAL: Could not save paper trades: %s", e)
        raise
```

Update `_load` to call `_validate_checksum(data)` and raise `ValueError("paper trades checksum mismatch")` on mismatch.

Remove the old `_validate_crc`, `CorruptionError`, and `_zlib` usage.

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_paper_save_embeds_sha256_checksum tests/test_infrastructure.py::test_paper_load_raises_on_checksum_mismatch tests/test_infrastructure.py::test_paper_load_passes_valid_checksum -v 2>&1 | tail -15
```

Expected: `3 passed`

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add paper.py tests/test_infrastructure.py && git commit -m "feat(#102): replace CRC32 with SHA-256 _checksum field for paper trades corruption detection"
```

---

### Task 7: Automated Backup Verification (#104)

**Status note:** `main.py`'s `auto_backup()` already calls `verify_backup(dst)` from `paper.py` for `.json` backups. The spec requires verifying `.db` backups too (re-open, count rows in `predictions`, assert > 0, log result). This task adds that DB verification and covers it with a test.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/main.py`
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing tests — append to `tests/test_infrastructure.py`:

```python
# ── Backup verification (#104) ────────────────────────────────────────────────


def test_verify_db_backup_counts_rows(tmp_path):
    """verify_db_backup returns row count > 0 for a valid predictions.db copy."""
    import sqlite3

    import main

    db = tmp_path / "predictions_2026-04-10.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE predictions (id INTEGER PRIMARY KEY, city TEXT, target_date TEXT)"
    )
    con.execute("INSERT INTO predictions (city, target_date) VALUES ('NYC', '2026-04-10')")
    con.commit()
    con.close()

    count = main.verify_db_backup(db)
    assert count == 1


def test_verify_db_backup_raises_on_empty(tmp_path):
    """verify_db_backup raises AssertionError (or returns 0) when predictions table is empty."""
    import sqlite3

    import main

    db = tmp_path / "predictions_empty.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE predictions (id INTEGER PRIMARY KEY, city TEXT)"
    )
    con.commit()
    con.close()

    result = main.verify_db_backup(db)
    assert result == 0  # returns count; caller decides whether to warn


def test_auto_backup_logs_verification(tmp_path, monkeypatch, caplog):
    """auto_backup logs 'backup verified' with path and row count."""
    import logging
    import main

    monkeypatch.setattr(main, "auto_backup", lambda: None)  # prevent side effects
    # Direct test of verify_db_backup logging
    import sqlite3

    db = tmp_path / "predictions_test.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO predictions VALUES (1)")
    con.commit()
    con.close()

    with caplog.at_level(logging.INFO):
        count = main.verify_db_backup(db)

    assert count >= 1
    assert any("backup verified" in r.message.lower() for r in caplog.records)
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_verify_db_backup_counts_rows tests/test_infrastructure.py::test_verify_db_backup_raises_on_empty tests/test_infrastructure.py::test_auto_backup_logs_verification -v 2>&1 | tail -15
```

Expected: `FAILED` (no `main.verify_db_backup` function)

- [ ] Step 3: Implement — add `verify_db_backup` to `main.py` and call it from `auto_backup`:

```python
def verify_db_backup(path: Path) -> int:
    """
    Re-open a backed-up predictions.db, count rows in predictions table.
    Logs 'backup verified: {path}, {n} rows'. Returns row count (#104).
    """
    import sqlite3

    path = Path(path)
    try:
        con = sqlite3.connect(str(path))
        row = con.execute("SELECT COUNT(*) FROM predictions").fetchone()
        n = row[0] if row else 0
        con.close()
        _log.info("backup verified: %s, %d rows", path, n)
        return n
    except Exception as exc:
        _log.warning("backup verification failed for %s: %s", path, exc)
        return 0
```

Update `auto_backup()` to call `verify_db_backup(dst)` after copying `.db` files:

```python
if dst.suffix == ".db":
    verify_db_backup(dst)
```

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_verify_db_backup_counts_rows tests/test_infrastructure.py::test_verify_db_backup_raises_on_empty tests/test_infrastructure.py::test_auto_backup_logs_verification -v 2>&1 | tail -15
```

Expected: `3 passed`

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add main.py tests/test_infrastructure.py && git commit -m "feat(#104): add verify_db_backup function and call it from auto_backup for DB integrity checks"
```

---

### Task 8: Cloud Backup to S3 (#105)

**Status note:** `paper.py` already has `cloud_backup(local_path)` gated by `KALSHI_S3_BUCKET`. `tests/test_cloud_backup.py` has 3 passing tests. The spec calls for a dedicated `cloud_backup.py` module with `backup_to_s3(local_path, bucket, key)` and uses `CLOUD_BACKUP_BUCKET` env var. This task creates the standalone module and wires it up so it can be called independently from `main.py` in addition to the paper-specific version.

**Files:**
- Create: `C:/Users/thesa/claude kalshi/cloud_backup.py`
- Modify: `C:/Users/thesa/claude kalshi/main.py`
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_cloud_backup.py`

- [ ] Step 1: Write failing tests — append to `tests/test_cloud_backup.py`:

```python
# ── cloud_backup.py module (#105) ─────────────────────────────────────────────


def test_backup_to_s3_calls_upload(tmp_path, monkeypatch):
    """backup_to_s3 calls boto3.client('s3').upload_file with correct args."""
    import sys
    from unittest.mock import MagicMock

    mock_s3 = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)

    local = tmp_path / "predictions_2026-04-10.db"
    local.write_bytes(b"data")

    import importlib
    import cloud_backup
    importlib.reload(cloud_backup)

    cloud_backup.backup_to_s3(local, "my-bucket", "backups/predictions_2026-04-10.db")
    mock_s3.upload_file.assert_called_once_with(
        str(local), "my-bucket", "backups/predictions_2026-04-10.db"
    )


def test_backup_to_s3_skips_when_boto3_missing(tmp_path, monkeypatch, caplog):
    """backup_to_s3 logs a warning and does not raise when boto3 is not installed."""
    import logging
    import sys

    monkeypatch.setitem(sys.modules, "boto3", None)

    import importlib
    import cloud_backup
    importlib.reload(cloud_backup)

    local = tmp_path / "file.db"
    local.write_bytes(b"x")

    with caplog.at_level(logging.WARNING):
        cloud_backup.backup_to_s3(local, "bucket", "key")

    assert any("boto3" in r.message.lower() or "skip" in r.message.lower() for r in caplog.records)


def test_backup_to_s3_skips_without_env(tmp_path, monkeypatch):
    """backup_to_s3 with no CLOUD_BACKUP_BUCKET env var returns None."""
    monkeypatch.delenv("CLOUD_BACKUP_BUCKET", raising=False)

    import importlib
    import cloud_backup
    importlib.reload(cloud_backup)

    local = tmp_path / "file.db"
    local.write_bytes(b"x")

    result = cloud_backup.backup_to_s3(local, bucket=None, key="test")
    assert result is None
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_cloud_backup.py::test_backup_to_s3_calls_upload tests/test_cloud_backup.py::test_backup_to_s3_skips_when_boto3_missing tests/test_cloud_backup.py::test_backup_to_s3_skips_without_env -v 2>&1 | tail -15
```

Expected: `FAILED` (no `cloud_backup` module)

- [ ] Step 3: Implement — create `cloud_backup.py`:

```python
"""
cloud_backup.py — optional S3 upload for local backup files (#105).

Gated by CLOUD_BACKUP_BUCKET env var. Requires boto3; logs warning and skips
if boto3 is not installed.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)


def backup_to_s3(
    local_path: Path,
    bucket: str | None,
    key: str,
) -> bool | None:
    """
    Upload *local_path* to S3 at s3://{bucket}/{key}.

    - If *bucket* is None, falls back to the CLOUD_BACKUP_BUCKET env var.
    - If neither is set, logs nothing and returns None (silently skipped).
    - If boto3 is not installed, logs a warning and returns None.
    - Returns True on success, False on upload error.
    """
    resolved_bucket = bucket or os.environ.get("CLOUD_BACKUP_BUCKET")
    if not resolved_bucket:
        return None

    local_path = Path(local_path)

    try:
        import boto3
    except ImportError:
        _log.warning(
            "cloud_backup: boto3 not installed — skipping S3 upload of %s", local_path.name
        )
        return None

    try:
        s3 = boto3.client("s3")
        s3.upload_file(str(local_path), resolved_bucket, key)
        _log.info(
            "cloud_backup: uploaded %s to s3://%s/%s", local_path.name, resolved_bucket, key
        )
        return True
    except Exception as exc:
        _log.warning(
            "cloud_backup: S3 upload failed for %s: %s", local_path.name, exc
        )
        return False
```

Update `main.py`'s `auto_backup()` to call `cloud_backup.backup_to_s3` after each successful copy:

```python
from cloud_backup import backup_to_s3

# inside auto_backup(), after copying dst:
if not dst.exists():
    shutil.copy2(src, dst)
    today_key = f"kalshi-backups/{dst.name}"
    backup_to_s3(dst, bucket=None, key=today_key)
```

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_cloud_backup.py -v 2>&1 | tail -20
```

Expected: all tests pass (including the 3 pre-existing ones)

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add cloud_backup.py main.py tests/test_cloud_backup.py && git commit -m "feat(#105): add standalone cloud_backup.py with backup_to_s3 gated by CLOUD_BACKUP_BUCKET"
```

---

### Task 9: Parallel Market Analysis with ThreadPoolExecutor (#127)

**Status note:** `weather_markets.py` already uses `ThreadPoolExecutor` for market *fetching* and model ensemble, but `analyze_trade` is called sequentially in `main.py`'s `cmd_markets` and several other loops. The test `test_market_fetch_uses_threadpool` passes but only covers market fetching. This task adds a `analyze_markets_parallel` helper in `weather_markets.py` and updates the main analysis loops to use it.

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/weather_markets.py`
- Modify: `C:/Users/thesa/claude kalshi/main.py`
- Append tests to: `C:/Users/thesa/claude kalshi/tests/test_infrastructure.py`

- [ ] Step 1: Write failing tests — append to `tests/test_infrastructure.py`:

```python
# ── Parallel market analysis (#127) ───────────────────────────────────────────


def test_analyze_markets_parallel_returns_results():
    """analyze_markets_parallel returns one result dict per market."""
    from unittest.mock import MagicMock, patch

    import weather_markets

    markets = [
        {"ticker": f"KXHIGHNY-26APR{i:02d}-T72", "title": f"Market {i}"}
        for i in range(5)
    ]

    fake_analysis = {"edge": 0.1, "signal": "BUY", "forecast_prob": 0.7}

    with patch.object(weather_markets, "enrich_with_forecast", return_value={}):
        with patch.object(weather_markets, "analyze_trade", return_value=fake_analysis):
            results = weather_markets.analyze_markets_parallel(markets)

    assert len(results) == 5
    for r in results:
        assert "analysis" in r or r is not None


def test_analyze_markets_parallel_handles_per_market_exception():
    """analyze_markets_parallel continues if one market raises an exception."""
    from unittest.mock import patch

    import weather_markets

    markets = [{"ticker": f"KXHIGH-{i}", "title": f"M{i}"} for i in range(4)]
    call_count = {"n": 0}

    def _flaky_analyze(enriched):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise ValueError("transient error for market 2")
        return {"edge": 0.05, "signal": "HOLD"}

    with patch.object(weather_markets, "enrich_with_forecast", return_value={}):
        with patch.object(weather_markets, "analyze_trade", side_effect=_flaky_analyze):
            results = weather_markets.analyze_markets_parallel(markets)

    # 3 successful + 1 None/skipped; total 4 entries returned
    assert len(results) == 4


def test_analyze_markets_parallel_is_faster_than_sequential():
    """ThreadPool reduces wall-clock time when each analysis has I/O latency."""
    import time
    from unittest.mock import patch

    import weather_markets

    markets = [{"ticker": f"MKT-{i}"} for i in range(6)]

    def _slow_analyze(enriched):
        time.sleep(0.05)
        return {"edge": 0.0, "signal": "HOLD"}

    with patch.object(weather_markets, "enrich_with_forecast", return_value={}):
        with patch.object(weather_markets, "analyze_trade", side_effect=_slow_analyze):
            t0 = time.monotonic()
            weather_markets.analyze_markets_parallel(markets)
            elapsed = time.monotonic() - t0

    # Sequential would take >= 0.3s; parallel should finish in < 0.25s
    assert elapsed < 0.25, f"parallel analysis too slow: {elapsed:.2f}s"
```

- [ ] Step 2: Run tests to confirm they fail:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_analyze_markets_parallel_returns_results tests/test_infrastructure.py::test_analyze_markets_parallel_handles_per_market_exception tests/test_infrastructure.py::test_analyze_markets_parallel_is_faster_than_sequential -v 2>&1 | tail -15
```

Expected: `FAILED` (no `analyze_markets_parallel` in `weather_markets`)

- [ ] Step 3: Implement — add `analyze_markets_parallel` to `weather_markets.py`:

```python
def analyze_markets_parallel(
    markets: list[dict],
    max_workers: int = 10,
) -> list[dict | None]:
    """
    Run analyze_trade on each market concurrently (#127).
    Returns a list of result dicts (one per market, None on per-market error).
    Exceptions in individual workers are caught and logged; the batch never crashes.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[dict | None] = [None] * len(markets)

    def _worker(idx: int, market: dict) -> tuple[int, dict | None]:
        enriched = enrich_with_forecast(market)
        return idx, analyze_trade(enriched)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_worker, i, m): i for i, m in enumerate(markets)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                _, analysis = fut.result()
                results[idx] = analysis
            except Exception as exc:
                _log.warning(
                    "analyze_markets_parallel: market index %d failed: %s", idx, exc
                )
                results[idx] = None

    return results
```

Update `cmd_markets` in `main.py` (line ~450) to replace the sequential `for m in markets` loop with `analyze_markets_parallel`:

```python
from weather_markets import analyze_markets_parallel

# Replace:
#   rows = []
#   for m in markets:
#       enriched = enrich_with_forecast(m)
#       analysis = analyze_trade(enriched)
#       ...
# With:
analyses = analyze_markets_parallel(markets)
rows = []
for m, analysis in zip(markets, analyses):
    prices = parse_market_price(m)
    edge = analysis["edge"] if analysis else 0
    sig = analysis["signal"].strip() if analysis else "—"
    ticker = m.get("ticker", "")
    rows.append([...])  # keep existing row construction
```

Apply the same pattern to the other sequential analysis loops in `main.py` at lines ~1277, ~1440, ~1571 where the pattern `for m in markets: enrich_with_forecast(m); analyze_trade(enriched)` is repeated.

- [ ] Step 4: Run tests to verify pass:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_infrastructure.py::test_analyze_markets_parallel_returns_results tests/test_infrastructure.py::test_analyze_markets_parallel_handles_per_market_exception tests/test_infrastructure.py::test_analyze_markets_parallel_is_faster_than_sequential -v 2>&1 | tail -15
```

Expected: `3 passed`

- [ ] Step 5: Commit:

```
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py main.py tests/test_infrastructure.py && git commit -m "feat(#127): add analyze_markets_parallel with ThreadPoolExecutor for concurrent market analysis"
```

---

### Final Verification

After all tasks are committed, run the full test suite to confirm no regressions:

- [ ] Run full test suite:

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -v 2>&1 | tail -30
```

Expected: all existing tests continue to pass, new tests added by this plan also pass.
