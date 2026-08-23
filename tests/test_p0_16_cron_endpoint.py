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
    # X-Requested-With matches the bundled frontend's authHeader() helper --
    # web_app.py's _check_auth now requires it on state-changing requests as a
    # CSRF mitigation (a bare cross-site <form> POST can't set custom headers).
    return {"Authorization": f"Basic {encoded}", "X-Requested-With": "XMLHttpRequest"}


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
        import time

        import cron

        lock_file = tmp_path / ".cron.lock"
        # started_at must be a realistic recent timestamp, not 0 (Unix
        # epoch) -- _is_cron_running now applies _STUCK_RUNNING_BACKSTOP_SECS
        # (24h) as a final backstop (M6/opus-review-caught), and an
        # epoch-0 started_at would fall outside it, incorrectly returning
        # False for what this test means to be the ordinary live case.
        lock_file.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time(),
                    "heartbeat": time.time(),
                }
            )
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

    def test_returns_false_when_live_pid_was_reused_by_different_process(
        self, tmp_path, monkeypatch
    ):
        """AUD (batch-30 item 1): pid_exists() alone can't tell a genuinely
        running cron process apart from an unrelated process that Windows
        handed the same (now-stale) PID after cron exited -- create_time
        must disagree in that case, and _is_cron_running must report False,
        not stay stuck reporting "running" forever. Mutation-tested:
        removing the `and not cron._cron_lock_pid_reused(...)` check makes
        this fail (falls back to True from pid_exists() alone)."""
        import json
        import os

        import cron

        lock_file = tmp_path / ".cron.lock"
        lock_file.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": 0,
                    "heartbeat": 0,
                    "create_time": 1000.0,
                }
            )
        )
        monkeypatch.setattr("cron.LOCK_PATH", lock_file)
        monkeypatch.setattr("cron._PSUTIL_AVAILABLE", True)
        mock_psutil = MagicMock(pid_exists=lambda p: True)
        mock_psutil.Process.return_value = MagicMock(create_time=lambda: 1000.0 + 3600)
        monkeypatch.setattr("cron._psutil", mock_psutil)

        assert cron._is_cron_running() is False

    def test_returns_false_beyond_stuck_running_backstop_even_when_unverifiable(
        self, tmp_path, monkeypatch
    ):
        """M6 (opus-review-caught): _cron_lock_pid_reused correctly returns
        False (i.e. "not disproven") when it can't positively confirm PID
        reuse -- e.g. querying the process raises AccessDenied because the
        reassigned PID now belongs to a protected/other-user process. Before
        this fix, that made _is_cron_running report "running" FOREVER (the
        exact permanent-lock-out symptom this whole batch exists to
        eliminate, just relocated from the acquire path to this read-only
        display/rate-limit path -- see cron.py:965/1042's web_app.py
        callers). _STUCK_RUNNING_BACKSTOP_SECS (24h) exists specifically to
        self-heal that case eventually. Mutation-tested: removing the
        `(_time.time() - started_at) < _STUCK_RUNNING_BACKSTOP_SECS` guard
        (returning True unconditionally once reuse can't be disproven) makes
        this fail."""
        import json
        import os
        import time

        import cron

        lock_file = tmp_path / ".cron.lock"
        lock_file.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time() - cron._STUCK_RUNNING_BACKSTOP_SECS - 1,
                    "heartbeat": time.time() - cron._STUCK_RUNNING_BACKSTOP_SECS - 1,
                    "create_time": 1000.0,
                }
            )
        )
        monkeypatch.setattr("cron.LOCK_PATH", lock_file)
        monkeypatch.setattr("cron._PSUTIL_AVAILABLE", True)
        mock_psutil = MagicMock(pid_exists=lambda p: True)

        class _FakeAccessDenied(Exception):
            pass

        mock_psutil.Process.side_effect = _FakeAccessDenied("denied")
        monkeypatch.setattr("cron._psutil", mock_psutil)

        assert cron._is_cron_running() is False

    def test_still_true_well_within_stuck_running_backstop(self, tmp_path, monkeypatch):
        """The new 24h backstop must not make an ordinary, still-genuinely-
        long-running session (well short of 24h) read as "not running" --
        proves the backstop threshold itself, not just its existence."""
        import json
        import os
        import time

        import cron

        lock_file = tmp_path / ".cron.lock"
        lock_file.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": time.time() - 3600,  # 1h -- far under 24h
                    "heartbeat": time.time() - 3600,
                    "create_time": 1000.0,
                }
            )
        )
        monkeypatch.setattr("cron.LOCK_PATH", lock_file)
        monkeypatch.setattr("cron._PSUTIL_AVAILABLE", True)
        mock_psutil = MagicMock(pid_exists=lambda p: True)
        mock_psutil.Process.return_value = MagicMock(create_time=lambda: 1000.0)
        monkeypatch.setattr("cron._psutil", mock_psutil)

        assert cron._is_cron_running() is True
