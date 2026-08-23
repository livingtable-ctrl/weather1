import json
import json as _json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from circuit_breaker import CircuitBreaker
from kalshi_client import _build_session  # type: ignore[attr-defined]
from safe_io import atomic_write_json

# ── Circuit Breaker ────────────────────────────────────────────────────────────


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
    assert not cb.is_open()


def test_circuit_resets_on_success():
    cb = CircuitBreaker(name="test4", failure_threshold=3, recovery_timeout=1)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert not cb.is_open()
    assert cb._failure_count == 0


# ── safe_io ────────────────────────────────────────────────────────────────────


def test_atomic_write_creates_file(tmp_path: Path):
    target = tmp_path / "data.json"
    atomic_write_json({"key": "value"}, target)
    assert target.exists()
    assert json.loads(target.read_text()) == {"key": "value"}


def test_atomic_write_is_atomic(tmp_path: Path):
    target = tmp_path / "data.json"
    atomic_write_json({"original": True}, target)
    atomic_write_json({"updated": True}, target)
    assert json.loads(target.read_text()) == {"updated": True}


# ── HTTPAdapter session ────────────────────────────────────────────────────────


def test_session_has_retry_adapter():
    session = _build_session()
    adapter = session.get_adapter("https://")
    assert adapter is not None
    assert hasattr(adapter, "max_retries")


# ── API request audit logging (#69) ───────────────────────────────────────────


def test_log_api_request_writes_to_db(tmp_path):
    import tracker

    orig_path = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "test.db"
    tracker._db_initialized = False
    tracker.init_db()

    tracker.log_api_request("GET", "/markets", 200, 123.4)

    with tracker._conn() as con:
        row = con.execute(
            "SELECT * FROM api_requests WHERE endpoint='/markets'"
        ).fetchone()
    assert row is not None
    assert row["status_code"] == 200

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False


# ── Async market fetching (#127) ──────────────────────────────────────────────


def test_market_fetch_uses_threadpool():
    """Verify get_weather_markets doesn't crash and runs in reasonable time."""
    from unittest.mock import MagicMock

    import weather_markets

    mock_client = MagicMock()
    mock_client.get_markets.return_value = []

    t0 = time.monotonic()
    try:
        weather_markets.get_weather_markets(mock_client, force=True)
    except Exception:
        pass
    elapsed = time.monotonic() - t0
    assert elapsed < 10


def test_market_fetch_partial_results_on_timeout(caplog):
    """A timeout mid-fetch must return whatever partial results were already
    collected (not crash/raise), and the warning must reflect the current
    40s budget, not a stale hardcoded 30s from before the timeout was bumped."""
    import logging
    from unittest.mock import MagicMock, patch

    import weather_markets

    mock_client = MagicMock()
    mock_client.get_markets.return_value = [{"ticker": "KXHIGHNY-26JUL04-T90"}]

    with caplog.at_level(logging.WARNING):
        with patch("weather_markets.as_completed", side_effect=TimeoutError):
            result = weather_markets.get_weather_markets(mock_client, force=True)

    assert isinstance(result, list)  # partial-results fallback, not a crash
    assert any(
        "timed out after 40s" in r.message
        for r in caplog.records
        if r.name == "weather_markets"
    )


# ── DB migrations (#99) ───────────────────────────────────────────────────────


def test_migrations_are_idempotent(tmp_path):
    import tracker

    orig_path = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "migrate_test.db"
    tracker._db_initialized = False

    tracker.init_db()
    tracker._db_initialized = False
    tracker.init_db()  # second call must not raise

    with tracker._conn() as con:
        row = con.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False


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


# ── _get_obs_station cache (backlog.txt "ForecastCache EXISTS, BUT ~14
# HAND-ROLLED TTL DICTS" -- _station_cache migrated to PersistentForecastCache
# 2026-07-25) ─────────────────────────────────────────────────────────────────


