"""Tests for P0.5 — get_state_snapshot() in paper.py and cron logging."""

import importlib


def test_get_state_snapshot_returns_required_keys(tmp_path, monkeypatch):
    """get_state_snapshot must return balance, open_trades_count, peak_balance, and snapshot_at."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)

    from paper import get_state_snapshot

    snap = get_state_snapshot()
    assert "balance" in snap
    assert "open_trades_count" in snap
    assert "peak_balance" in snap
    assert "snapshot_at" in snap
    assert isinstance(snap["balance"], float)
    assert isinstance(snap["open_trades_count"], int)
    assert snap["open_trades_count"] >= 0


def test_state_snapshot_balance_matches_get_balance(tmp_path, monkeypatch):
    """get_state_snapshot balance must equal get_balance()."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)

    from paper import get_balance, get_state_snapshot

    snap = get_state_snapshot()
    assert snap["balance"] == get_balance()


def test_state_snapshot_peak_matches_get_peak_balance(tmp_path, monkeypatch):
    """get_state_snapshot peak_balance must equal get_peak_balance()."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)

    from paper import get_peak_balance, get_state_snapshot

    snap = get_state_snapshot()
    assert snap["peak_balance"] == get_peak_balance()


def test_cmd_cron_logs_state_snapshot(tmp_path, monkeypatch):
    """cmd_cron must log a state snapshot line on each run."""
    import logging

    import main
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    importlib.reload(paper)

    # Patch out everything that would make cron do real work
    monkeypatch.setattr(main, "get_weather_markets", lambda client: [])
    monkeypatch.setattr(
        paper,
        "get_state_snapshot",
        lambda: {
            "balance": 1000.0,
            "open_trades_count": 0,
            "peak_balance": 1000.0,
            "snapshot_at": "2026-01-01T00:00:00+00:00",
        },
    )
    # Isolate from real data/ files so kill switch and black swan don't interfere
    monkeypatch.setattr(main, "RUNNING_FLAG_PATH", tmp_path / ".cron_running")
    monkeypatch.setattr(main, "KILL_SWITCH_PATH", tmp_path / ".kill_switch")
    monkeypatch.setattr("alerts.run_black_swan_check", lambda: [])
    monkeypatch.setattr("alerts.run_anomaly_check", lambda log_results=False: None)

    log_records = []

    class Capture(logging.Handler):
        def emit(self, record):
            log_records.append(record)

    handler = Capture()
    handler.setLevel(logging.DEBUG)
    main_logger = logging.getLogger("main")
    main_logger.setLevel(logging.DEBUG)
    main_logger.addHandler(handler)
    try:
        from unittest.mock import MagicMock

        client = MagicMock()
        main.cmd_cron(client)
    except BaseException:
        pass  # cron ends with sys.exit(0) — that's fine
    finally:
        main_logger.removeHandler(handler)
        main_logger.setLevel(logging.NOTSET)

    snapshot_logged = any(
        "snapshot" in r.getMessage().lower() or "balance" in r.getMessage().lower()
        for r in log_records
    )
    assert snapshot_logged, "cmd_cron must log a state snapshot on each run"
