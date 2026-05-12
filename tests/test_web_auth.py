"""P0-8: mutation endpoints must require authentication."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch


def _make_app():
    """Create a test Flask app in demo mode."""
    import web_app

    with patch("main.KALSHI_ENV", "demo"):
        app = web_app._build_app(client=MagicMock())
    app.config["TESTING"] = True
    return app


def _basic_auth(password: str) -> dict:
    encoded = base64.b64encode(f"user:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


class TestMutationEndpointsRequireAuth:
    def test_halt_without_auth_returns_401(self):
        app = _make_app()
        with app.test_client() as c:
            with patch("utils.DASHBOARD_PASSWORD", "secret"):
                resp = c.post("/api/halt", json={"reason": "test"})
        assert resp.status_code == 401

    def test_resume_without_auth_returns_401(self):
        app = _make_app()
        with app.test_client() as c:
            with patch("utils.DASHBOARD_PASSWORD", "secret"):
                resp = c.post("/api/resume")
        assert resp.status_code == 401

    def test_run_cron_without_auth_returns_401(self):
        app = _make_app()
        with app.test_client() as c:
            with patch("utils.DASHBOARD_PASSWORD", "secret"):
                resp = c.post("/api/run_cron")
        assert resp.status_code == 401

    def test_halt_with_correct_auth_succeeds(self):
        app = _make_app()
        with app.test_client() as c:
            with patch("utils.DASHBOARD_PASSWORD", "secret"):
                resp = c.post(
                    "/api/halt",
                    json={"reason": "test"},
                    headers=_basic_auth("secret"),
                )
        assert resp.status_code == 200
        assert resp.get_json()["halted"] is True

    def test_resume_with_correct_auth_succeeds(self):
        app = _make_app()
        with app.test_client() as c:
            with patch("utils.DASHBOARD_PASSWORD", "secret"):
                resp = c.post("/api/resume", headers=_basic_auth("secret"))
        assert resp.status_code == 200

    def test_halt_with_wrong_password_returns_401(self):
        app = _make_app()
        with app.test_client() as c:
            with patch("utils.DASHBOARD_PASSWORD", "secret"):
                resp = c.post(
                    "/api/halt",
                    json={"reason": "test"},
                    headers=_basic_auth("wrongpassword"),
                )
        assert resp.status_code == 401

    def test_run_cron_rate_limited_after_first_spawn(self):
        app = _make_app()
        with app.test_client() as c:
            with (
                patch("utils.DASHBOARD_PASSWORD", "secret"),
                patch("subprocess.Popen", return_value=MagicMock(pid=99)),
            ):
                resp1 = c.post("/api/run_cron", headers=_basic_auth("secret"))
                assert resp1.status_code == 200
                resp2 = c.post("/api/run_cron", headers=_basic_auth("secret"))
                assert resp2.status_code == 429

    def test_no_password_allows_open_access(self):
        """When DASHBOARD_PASSWORD is empty, mutation endpoints are open (dev mode)."""
        app = _make_app()
        with app.test_client() as c:
            with patch("utils.DASHBOARD_PASSWORD", ""):
                resp = c.post("/api/resume")
        assert resp.status_code == 200