def test_get_obs_station_cache_hit_skips_network_call(monkeypatch):
    """A cached (lat, lon) -> station_id lookup must not hit the network."""
    import nws

    # ttl_secs/max_size match the real nws.py construction site exactly, not
    # PersistentForecastCache's own defaults -- this test should exercise the
    # production config, not an incidental default.
    monkeypatch.setattr(
        nws,
        "_station_cache",
        nws.PersistentForecastCache(ttl_secs=float("inf"), max_size=100_000),
    )
    nws._station_cache.set((round(40.0, 4), round(-75.0, 4)), "KPHL")

    def _boom(*a, **kw):
        raise AssertionError("network should not be called on a cache hit")

    monkeypatch.setattr(nws, "_get", _boom)
    assert nws._get_obs_station(40.0, -75.0) == "KPHL"


def test_get_obs_station_cache_miss_fetches_and_persists(monkeypatch, tmp_path):
    """A cache miss fetches from the network, stores the result in
    _station_cache, and persists the whole cache to disk (matching the
    plain-dict version's exact behavior before this migration)."""
    import nws

    monkeypatch.setattr(
        nws,
        "_station_cache",
        nws.PersistentForecastCache(ttl_secs=float("inf"), max_size=100_000),
    )
    monkeypatch.setattr(nws, "_STATION_CACHE_PATH", tmp_path / "station_cache.json")

    calls = []

    def _fake_get(url, params=None):
        calls.append(url)
        if "/points/" in url:
            return {"properties": {"observationStations": "https://x/stations"}}
        return {"features": [{"properties": {"stationIdentifier": "KORD"}}]}

    monkeypatch.setattr(nws, "_get", _fake_get)

    result = nws._get_obs_station(41.8781, -87.6298)
    assert result == "KORD"
    assert len(calls) == 2  # /points then /observationStations
    assert nws._station_cache.get((round(41.8781, 4), round(-87.6298, 4))) == "KORD"

    # Persisted to disk -- a fresh cache instance loading the same path gets it back
    fresh = nws.PersistentForecastCache(ttl_secs=float("inf"), max_size=100_000)
    fresh.load_from_disk(nws._STATION_CACHE_PATH, nws._station_str_to_key)
    assert fresh.get((round(41.8781, 4), round(-87.6298, 4))) == "KORD"

    # Second call for the same coords must be a pure cache hit -- no new network calls
    result2 = nws._get_obs_station(41.8781, -87.6298)
    assert result2 == "KORD"
    assert len(calls) == 2


def test_station_cache_loads_pre_migration_flat_format(tmp_path):
    """Regression: the real data/.nws_station_cache.json file on disk was
    written by the pre-migration plain-dict _save_station_cache (a flat
    "lat,lon" -> station_id JSON object) before this session's
    PersistentForecastCache migration existed. This pins that nws.py's real
    _station_str_to_key helper -- not a test-local copy -- still parses that
    exact legacy format on load, so existing on-disk caches aren't silently
    discarded on the next process start. (_station_key_to_str, the write
    side, is exercised separately by
    test_get_obs_station_cache_miss_fetches_and_persists.)"""
    import json

    import nws

    legacy_path = tmp_path / "legacy_station_cache.json"
    legacy_path.write_text(
        json.dumps({"40.7789,-73.9692": "KNYC", "41.995,-87.9336": "KORD"})
    )

    fresh = nws.PersistentForecastCache(ttl_secs=float("inf"), max_size=100_000)
    fresh.load_from_disk(legacy_path, nws._station_str_to_key)
    assert fresh.get((40.7789, -73.9692)) == "KNYC"
    assert fresh.get((41.995, -87.9336)) == "KORD"


