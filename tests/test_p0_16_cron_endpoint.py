"""P0-16: api_run_cron concurrent-run guard.

Verifies that /api/run_cron returns 409 when a cron process already
holds the lock, and starts normally when no lock is held.
Auth behaviour (401 without credentials) is already covered by test_web_auth.py.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch


def _make_app():
    import web_app

    with patch("main.KALSHI_ENV", "demo"):
        app = web_app._build_app(client=MagicMock())
    app.config["TESTING"] = True
    return app


def _auth_headers(password: str = "secret") -> dict:
    encoded = base64.b64encode(f"user:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


class TestRunCronConcurrentGuard:
    def test_returns_409_when_cron_already_running(self):
        """If _is_cron_running() returns True, endpoint must return 409."""
        app = _make_app()
        with app.test_client() as c:
            with (
                patch("utils.DASHBOARD_PASSWORD", "secret"),
                patch("cron._is_cron_running", return_value=True),
            ):
                resp = c.post("/api/run_cron", headers=_auth_headers())

        assert resp.status_code == 409
        body = resp.get_json()
        assert "already running" in body.get("error", "").lower()

    def test_starts_successfully_when_no_cron_running(self):
        """If _is_cron_running() returns False and no rate limit, cron spawns."""
        app = _make_app()
        with app.test_client() as c:
            with (
                patch("utils.DASHBOARD_PASSWORD", "secret"),
                patch("cron._is_cron_running", return_value=False),
                patch("subprocess.Popen") as mock_popen,
            ):
                mock_popen.return_value = MagicMock(pid=12345)
                resp = c.post("/api/run_cron", headers=_auth_headers())

        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("status") == "started"
        mock_popen.assert_called_once()

    def test_concurrent_guard_checked_before_rate_limit(self):
        """409 must be returned even when the per-IP rate limit is not yet exceeded."""
        app = _make_app()
        with app.test_client() as c:
            with (
                patch("utils.DASHBOARD_PASSWORD", "secret"),
                patch("cron._is_cron_running", return_value=True),
                patch("subprocess.Popen") as mock_popen,
            ):
                resp = c.post("/api/run_cron", headers=_auth_headers())

        # Cron is running → 409, no subprocess spawned
        assert resp.status_code == 409
        mock_popen.assert_not_called()

    def test_auth_still_required(self):
        """Concurrent guard must not bypass authentication."""
        app = _make_app()
        with app.test_client() as c:
            with (
                patch("utils.DASHBOARD_PASSWORD", "secret"),
                patch("cron._is_cron_running", return_value=False),
            ):
                resp = c.post("/api/run_cron")  # no auth header

        assert resp.status_code == 401


class TestIsCronRunning:
    """Unit tests for the _is_cron_running() helper in cron.py."""

    def test_returns_false_when_no_lock_file(self, tmp_path, monkeypatch):
        import cron

        monkeypatch.setattr("cron.LOCK_PATH", tmp_path / ".cron.lock")
        assert cron._is_cron_running() is False

    def test_returns_false_for_dead_pid_with_psutil(self, tmp_path, monkeypatch):
        import json

        import cron

        lock_file = tmp_path / ".cron.lock"
        lock_file.write_text(
            json.dumps({"pid": 999999999, "started_at": 0, "heartbeat": 0})
        )
        monkeypatch.setattr("cron.LOCK_PATH", lock_file)
        monkeypatch.setattr("cron._PSUTIL_AVAILABLE", True)
        monkeypatch.setattr("cron._psutil", MagicMock(pid_exists=lambda p: False))

        assert cron._is_cron_running() is False

    def test_returns_true_for_live_pid_with_psutil(self, tmp_path, monkeypatch):
        import json
        import os

        import cron

        lock_file = tmp_path / ".cron.lock"
        lock_file.write_text(
            json.dumps({"pid": os.getpid(), "started_at": 0, "heartbeat": 0})
        )
        monkeypatch.setattr("cron.LOCK_PATH", lock_file)
        monkeypatch.setattr("cron._PSUTIL_AVAILABLE", True)
        monkeypatch.setattr("cron._psutil", MagicMock(pid_exists=lambda p: True))

        assert cron._is_cron_running() is True

    def test_returns_false_for_corrupt_lock_file(self, tmp_path, monkeypatch):
        import cron

        lock_file = tmp_path / ".cron.lock"
        lock_file.write_text("not valid json {{")
        monkeypatch.setattr("cron.LOCK_PATH", lock_file)

        assert cron._is_cron_running() is False
