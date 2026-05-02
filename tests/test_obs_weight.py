"""Tests for obs_weight_used and local_hour DB columns (Phase 6.0)."""

import sqlite3


def test_predictions_table_has_obs_weight_and_local_hour_columns(monkeypatch, tmp_path):
    """predictions table must have obs_weight_used and local_hour columns."""
    import tracker

    db_path = tmp_path / "predictions.db"
    monkeypatch.setattr(tracker, "DB_PATH", db_path)
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()

    con = sqlite3.connect(str(db_path))
    cols = [r[1] for r in con.execute("PRAGMA table_info(predictions)").fetchall()]
    con.close()

    assert "obs_weight_used" in cols, "obs_weight_used column missing from predictions"
    assert "local_hour" in cols, "local_hour column missing from predictions"
