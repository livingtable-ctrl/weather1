"""Pass 16 (Test Quality) repro: confirms web_app.py's CSRF X-Requested-With
check works correctly today (no live bug) but that the shipped test suite
(tests/test_web_auth.py, tests/test_p0_16_cron_endpoint.py) never exercises
its rejection branch -- every _basic_auth()/_auth_headers() helper in those
files unconditionally includes X-Requested-With, so a POST with correct
Basic-auth credentials but WITHOUT the CSRF header is never tested against.

Run standalone (not part of the real suite) via:
  pytest audit/reproductions/test_csrf_header_gap_repro.py -q
from the repo root. Uses the same _make_app() pattern as test_web_auth.py.
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


def _basic_auth_no_csrf(password: str) -> dict:
    encoded = base64.b64encode(f"user:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}  # deliberately no X-Requested-With


def test_correct_password_without_csrf_header_is_rejected():
    """This is the actual security property the CSRF fix (commit 0edf818b)
    is supposed to guarantee, and it currently holds -- but no test in the
    shipped suite asserts it. If a future refactor of _check_auth ever
    dropped the X-Requested-With condition (e.g. collapsed the `or` into
    always-true), every existing web_app auth test would keep passing
    (they all send the header) and this regression would ship silently."""
    app = _make_app()
    with app.test_client() as c:
        with patch("utils.DASHBOARD_PASSWORD", "secret"):
            resp = c.post(
                "/api/halt",
                json={"reason": "test"},
                headers=_basic_auth_no_csrf("secret"),
            )
    assert resp.status_code == 401, (
        f"expected 401 (CSRF header missing) but got {resp.status_code} -- "
        f"the CSRF check either passed anyway or the endpoint behaved "
        f"differently than test_web_auth.py's always-header-present tests "
        f"would ever reveal"
    )