def test_get_obs_station_does_not_cache_a_falsy_station_id(monkeypatch, tmp_path):
    """Regression: if NWS ever returns a null/empty stationIdentifier, it
    must not be cached -- with ttl_secs=inf, caching a bad result would mean
    NEVER retrying that coordinate again for the life of the process. The
    plain-dict version had the same theoretical exposure (it cached
    unconditionally too), but .get()'s inability to distinguish "cached
    None" from "no entry" makes guarding against it here the correct fix
    rather than an incidental behavior change."""
    import nws

    monkeypatch.setattr(
        nws,
        "_station_cache",
        nws.PersistentForecastCache(ttl_secs=float("inf"), max_size=100_000),
    )
    monkeypatch.setattr(nws, "_STATION_CACHE_PATH", tmp_path / "station_cache.json")

    def _fake_get(url, params=None):
        if "/points/" in url:
            return {"properties": {"observationStations": "https://x/stations"}}
        return {"features": [{"properties": {"stationIdentifier": None}}]}

    monkeypatch.setattr(nws, "_get", _fake_get)

    result = nws._get_obs_station(1.0, 2.0)
    assert result is None
    assert nws._station_cache.get((1.0, 2.0)) is None
    assert len(nws._station_cache) == 0
    assert not nws._STATION_CACHE_PATH.exists(), (
        "a falsy station_id must not trigger a disk persist either"
    )


# ── Disk-write resilience (#8) ────────────────────────────────────────────────


def test_atomic_write_falls_back_to_tmp_on_oserror(tmp_path, monkeypatch):
    """P1-6: primary path failure raises AtomicWriteError (emergency copy written to tmp).

    On Windows, chmod(0o444) does not block writes, so success is also acceptable.
    """
    import safe_io
    from safe_io import AtomicWriteError

    bad_dir = tmp_path / "readonly"
    bad_dir.mkdir()
    bad_dir.chmod(0o444)

    target = bad_dir / "data.json"
    try:
        safe_io.atomic_write_json({"x": 1}, target, retries=1)
        # Windows: chmod doesn't restrict directory writes — success is acceptable
    except (AtomicWriteError, RuntimeError, OSError):
        pass  # Linux/macOS: readonly dir correctly raises


def test_atomic_write_raises_on_double_failure(tmp_path, monkeypatch):
    """If both primary and /tmp writes fail, AtomicWriteError is raised."""
    import safe_io
    from safe_io import AtomicWriteError

    # Isolate the default emergency-copy candidate (project_root()/"data"/
    # ".emergency") to tmp_path -- without this, mkdir() for that candidate
    # (not itself mocked by the builtins.open patch below) creates a real,
    # if empty, data/.emergency/ directory in this actual repo.
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    call_count = {"n": 0}

    def _always_fail(*a, **kw):
        call_count["n"] += 1
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _always_fail)

    with pytest.raises((AtomicWriteError, RuntimeError, OSError)):
        safe_io.atomic_write_json({"x": 1}, tmp_path / "data.json", retries=1)


def test_alerts_write_raises_on_failure(tmp_path, monkeypatch):
    """alerts.py write function raises RuntimeError if disk write fails twice."""
    try:
        import alerts
    except ImportError:
        pytest.skip("alerts module not present")

    monkeypatch.setattr(
        "safe_io.atomic_write_json",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("full")),
    )
    with pytest.raises((RuntimeError, OSError)):
        alerts.save_alerts([{"msg": "test"}], tmp_path / "alerts.json")


def test_execution_log_write_raises_on_failure(tmp_path, monkeypatch):
    """execution_log.py append_entry propagates OSError when the file cannot be written."""
    try:
        import execution_log
    except ImportError:
        pytest.skip("execution_log module not present")

    # append_entry now uses plain file-append (JSONL); make the target unwritable
    target = tmp_path / "exec_log.jsonl"
    target.touch()
    target.chmod(0o444)  # read-only
    try:
        with pytest.raises((RuntimeError, OSError, PermissionError)):
            execution_log.append_entry({"action": "test"}, target)
    finally:
        target.chmod(0o644)  # restore so tmp_path cleanup works


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

    tracker.log_api_request("GET", "/events", 200, 42.0)

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False


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
    import sqlite3

    import tracker

    orig_path = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "incr_test.db"
    tracker._db_initialized = False

    con = sqlite3.connect(str(tracker.DB_PATH))
    con.execute("PRAGMA user_version=0")
    con.close()

    tracker.init_db()

    with tracker._conn() as con:
        version = con.execute("PRAGMA user_version").fetchone()[0]
    assert version == tracker._SCHEMA_VERSION

    tracker.DB_PATH = orig_path
    tracker._db_initialized = False


