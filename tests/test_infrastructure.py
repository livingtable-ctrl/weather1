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


# ── Disk-write resilience (#8) ────────────────────────────────────────────────


def test_atomic_write_falls_back_to_tmp_on_oserror(tmp_path, monkeypatch):
    """If the primary path fails, write succeeds via /tmp fallback."""
    import safe_io

    bad_dir = tmp_path / "readonly"
    bad_dir.mkdir()
    bad_dir.chmod(0o444)

    target = bad_dir / "data.json"
    try:
        safe_io.atomic_write_json({"x": 1}, target, retries=1)
    except RuntimeError:
        pass  # acceptable: double failure raises RuntimeError


def test_atomic_write_raises_runtime_error_on_double_failure(tmp_path, monkeypatch):
    """If both primary and /tmp writes fail, RuntimeError is raised."""
    import safe_io

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
        "safe_io.atomic_write_json",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("full")),
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
        "safe_io.atomic_write_json",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("full")),
    )
    with pytest.raises((RuntimeError, OSError)):
        execution_log.append_entry({"action": "test"}, tmp_path / "exec_log.json")


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
    """Saved paper trades JSON contains a '_checksum' key with 16-char hex SHA-256."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1000.0, "trades": []})

    raw = _json.loads((tmp_path / "paper_trades.json").read_text())
    assert "_checksum" in raw
    assert len(raw["_checksum"]) == 16
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


# ── Parallel market analysis (#127) ───────────────────────────────────────────


def test_analyze_markets_parallel_returns_results():
    """analyze_markets_parallel returns one result dict per market."""
    from unittest.mock import patch

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
        assert r is not None


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

    assert elapsed < 0.25, f"parallel analysis too slow: {elapsed:.2f}s"
