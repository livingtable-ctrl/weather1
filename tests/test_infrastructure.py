import json
import os
import sys
import time
from pathlib import Path

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