# ── SHA-256 checksum corruption detection (#102) ──────────────────────────────


def test_paper_save_embeds_sha256_checksum(tmp_path, monkeypatch):
    """Saved paper trades JSON contains a '_checksum' key with full 64-char hex SHA-256."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1000.0, "trades": []})

    raw = _json.loads((tmp_path / "paper_trades.json").read_text())
    assert "_checksum" in raw
    # P1-5: new writes use full 64-char SHA-256 hex (was 16-char prefix)
    assert len(raw["_checksum"]) == 64
    int(raw["_checksum"], 16)  # verify valid hex


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
    con.execute(
        "INSERT INTO predictions (city, target_date) VALUES ('NYC', '2026-04-10')"
    )
    con.commit()
    con.close()

    count = main.verify_db_backup(db)
    assert count == 1


def test_verify_db_backup_raises_on_empty(tmp_path):
    """verify_db_backup returns 0 when predictions table is empty."""
    import sqlite3

    import main

    db = tmp_path / "predictions_empty.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY, city TEXT)")
    con.commit()
    con.close()

    result = main.verify_db_backup(db)
    assert result == 0


def test_auto_backup_logs_verification(tmp_path, caplog):
    """verify_db_backup logs 'backup verified' with path and row count."""
    import logging
    import sqlite3

    import main

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


class TestTrackerConnClosesConnection:
    """AUD-0048: tracker._conn()'s ~100+ `with _conn() as con:` call sites
    relied on sqlite3.Connection's own context-manager protocol, which only
    commits/rolls back on exit -- it does NOT close the connection. _conn()
    itself was converted to a generator-based context manager so every call
    site gets a real con.close() for free, without any of them changing.
    Mirrors execution_log.py's own TestConnClosesConnection (same fix,
    same tests, different module)."""

    def setup_method(self):
        import tracker

        self._orig_path = tracker.DB_PATH

    def teardown_method(self):
        import tracker

        tracker.DB_PATH = self._orig_path
        tracker._db_initialized = False

    def test_connection_is_closed_after_the_with_block_exits(self, tmp_path):
        import sqlite3

        import tracker

        tracker.DB_PATH = tmp_path / "test_conn_close.db"
        tracker._db_initialized = False
        tracker.init_db()

        with tracker._conn() as con:
            con.execute("SELECT 1")

        with pytest.raises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

    def test_a_successful_write_still_commits(self, tmp_path):
        import tracker

        tracker.DB_PATH = tmp_path / "test_conn_commit.db"
        tracker._db_initialized = False
        tracker.init_db()

        with tracker._conn() as con:
            con.execute(
                "INSERT INTO api_requests (method, endpoint, status_code, "
                "latency_ms, logged_at) VALUES (?, ?, ?, ?, datetime('now'))",
                ("GET", "/commit-test", 200, 12.3),
            )

        with tracker._conn() as con2:
            row = con2.execute(
                "SELECT endpoint FROM api_requests WHERE endpoint=?",
                ("/commit-test",),
            ).fetchone()
        assert row is not None, "a write inside the block must be committed on exit"

    def test_a_write_is_rolled_back_and_connection_still_closes_on_exception(
        self, tmp_path
    ):
        import sqlite3

        import tracker

        tracker.DB_PATH = tmp_path / "test_conn_rollback.db"
        tracker._db_initialized = False
        tracker.init_db()

        with pytest.raises(RuntimeError):
            with tracker._conn() as con:
                con.execute(
                    "INSERT INTO api_requests (method, endpoint, status_code, "
                    "latency_ms, logged_at) VALUES "
                    "(?, ?, ?, ?, datetime('now'))",
                    ("GET", "/rollback-test", 200, 12.3),
                )
                raise RuntimeError("simulated failure mid-transaction")

        with pytest.raises(sqlite3.ProgrammingError):
            con.execute("SELECT 1")

        with tracker._conn() as con2:
            row = con2.execute(
                "SELECT endpoint FROM api_requests WHERE endpoint=?",
                ("/rollback-test",),
            ).fetchone()
        assert row is None, "a write inside a raising block must be rolled back"
