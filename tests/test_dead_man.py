from datetime import UTC, datetime, timedelta


def test_heartbeat_stale_detection(tmp_path, monkeypatch):
    import watchdog

    monkeypatch.setattr(watchdog, "HEARTBEAT_PATH", tmp_path / "last_heartbeat.txt")

    # No file → stale
    assert watchdog.is_heartbeat_stale(max_age_hours=48) is True

    # Recent file → not stale
    heartbeat_file = tmp_path / "last_heartbeat.txt"
    heartbeat_file.write_text(datetime.now(UTC).isoformat())
    assert watchdog.is_heartbeat_stale(max_age_hours=48) is False

    # Old file → stale
    old_time = (datetime.now(UTC) - timedelta(hours=49)).isoformat()
    heartbeat_file.write_text(old_time)
    assert watchdog.is_heartbeat_stale(max_age_hours=48) is True
